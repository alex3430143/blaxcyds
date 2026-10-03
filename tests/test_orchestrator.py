from types import SimpleNamespace

from conftest import FakeBody, StubEye, make_screen_state

from blaxcy.brain import Router, default_registry
from blaxcy.models import (
    Action,
    ActionKind,
    Plan,
    PlanStep,
    RiskClass,
)
from blaxcy.orchestrator import Orchestrator, RulePlanner
from blaxcy.policy import Policy


class ScriptedPlanner:
    def __init__(self, plan: Plan):
        self._plan = plan

    def plan(self, objective):
        return self._plan


def make_orch(body, eye, memory, state_store=None, planner=None, max_risk="high"):
    settings = SimpleNamespace(max_risk=max_risk, real_input_enabled=False)
    policy = Policy(max_risk=RiskClass(max_risk), real_input_enabled=False)
    return Orchestrator(settings=settings, policy=policy, eye=eye, body=body,
                        router=Router(default_registry()), memory=memory,
                        state_store=state_store, planner=planner), policy


def test_observe_goal_is_verified(tmp_memory, tmp_state):
    orch, _ = make_orch(FakeBody(), StubEye(make_screen_state()), tmp_memory, tmp_state)
    result = orch.run("observe the desktop")
    assert result.verified
    assert result.status == "verified"
    assert result.steps_attempted >= 1


def test_type_goal_plans_and_verifies(tmp_memory):
    orch, _ = make_orch(FakeBody(), StubEye(make_screen_state(changed=True)), tmp_memory)
    result = orch.run("type 'hello world'")
    kinds = [a.kind for s in result.plan.steps for a in s.actions]
    assert ActionKind.TYPE_TEXT in kinds
    assert result.verified


def test_unrecognized_goal_escalates_without_false_success(tmp_memory):
    orch, _ = make_orch(FakeBody(), StubEye(make_screen_state()), tmp_memory)
    result = orch.run("make me a sandwich")
    assert not result.verified
    assert result.escalations
    assert result.status == "escalated"


def test_failed_action_is_retried_then_succeeds(tmp_memory):
    plan = Plan(objective_id="o", steps=[PlanStep(
        step_id="s1", description="retry me",
        actions=[Action(kind=ActionKind.NOOP)])])
    body = FakeBody(outcomes=[False, True])
    orch, _ = make_orch(body, StubEye(make_screen_state()), tmp_memory,
                        planner=ScriptedPlanner(plan))
    result = orch.run("anything")
    assert len(body.calls) == 2  # failed once, retried
    assert result.steps_succeeded == 1


def test_emergency_stop_prevents_execution(tmp_memory):
    plan = Plan(objective_id="o", steps=[PlanStep(
        step_id="s1", description="x", actions=[Action(kind=ActionKind.NOOP)])])
    body = FakeBody()
    orch, policy = make_orch(body, StubEye(make_screen_state()), tmp_memory,
                             planner=ScriptedPlanner(plan))
    policy.emergency_stop()
    result = orch.run("anything")
    assert not result.verified
    assert body.calls == []
    assert any("emergency stop" in e for e in result.escalations)


def test_learning_is_recorded_in_memory(tmp_memory):
    orch, _ = make_orch(FakeBody(), StubEye(make_screen_state()), tmp_memory)
    before = tmp_memory.count()
    orch.run("observe the desktop")
    assert tmp_memory.count() > before


def test_evaluate_recommendation(tmp_memory):
    orch, _ = make_orch(FakeBody(), StubEye(make_screen_state()), tmp_memory)
    result = orch.run("observe the desktop")
    evaluation = orch.evaluate(result)
    assert evaluation["verified"] is True
    assert evaluation["recommendation"] == "stop"


def test_run_writes_checkpoint(tmp_memory, tmp_state):
    orch, _ = make_orch(FakeBody(), StubEye(make_screen_state()), tmp_memory, tmp_state)
    orch.run("observe the desktop")
    assert tmp_state.last_checkpoint() is not None


def test_rule_planner_app_launch_requires_verification_step():
    planner = RulePlanner()
    objective = SimpleNamespace(goal="open a text editor", objective_id="o", constraints=[])
    plan = planner.plan(objective)
    kinds = [a.kind for s in plan.steps for a in s.actions]
    assert ActionKind.APP_LAUNCH in kinds
    assert any(s.verify for s in plan.steps)
