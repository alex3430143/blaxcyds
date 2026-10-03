from blaxcy.models import (
    IPC_VERSION,
    Action,
    ActionKind,
    ActionResult,
    ActionStatus,
    IPCMessage,
    Objective,
    Plan,
    PlanStep,
    RiskClass,
    ScreenState,
    WindowInfo,
)


def test_action_round_trip_preserves_kind_and_risk():
    action = Action(kind=ActionKind.CLICK, params={"x": 5, "y": 6}, risk=RiskClass.MEDIUM)
    restored = Action.from_dict(action.to_dict())
    assert restored.kind is ActionKind.CLICK
    assert restored.risk is RiskClass.MEDIUM
    assert restored.params == {"x": 5, "y": 6}
    assert restored.action_id == action.action_id


def test_action_result_ok_property():
    ok = ActionResult(action_id="a", status=ActionStatus.SUCCEEDED)
    dry = ActionResult(action_id="b", status=ActionStatus.DRY_RUN)
    bad = ActionResult(action_id="c", status=ActionStatus.FAILED)
    blocked = ActionResult(action_id="d", status=ActionStatus.BLOCKED)
    assert ok.ok and dry.ok
    assert not bad.ok and not blocked.ok


def test_screen_state_excludes_frame_bytes_from_serialization():
    state = ScreenState(timestamp=1.0, width=10, height=20, frame_bytes=b"secret")
    d = state.to_dict()
    assert "frame_bytes" not in d
    assert "frame_bytes_b64" not in d
    restored = ScreenState.from_dict(d)
    assert restored.frame_bytes is None
    assert restored.width == 10


def test_screen_state_freshness_and_active_window():
    state = ScreenState(timestamp=1000.0, width=1, height=1,
                        windows=[WindowInfo(window_id="w1", title="Terminal")],
                        active_window_id="w1")
    assert state.active_window().title == "Terminal"
    assert state.is_fresh(10.0, now=1005.0)
    assert not state.is_fresh(1.0, now=1005.0)


def test_ipc_message_json_round_trip_and_version():
    msg = IPCMessage(type="ping", payload={"a": 1}, token="t")
    restored = IPCMessage.from_json(msg.to_json())
    assert restored.type == "ping"
    assert restored.payload == {"a": 1}
    assert restored.version == IPC_VERSION


def test_objective_and_plan_round_trip():
    obj = Objective(goal="do x", success_criteria=["c1"], max_risk=RiskClass.HIGH)
    restored = Objective.from_dict(obj.to_dict())
    assert restored.max_risk is RiskClass.HIGH

    plan = Plan(objective_id=obj.objective_id,
                steps=[PlanStep(step_id="s1", description="d",
                                actions=[Action(kind=ActionKind.NOOP)])])
    rp = Plan.from_dict(plan.to_dict())
    assert rp.steps[0].actions[0].kind is ActionKind.NOOP
