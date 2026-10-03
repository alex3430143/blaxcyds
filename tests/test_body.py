import time

from blaxcy.body import Body, DryRunBackend
from blaxcy.body.actions import app_launch, mouse_move, type_text
from blaxcy.body.backends import X11Backend
from blaxcy.models import Action, ActionKind, ActionResult, ActionStatus, RiskClass
from blaxcy.policy import Policy


class SlowBackend:
    name = "slow"

    def perform(self, action):
        time.sleep(2.0)
        return {}

    def release_all(self):
        pass


class FailingBackend:
    name = "failing"

    def __init__(self):
        self.released = 0

    def perform(self, action):
        raise RuntimeError("kaboom")

    def release_all(self):
        self.released += 1


def test_dry_run_input_is_simulated(dry_body: Body):
    result = dry_body.execute(type_text("hello"))
    assert result.status is ActionStatus.DRY_RUN
    assert result.ok
    assert result.observed["simulated"] is True
    assert result.backend == "dry-run"


def test_high_risk_blocked_without_approval(policy: Policy):
    body = Body(DryRunBackend(), policy)
    result = body.execute(app_launch("gedit"))
    assert result.status is ActionStatus.BLOCKED
    assert result.observed["requires_confirmation"]
    assert result.error
    assert body.blocked == 1 and body.executed == 0


def test_approved_high_risk_runs(policy: Policy):
    body = Body(DryRunBackend(), policy)
    action = app_launch("gedit")
    policy.approve(action.action_id)
    result = body.execute(action)
    assert result.ok and result.status is ActionStatus.SUCCEEDED
    assert body.executed == 1


def test_timeout_releases_inputs(policy: Policy):
    backend = FailingBackend()
    body = Body(SlowBackend(), policy)
    action = Action(kind=ActionKind.NOOP, timeout_s=0.05)
    result = body.execute(action)
    assert result.status is ActionStatus.TIMEOUT


def test_backend_failure_reports_and_releases(policy: Policy):
    backend = FailingBackend()
    body = Body(backend, policy)
    result = body.execute(Action(kind=ActionKind.NOOP))
    assert result.status is ActionStatus.FAILED
    assert "kaboom" in result.error
    assert backend.released == 1


def test_postcondition_verifier_marks_verified(policy: Policy):
    body = Body(DryRunBackend(), policy)
    result = body.execute(mouse_move(1, 2), postcondition_verifier=lambda a, r: True)
    assert result.verified
    result2 = body.execute(mouse_move(3, 4), postcondition_verifier=lambda a, r: False)
    assert not result2.verified


def test_x11_mouse_actions_never_use_hanging_sync():
    """Regression: `xdotool mousemove --sync` hangs when the pointer is already
    at the target (it waits for a motion event that never fires), which made
    clicks time out. The X11 backend must move the pointer without `--sync`.
    """
    backend = X11Backend(display="")
    calls: list[tuple] = []

    def fake_xdotool(*args, **kwargs):
        calls.append(args)
        return ""

    backend._xdotool = fake_xdotool

    backend._do_mouse_move(Action(kind=ActionKind.MOUSE_MOVE, params={"x": 5, "y": 6}))
    assert calls[0][:3] == ("mousemove", "5", "6")
    assert "--sync" not in calls[0]

    calls.clear()
    backend._do_click(Action(kind=ActionKind.CLICK, params={"x": 5, "y": 6}))
    assert calls and all("--sync" not in c for c in calls)
    assert calls[0][:3] == ("mousemove", "5", "6")


def test_heartbeat_advances_and_alive(policy: Policy):
    body = Body(DryRunBackend(), policy)
    body.touch()
    assert body.alive(max_age_s=5.0)
    assert body.heartbeat_age() < 1.0
    health = body.health()
    assert health["backend"] == "dry-run"
