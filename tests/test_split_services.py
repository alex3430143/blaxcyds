"""Real-subprocess tests for the split service architecture (M5).

Every test here spawns a genuine child process via `blaxcy serve <name>` with an
isolated `BLAXCY_ROOT`, then exercises the authentic IPC path: authenticated
ping, a real API call, crash → detection → restart with a new pid, and the
parent watchdog. Nothing is mocked at the process boundary.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

import pytest

from blaxcy.brain.router import Need
from blaxcy.brain.service import RemoteBrain
from blaxcy.config import Settings, project_root
from blaxcy.memory import RemoteMemory
from blaxcy.service import (
    ProcessComponent,
    ServiceError,
    service_command,
    service_socket,
)
from blaxcy.supervisor import Supervisor

STARTUP_TIMEOUT = 40.0


def _settings(tmp_path: Path) -> Settings:
    settings = Settings(root=tmp_path)
    settings.ensure_dirs()
    return settings


def _spawn(tmp_path: Path, name: str, *, extra_env: dict[str, str] | None = None,
           startup_timeout: float = STARTUP_TIMEOUT) -> tuple[Settings, ProcessComponent]:
    settings = _settings(tmp_path)
    env = {"BLAXCY_ROOT": str(tmp_path), "PYTHONPATH": str(project_root())}
    env.update(extra_env or {})
    comp = ProcessComponent(
        name, service_command(name),
        socket_path=service_socket(settings, name),
        secret=settings.ipc_secret(),
        env=env, cwd=str(project_root()),
        startup_timeout=startup_timeout,
    )
    return settings, comp


def _wait_exit(proc, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    return proc.poll() is not None


class _RecordingBody:
    def __init__(self) -> None:
        self.releases = 0

    def panic_release(self) -> None:
        self.releases += 1


# --------------------------------------------------------------------------- #
# Memory service
# --------------------------------------------------------------------------- #
def test_memory_service_round_trip_over_ipc(tmp_path):
    settings, comp = _spawn(tmp_path, "memory")
    comp.start()
    try:
        health = comp.health()
        assert health["alive"] is True and health["ok"] is True
        assert health["pid"] > 0

        remote = RemoteMemory(settings)
        record = remote.add("opened gedit", kind="lesson", tags=["editor"])
        assert record.content == "opened gedit"
        assert remote.count() == 1
        rows = remote.query(text="gedit")
        assert len(rows) == 1 and rows[0].record_id == record.record_id
        assert remote.get(record.record_id).content == "opened gedit"
        assert remote.forget(record.record_id) is True
        assert remote.count() == 0
        assert remote.health()["remote"] is True
    finally:
        comp.stop()
    assert not comp.is_running()
    assert not comp.socket_path.exists()


def test_memory_service_survives_concurrent_callers(tmp_path):
    """Regression: the service host is thread-per-connection, so several callers
    hit the one SQLite connection at once. That used to fail with
    `bad parameter or other API misuse` and silently drop writes."""
    settings, comp = _spawn(tmp_path, "memory")
    comp.start()
    try:
        remote = RemoteMemory(settings)
        errors: list[str] = []

        def worker(index: int) -> None:
            try:
                for j in range(25):
                    remote.add(f"c{index}-{j}", kind="lesson")
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert remote.count() == 200   # every write landed, none lost
    finally:
        comp.stop()


def test_missing_memory_service_raises_instead_of_returning_empty(tmp_path):
    """A down service must never look like legitimate empty memory."""
    remote = RemoteMemory(_settings(tmp_path))
    with pytest.raises(ServiceError):
        remote.count()
    assert remote.degraded_calls == 1


def test_supervisor_restarts_a_crashed_memory_service(tmp_path):
    settings, comp = _spawn(tmp_path, "memory")
    body = _RecordingBody()
    sup = Supervisor(body=body, max_restarts=3)
    sup.register_process(comp)
    sup.start_all()
    try:
        remote = RemoteMemory(settings)
        remote.add("before crash", kind="lesson")
        first_pid = comp.pid
        os.kill(first_pid, signal.SIGKILL)
        time.sleep(0.4)

        events = sup.check_once()
        assert any(e["event"] == "heartbeat_lost" for e in events)
        assert any(e["event"] == "restarted" for e in events)
        assert body.releases >= 1               # safe input release before restart
        assert comp.is_running()
        assert comp.pid != first_pid            # new pid
        assert remote.count() == 1              # data survived on disk
        assert remote.health()["pid"] == comp.pid
    finally:
        sup.stop_all()
    assert not comp.is_running()
    assert not comp.socket_path.exists()


def test_memory_service_exits_when_its_supervisor_vanishes(tmp_path):
    settings = _settings(tmp_path)
    _, comp = _spawn(tmp_path, "memory",
                     extra_env={"BLAXCY_SUPERVISOR_PID": "999999",
                                "BLAXCY_PARENT_CHECK_S": "0.2"})
    comp.start()
    try:
        assert _wait_exit(comp._proc), "memory service outlived its vanished supervisor"
    finally:
        comp.stop()


# --------------------------------------------------------------------------- #
# Brain service
# --------------------------------------------------------------------------- #
def test_brain_service_round_trip_over_ipc(tmp_path):
    settings, comp = _spawn(tmp_path, "brain")
    comp.start()
    try:
        health = comp.health()
        assert health["alive"] is True and health["ok"] is True

        brain = RemoteBrain(settings)
        rows = brain.status()
        assert any(r["name"] == "offline-deterministic" and r["available"] for r in rows)

        need = Need(capability="reasoning", prefer="offline-deterministic")
        completion = brain.complete("say hi", need)
        assert completion.ok is True
        assert completion.model == "offline-deterministic"
        assert completion.text

        candidates = brain.candidates(need)
        assert candidates and candidates[0].name == "offline-deterministic"
    finally:
        comp.stop()
    assert not comp.is_running()


def test_supervisor_restarts_a_crashed_brain_service(tmp_path):
    settings, comp = _spawn(tmp_path, "brain")
    sup = Supervisor(body=_RecordingBody(), max_restarts=3)
    sup.register_process(comp)
    sup.start_all()
    try:
        first_pid = comp.pid
        os.kill(first_pid, signal.SIGKILL)
        time.sleep(0.4)
        events = sup.check_once()
        assert any(e["event"] == "heartbeat_lost" for e in events)
        assert comp.is_running() and comp.pid != first_pid
        assert RemoteBrain(settings).status()      # healthy again
    finally:
        sup.stop_all()
    assert not comp.is_running()


def test_brain_service_exits_when_its_supervisor_vanishes(tmp_path):
    settings = _settings(tmp_path)
    _, comp = _spawn(tmp_path, "brain",
                     extra_env={"BLAXCY_SUPERVISOR_PID": "999999",
                                "BLAXCY_PARENT_CHECK_S": "0.2"})
    comp.start()
    try:
        assert _wait_exit(comp._proc), "brain service outlived its vanished supervisor"
    finally:
        comp.stop()


# --------------------------------------------------------------------------- #
# State consistency across the process boundary
# --------------------------------------------------------------------------- #
def test_screen_state_survives_the_wire_with_freshness_and_provenance():
    """The Eye's ScreenState must keep timestamp/source/confidence/sequence and
    window identity when serialized for IPC, so a remote frame is never mistaken
    for current perception by accident."""
    from blaxcy.eye.screen_state import ScreenState

    now = time.time()
    original = ScreenState(
        timestamp=now, width=1366, height=768, sequence=7,
        frame_hash="abc123", changed=True, changed_ratio=0.25,
        source="x11:import", confidence=0.9,
        active_window_id="w1", cursor=(5, 6),
        windows=[],
    )
    restored = ScreenState.from_dict(original.to_dict(include_frame=False))
    assert restored.timestamp == now
    assert restored.sequence == 7
    assert restored.source == "x11:import"
    assert restored.confidence == 0.9
    assert restored.active_window_id == "w1"
    assert restored.cursor == (5, 6)
    # Freshness is computed from the original timestamp, not the receive time.
    assert restored.age(now=now) == 0.0
    assert restored.is_fresh(1.0, now=now) is True


# --------------------------------------------------------------------------- #
# End-to-end split mode: the application runs with memory + brain remote
# --------------------------------------------------------------------------- #
def _fake_state(seq: int):
    from blaxcy.models import ScreenState, WindowInfo

    return ScreenState(
        timestamp=time.time(), width=1366, height=768, sequence=seq,
        frame_hash=f"hash-{seq}", changed=True, changed_ratio=0.5,
        confidence=1.0, source="fake",
        windows=[WindowInfo(window_id="1", title="gedit", focused=True)],
        active_window_id="1", cursor=(10, 10),
    )


def test_application_normalizes_split_aliases_without_starting(tmp_path):
    """Regression: `--split all` (and programmatic tuples/unknown names) must be
    normalized centrally, or it silently runs everything in-process."""
    from blaxcy.app import Application

    settings = _settings(tmp_path)
    app = Application(settings=settings, split="all")
    assert set(app.split) == {"eye", "memory", "brain"}
    assert set(app.processes) == {"eye", "memory", "brain"}
    app.stop()  # nothing started; stopping must be safe

    partial = Application(settings=settings, split=("bogus", "memory"))
    assert partial.split == ("memory",)
    assert set(partial.processes) == {"memory"}
    partial.stop()


def test_application_runs_with_memory_and_brain_split(tmp_path):
    from blaxcy.app import Application
    from blaxcy.eye import FakeEyeBackend

    settings = _settings(tmp_path)
    app = Application(settings=settings, eye_backend=FakeEyeBackend(factory=_fake_state),
                      split=("memory", "brain"))
    app.start()
    try:
        assert isinstance(app.memory, RemoteMemory)
        assert isinstance(app.router, RemoteBrain)
        app.eye.snapshot(wait=True, timeout=2.0)

        result = app.orchestrator.run("observe the desktop")
        assert result.verified is True
        assert app.orchestrator.memory_degraded == 0

        # Learning was persisted by the Memory service, not locally.
        assert app.memory.count() >= 1
        assert app.memory.query(kind="lesson")

        # The Brain service is genuinely answering.
        assert any(r["name"] == "offline-deterministic" for r in app.router.status())

        statuses = {s["name"]: s for s in app.service_status()}
        assert statuses["memory"]["running"] and statuses["brain"]["running"]
        assert statuses["memory"]["pid"] == app.processes["memory"].pid
    finally:
        app.stop()
    assert all(not proc.is_running() for proc in app.processes.values())
