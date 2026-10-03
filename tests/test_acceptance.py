"""Tests for the B7 live-acceptance harness.

These tests never touch the real mouse/keyboard: the target, the Body and the Eye
are all fakes, so the orchestration, the authorization gate, the independent
verification and the reversibility guarantees are tested without real input.
"""

from __future__ import annotations

import time

from blaxcy.acceptance import XtermTarget, run_live_acceptance
from blaxcy.models import (
    ActionResult,
    ActionKind,
    ActionStatus,
    ScreenState,
    WindowInfo,
)
from blaxcy.policy import Policy


class FakeTarget:
    def __init__(self, *, window=True, title="BLAXCY_ACCEPT", geometry=(100, 100, 200, 100)):
        self.opened = False
        self.closed = False
        self._window = window
        self.title = title
        self._geometry = geometry
        self._content = ""

    def open(self):
        self.opened = True
        return {"file": "/tmp/fake-accept.txt", "pid": 4242}

    def wait_window(self, timeout=8.0):
        return "12345" if self._window else None

    def geometry(self):
        return self._geometry

    def read(self):
        return self._content

    def close(self):
        self.closed = True


class RecordingBody:
    """Fake Body: records actions and mirrors typed text into the target."""

    def __init__(self, target: FakeTarget):
        self.target = target
        self.actions = []

    def execute(self, action, postcondition_verifier=None):
        self.actions.append(action)
        if action.kind is ActionKind.TYPE_TEXT:
            self.target._content += action.params["text"]
        return ActionResult(action_id=action.action_id, status=ActionStatus.SUCCEEDED,
                            backend="recording", detail="recorded")

    def panic_release(self):
        pass


class StubEye:
    def __init__(self, cursor, title):
        self._state = ScreenState(
            timestamp=time.time(), width=400, height=300, cursor=cursor,
            windows=[WindowInfo(window_id="1", title=title, focused=True)],
            active_window_id="1")

    def current(self):
        return self._state


def _run(policy, body, eye, tmp_path, *, cursor=(10, 10)):
    restored = {}
    result = run_live_acceptance(
        policy=policy, body=body, eye=eye, target=body.target,
        evidence_path=tmp_path / "B7_EVIDENCE.md",
        get_cursor=lambda: cursor,
        set_cursor=lambda x, y: restored.update(pos=(x, y)))
    return result, restored


def test_refuses_without_real_input_authorization(tmp_path):
    target = FakeTarget()
    result, _ = _run(Policy(real_input_enabled=False), RecordingBody(target),
                     StubEye((0, 0), "x"), tmp_path)
    assert result.ok is False and result.verified is False
    assert result.evidence.get("refused") is True
    assert target.opened is False
    # A refusal must never overwrite the real evidence artifact; it is recorded
    # beside it instead.
    assert not (tmp_path / "B7_EVIDENCE.md").exists()
    refused = (tmp_path / "B7_EVIDENCE.refused.md").read_text()
    assert "refused" in refused
    assert "authorized: no (refused)" in refused


def test_refusal_does_not_overwrite_existing_evidence(tmp_path):
    """An unauthorized run must leave a prior verified artifact untouched."""
    real = tmp_path / "B7_EVIDENCE.md"
    real.write_text("# BLAXCY — B7 Live Acceptance Evidence\n- **verified: True**\n",
                    encoding="utf-8")
    _run(Policy(real_input_enabled=False), RecordingBody(FakeTarget()),
         StubEye((0, 0), "x"), tmp_path)
    assert "verified: True" in real.read_text()
    assert (tmp_path / "B7_EVIDENCE.refused.md").exists()


def test_verified_run_when_everything_works(tmp_path):
    target = FakeTarget()
    body = RecordingBody(target)
    # geometry (100,100,200,100) -> center (200,150)
    result, restored = _run(Policy(real_input_enabled=True), body,
                            StubEye((200, 150), "BLAXCY_ACCEPT"), tmp_path)
    assert result.ok and result.verified
    assert all(s["ok"] for s in result.steps)
    kinds = [a.kind for a in body.actions]
    assert ActionKind.MOUSE_MOVE in kinds
    assert ActionKind.CLICK in kinds
    assert ActionKind.TYPE_TEXT in kinds
    assert ActionKind.HOTKEY in kinds
    assert target.closed is True
    assert restored["pos"] == (10, 10)
    evidence = (tmp_path / "B7_EVIDENCE.md").read_text()
    assert "verified: True" in evidence


def test_unfocused_window_fails_verification_but_cleans_up(tmp_path):
    target = FakeTarget()
    result, restored = _run(Policy(real_input_enabled=True), RecordingBody(target),
                            StubEye((200, 150), "some other window"), tmp_path)
    assert result.ok is True
    assert result.verified is False
    assert target.closed is True
    assert restored["pos"] == (10, 10)


def test_missing_window_aborts_and_restores_cursor(tmp_path):
    target = FakeTarget(window=False)
    result, restored = _run(Policy(real_input_enabled=True), RecordingBody(target),
                            StubEye((0, 0), "x"), tmp_path)
    assert result.ok is False
    assert target.closed is True
    assert restored["pos"] == (10, 10)


def test_xterm_target_is_inert_until_opened():
    target = XtermTarget()
    assert target.read() == ""
    assert target.geometry() is None
    target.close()  # must not raise


def test_cli_accept_live_refuses_without_authorization(capsys, monkeypatch, tmp_path):
    from blaxcy.cli import main

    # Isolate BLAXCY_ROOT: a CLI acceptance test must never write into the
    # project's real .build-state and clobber collected evidence.
    monkeypatch.setenv("BLAXCY_ROOT", str(tmp_path))
    monkeypatch.delenv("BLAXCY_ENABLE_REAL_INPUT", raising=False)
    code = main(["accept-live", "--json"])
    assert code == 2  # refused, not verified, not an error
    build_state = tmp_path / ".build-state"
    assert (build_state / "B7_EVIDENCE.refused.md").exists()
    assert not (build_state / "B7_EVIDENCE.md").exists()
