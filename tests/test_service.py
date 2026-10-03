"""Tests for the component service split (IPC-hosted, supervised subprocesses).

A tiny throwaway service is spawned as a real child process so the whole path —
spawn, authenticated ping, request/response, health, crash/restart, stop — is
exercised for real, not mocked.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

import pytest

from blaxcy.config import project_root
from blaxcy.service import (
    ProcessComponent,
    ServiceClient,
    ServiceError,
    ServiceServer,
)
from blaxcy.supervisor import Supervisor

_TRIVIAL_SERVICE = """
import os
from blaxcy.service import ServiceServer, watch_parent


def boom():
    raise ValueError("kaboom")


server = ServiceServer(
    "trivial",
    {
        "health": lambda: {"ok": True, "pid": os.getpid()},
        "echo": lambda value=0: {"value": value},
        "boom": boom,
    },
    os.environ["BLAXCY_TEST_SOCK"],
    os.environ["BLAXCY_TEST_SECRET"],
)
watch_parent(server)
server.run_forever()
"""


def _spawn_trivial(tmp_path, name="trivial", startup_timeout=20.0):
    sock = tmp_path / "svc.sock"
    comp = ProcessComponent(
        name,
        [sys.executable, "-c", _TRIVIAL_SERVICE],
        socket_path=sock,
        secret="unit-secret",
        env={
            "BLAXCY_TEST_SOCK": str(sock),
            "BLAXCY_TEST_SECRET": "unit-secret",
            "PYTHONPATH": str(project_root()),
        },
        cwd=str(project_root()),
        startup_timeout=startup_timeout,
    )
    return comp


# --------------------------------------------------------------------------- #
# server/client in-process
# --------------------------------------------------------------------------- #
@pytest.fixture
def local_service(tmp_path):
    sock = tmp_path / "local.sock"
    server = ServiceServer(
        "local",
        {"health": lambda: {"ok": True}, "echo": lambda value=0: {"value": value},
         "boom": lambda: (_ for _ in ()).throw(ValueError("x"))},
        sock, "s3cret")
    server.start()
    yield sock, "s3cret", server
    server.stop()


def test_server_client_round_trip_and_capabilities(local_service):
    sock, secret, _ = local_service
    client = ServiceClient(sock, secret)
    assert client.ping()["service"] == "local"
    assert client.call("health") == {"ok": True}
    assert client.call("echo", value=7) == {"value": 7}
    assert "echo" in client.capabilities()["methods"]


def test_wrong_secret_is_rejected(local_service):
    sock, _, _ = local_service
    with pytest.raises(ServiceError):
        ServiceClient(sock, "wrong").call("health")


def test_unknown_method_is_rejected(local_service):
    sock, secret, _ = local_service
    with pytest.raises(ServiceError):
        ServiceClient(sock, secret).call("does-not-exist")


def test_handler_exception_becomes_service_error(local_service):
    sock, secret, _ = local_service
    with pytest.raises(ServiceError):
        ServiceClient(sock, secret).call("boom")


def test_shutdown_message_stops_run_forever(tmp_path):
    import threading

    sock = tmp_path / "shut.sock"
    server = ServiceServer("s", {"health": lambda: {"ok": True}}, sock, "k")
    thread = threading.Thread(target=server.run_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not sock.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    ServiceClient(sock, "k").shutdown()
    thread.join(timeout=5)
    assert not thread.is_alive()


# --------------------------------------------------------------------------- #
# real subprocess
# --------------------------------------------------------------------------- #
def test_process_component_spawns_serves_and_stops(tmp_path):
    comp = _spawn_trivial(tmp_path)
    comp.start()
    try:
        assert comp.is_running()
        assert comp.health()["alive"] is True
        assert comp.health()["ok"] is True
        assert comp.client().call("echo", value=42) == {"value": 42}
    finally:
        comp.stop()
    assert not comp.is_running()
    assert not comp.socket_path.exists()


def test_process_component_reports_startup_failure(tmp_path):
    comp = ProcessComponent(
        "dies",
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        socket_path=tmp_path / "dies.sock",
        secret="k",
        startup_timeout=5.0,
    )
    with pytest.raises(RuntimeError):
        comp.start()


class RecordingBody:
    def __init__(self):
        self.releases = 0

    def panic_release(self):
        self.releases += 1


def test_supervisor_restarts_a_crashed_service_with_safe_release(tmp_path):
    body = RecordingBody()
    sup = Supervisor(body=body, max_restarts=3)
    comp = _spawn_trivial(tmp_path)
    sup.register_process(comp)
    sup.start_all()
    try:
        assert sup.health()["trivial"]["state"] == "running"
        first_pid = comp._proc.pid
        os.kill(first_pid, signal.SIGKILL)  # simulate a crash
        time.sleep(0.3)

        events = sup.check_once()
        assert any(e["event"] == "heartbeat_lost" for e in events)
        assert any(e["event"] == "restarted" for e in events)
        assert body.releases >= 1  # safety: inputs released before restart
        assert comp.is_running()
        assert comp._proc.pid != first_pid
        assert sup.health()["trivial"]["state"] == "degraded"
    finally:
        sup.stop_all()
    assert not comp.is_running()


# --------------------------------------------------------------------------- #
# RemoteEye degradation is explicit, never silent
# --------------------------------------------------------------------------- #
def test_service_exits_when_its_supervisor_disappears(tmp_path):
    """A service must not outlive a parent that died without calling stop()."""
    sock = tmp_path / "orphan.sock"
    comp = ProcessComponent(
        "trivial",
        [sys.executable, "-c", _TRIVIAL_SERVICE],
        socket_path=sock,
        secret="unit-secret",
        env={
            "BLAXCY_TEST_SOCK": str(sock),
            "BLAXCY_TEST_SECRET": "unit-secret",
            "PYTHONPATH": str(project_root()),
            "BLAXCY_SUPERVISOR_PID": "999999",   # a pid that is not our parent
            "BLAXCY_PARENT_CHECK_S": "0.2",
        },
        cwd=str(project_root()),
        startup_timeout=20.0,
    )
    comp.start()
    try:
        proc = comp._proc
        deadline = time.monotonic() + 8.0
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert proc.poll() is not None, "service outlived its vanished supervisor"
    finally:
        comp.stop()


def test_remote_eye_falls_back_and_counts_degradation(tmp_path):
    from blaxcy.config import Settings
    from blaxcy.eye.service import RemoteEye

    class FakeEye:
        def current(self):
            return "local-state"

        def health(self):
            return {"running": True}

        def start(self):
            self.started = True

    settings = Settings(root=tmp_path)
    settings.runtime_dir = tmp_path / "runtime"
    remote = RemoteEye(settings, fallback=FakeEye())
    assert remote.current() == "local-state"      # service socket does not exist
    assert remote.degraded_calls == 1
    assert remote.health()["degraded_calls"] == 1
