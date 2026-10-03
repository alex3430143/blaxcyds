"""Shared test fixtures.

Every fixture here is designed so tests NEVER touch the real mouse, keyboard, or
display: perception uses a fake backend and control uses a dry-run backend.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from blaxcy.body import Body, DryRunBackend
from blaxcy.eye import Eye, FakeEyeBackend
from blaxcy.models import (
    ActionResult,
    ActionStatus,
    RiskClass,
    ScreenState,
    WindowInfo,
)
from blaxcy.policy import Policy


# --------------------------------------------------------------------------- #
# fakes
# --------------------------------------------------------------------------- #
class FakeBody:
    """Minimal Body stand-in for orchestrator tests. Records calls."""

    def __init__(self, outcomes: list[bool] | None = None, default_ok: bool = True):
        self.outcomes = list(outcomes or [])
        self.default_ok = default_ok
        self.calls: list = []
        self.released = 0

    def execute(self, action, postcondition_verifier=None):
        self.calls.append(action)
        ok = self.outcomes.pop(0) if self.outcomes else self.default_ok
        return ActionResult(
            action_id=action.action_id,
            status=ActionStatus.SUCCEEDED if ok else ActionStatus.FAILED,
            correlation_id=action.correlation_id,
            started_at=time.time(), finished_at=time.time(),
            backend="fake-body", error=None if ok else "boom",
        )

    def panic_release(self):
        self.released += 1


class StubEye:
    """Eye stand-in exposing current()/snapshot() over a fixed state."""

    def __init__(self, state: ScreenState | None):
        self.state = state

    def current(self):
        return self.state

    def snapshot(self, *args, **kwargs):
        return self.state


def make_screen_state(seq: int = 0, *, changed: bool = True, title: str = "gedit",
                      hash_: str | None = None, confidence: float = 1.0) -> ScreenState:
    return ScreenState(
        timestamp=time.time(), width=1366, height=768, sequence=seq,
        frame_hash=hash_ if hash_ is not None else f"hash-{seq}",
        changed=changed, changed_ratio=0.5 if changed else 0.0,
        confidence=confidence, source="fake",
        windows=[WindowInfo(window_id="1", title=title, focused=True)],
        active_window_id="1", cursor=(10, 10),
    )


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def policy() -> Policy:
    return Policy(max_risk=RiskClass.MEDIUM, real_input_enabled=False)


@pytest.fixture
def dry_body(policy: Policy) -> Body:
    return Body(DryRunBackend(), policy)


@pytest.fixture
def fake_eye():
    """A started Eye backed by a scripted fake backend, producing fresh frames."""
    counter = {"n": 0}

    def factory(seq: int) -> ScreenState:
        counter["n"] += 1
        return make_screen_state(seq, changed=(counter["n"] % 2 == 1), title="gedit")

    eye = Eye(FakeEyeBackend(factory=factory), interval_s=0.005)
    eye.start()
    eye.snapshot(timeout=1.0)
    yield eye
    eye.stop()


@pytest.fixture
def tmp_memory(tmp_path: Path):
    from blaxcy.memory import Memory

    mem = Memory(tmp_path / "memory.sqlite3")
    yield mem
    mem.close()


@pytest.fixture
def tmp_state(tmp_path: Path):
    from blaxcy.state_store import StateStore

    return StateStore(tmp_path / "state.json")
