"""Supervisor soak test: repeatedly crash **every** split service.

Unlike the single-crash tests, this drives each split component through several
crash/restart cycles and asserts the full safety contract each time: heartbeat
loss is detected, inputs are safely released before the restart, a new process
with a new pid comes up, the component is reported `degraded` while it recovers,
and it is genuinely serving again. It also proves restart exhaustion ends in
`failed` with no restart, and that a running `Application` reports the counters.

The Eye runs with `DISPLAY=""` so it selects the deterministic fake backend —
the soak test must never touch the real desktop.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

from blaxcy.config import Settings, project_root
from blaxcy.service import ProcessComponent, service_command, service_socket
from blaxcy.state_store import StateStore
from blaxcy.supervisor import Supervisor

CYCLES = 3

# (service name, extra child env). The eye is forced headless.
_SERVICES = [
    ("memory", {}),
    ("brain", {}),
    ("eye", {"DISPLAY": ""}),
]


class RecordingBody:
    def __init__(self) -> None:
        self.releases = 0

    def panic_release(self) -> None:
        self.releases += 1


def _spawn(tmp_path: Path, name: str,
           extra_env: dict[str, str]) -> tuple[Settings, ProcessComponent]:
    settings = Settings(root=tmp_path)
    settings.ensure_dirs()
    env = {"BLAXCY_ROOT": str(tmp_path), "PYTHONPATH": str(project_root())}
    env.update(extra_env)
    comp = ProcessComponent(
        name, service_command(name),
        socket_path=service_socket(settings, name),
        secret=settings.ipc_secret(),
        env=env, cwd=str(project_root()), startup_timeout=40.0,
    )
    return settings, comp


def _wait_dead(comp: ProcessComponent, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while comp.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not comp.is_running(), "service did not die after SIGKILL"


@pytest.mark.parametrize("name,extra_env", _SERVICES, ids=[s[0] for s in _SERVICES])
def test_supervisor_soak_restarts_each_split_service(tmp_path, name, extra_env):
    settings, comp = _spawn(tmp_path, name, extra_env)
    body = RecordingBody()
    sup = Supervisor(body=body, max_restarts=10,
                     state_store=StateStore(Path(settings.state_dir) / "state.json"))
    sup.register_process(comp)
    sup.start_all()
    try:
        assert sup.health()[name]["state"] == "running"

        for cycle in range(1, CYCLES + 1):
            old_pid = comp.pid
            os.kill(old_pid, signal.SIGKILL)
            _wait_dead(comp)

            events = sup.check_once()
            assert any(e["event"] == "heartbeat_lost" for e in events), events
            assert any(e["event"] == "restarted" for e in events), events

            # Safety: held input is released before any restart.
            assert body.releases >= cycle
            # Recovery: a new process, actually serving.
            assert comp.is_running()
            assert comp.pid != old_pid
            assert comp.health()["alive"] is True

            info = sup.health()[name]
            assert info["restarts"] == cycle
            # `degraded` = running but recently unhealthy — reported, not hidden.
            assert info["state"] == "degraded", info
    finally:
        sup.stop_all()

    assert not comp.is_running()
    assert not comp.socket_path.exists()          # no leftover socket / orphan


def test_supervisor_soak_exhaustion_ends_failed(tmp_path):
    """Past `max_restarts` the supervisor must stop trying and report `failed`."""
    settings, comp = _spawn(tmp_path, "memory", {})
    sup = Supervisor(body=RecordingBody(), max_restarts=2)
    sup.register_process(comp)
    sup.start_all()
    try:
        for _ in range(2):                        # the two allowed restarts
            os.kill(comp.pid, signal.SIGKILL)
            _wait_dead(comp)
            events = sup.check_once()
            assert any(e["event"] == "restarted" for e in events)

        os.kill(comp.pid, signal.SIGKILL)         # one crash too many
        _wait_dead(comp)
        events = sup.check_once()
        assert any(e["event"] == "restart_exhausted" for e in events)
        assert sup.health()["memory"]["state"] == "failed"
        assert not comp.is_running()
    finally:
        sup.stop_all()


def test_supervisor_persists_counters_for_blaxcy_services(tmp_path):
    """`blaxcy services` reads the last persisted supervisor snapshot, so the
    restart/health counters must be written where it can find them."""
    settings, comp = _spawn(tmp_path, "memory", {})
    store = StateStore(Path(settings.state_dir) / "state.json")
    sup = Supervisor(body=RecordingBody(), max_restarts=3, state_store=store)
    sup.register_process(comp)
    sup.start_all()
    try:
        os.kill(comp.pid, signal.SIGKILL)
        _wait_dead(comp)
        sup.check_once()
    finally:
        sup.stop_all()

    snapshot = store.get("supervisor")
    assert snapshot and snapshot["components"]["memory"]["restarts"] == 1
    # The final state after stop_all is honestly `stopped`.
    assert store.get("supervisor")["components"]["memory"]["state"] == "stopped"


def _fake_state(seq: int):
    from blaxcy.models import ScreenState, WindowInfo

    return ScreenState(
        timestamp=time.time(), width=1366, height=768, sequence=seq,
        frame_hash=f"h{seq}", changed=True, changed_ratio=0.5,
        confidence=1.0, source="fake",
        windows=[WindowInfo(window_id="1", title="gedit", focused=True)],
        active_window_id="1", cursor=(10, 10),
    )


def test_application_service_status_reports_degraded_and_restarts(tmp_path):
    """`service_status()` must expose the supervisor's live counters, and a
    crash-under-run must show up as `degraded` with a new pid."""
    from blaxcy.app import Application
    from blaxcy.eye import FakeEyeBackend

    settings = Settings(root=tmp_path)
    settings.ensure_dirs()
    app = Application(settings=settings, eye_backend=FakeEyeBackend(factory=_fake_state),
                      split=("memory",))
    app.start()
    try:
        first = {s["name"]: s for s in app.service_status()}["memory"]
        assert first["running"] is True
        assert first["restarts"] == 0
        old_pid = app.processes["memory"].pid

        os.kill(old_pid, signal.SIGKILL)

        deadline = time.monotonic() + 20.0
        status = first
        while time.monotonic() < deadline:
            status = {s["name"]: s for s in app.service_status()}["memory"]
            # Wait until the restart is complete and the degraded state is
            # reported (there is a brief window where restarts is incremented
            # before the restarted process has been marked degraded).
            if status.get("restarts", 0) >= 1 and status.get("state") == "degraded":
                break
            time.sleep(0.1)

        assert status["restarts"] >= 1
        assert status["state"] == "degraded"
        assert status["pid"] != old_pid
        assert app.memory.count() >= 0             # service is serving again
    finally:
        app.stop()
    assert not any(p.is_running() for p in app.processes.values())
