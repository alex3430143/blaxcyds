"""Tests for validated planning — the model-text → Plan safety boundary.

A model (local or remote) may only ever return text. These tests prove that
malformed, over-broad, or malicious model output is rejected wholesale and can
never become a Body action, and that risk is assigned by BLAXCY, not the model.
"""

from __future__ import annotations

import json

import pytest

from blaxcy.brain.router import Completion, FailureKind
from blaxcy.models import ActionKind, Objective, RiskClass
from blaxcy.planning import (
    ModelPlanner,
    PlanValidationError,
    extract_json,
    validate_action_dict,
    validate_model_plan,
)


def make_objective(goal: str = "open a text editor") -> Objective:
    return Objective(goal=goal, success_criteria=["window exists"])


# --------------------------------------------------------------------------- #
# action validation
# --------------------------------------------------------------------------- #
def test_valid_action_is_accepted_and_risk_is_assigned_by_blaxcy():
    action = validate_action_dict({"kind": "app_launch", "params": {"command": "gedit"},
                                   "risk": "safe"})
    assert action.kind is ActionKind.APP_LAUNCH
    # The model said "safe"; BLAXCY overrides it.
    assert action.risk is RiskClass.HIGH


@pytest.mark.parametrize("kind", ["terminal_run", "fs_write", "browser_eval", "not_a_kind"])
def test_dangerous_or_unknown_action_kinds_are_rejected(kind):
    with pytest.raises(PlanValidationError):
        validate_action_dict({"kind": kind, "params": {}})


def test_unknown_param_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_action_dict({"kind": "type_text", "params": {"text": "hi", "shell": "rm -rf /"}})


def test_unknown_verify_key_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_action_dict({"kind": "noop", "params": {},
                              "expected_postcondition": {"delete_everything": True}})


def test_long_strings_are_rejected():
    with pytest.raises(PlanValidationError):
        validate_action_dict({"kind": "type_text", "params": {"text": "x" * 5000}})


# --------------------------------------------------------------------------- #
# plan validation
# --------------------------------------------------------------------------- #
def test_valid_plan_parses_into_typed_steps_and_actions():
    payload = {
        "steps": [
            {"description": "launch gedit",
             "actions": [{"kind": "app_launch", "params": {"command": "gedit"},
                          "target": "gedit"}],
             "verify": {"window_exists": "gedit"}},
            {"description": "type",
             "actions": [{"kind": "type_text", "params": {"text": "hello"}}]},
        ]
    }
    plan = validate_model_plan(make_objective(), payload)
    assert len(plan.steps) == 2
    assert plan.steps[0].actions[0].kind is ActionKind.APP_LAUNCH
    assert plan.steps[0].actions[0].risk is RiskClass.HIGH
    assert plan.steps[0].verify == {"window_exists": "gedit"}


def test_plan_with_no_steps_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_model_plan(make_objective(), {"steps": []})


def test_oversized_plan_is_rejected():
    step = {"description": "x", "actions": [{"kind": "noop", "params": {}}]}
    with pytest.raises(PlanValidationError):
        validate_model_plan(make_objective(), {"steps": [step] * 100})


def test_non_object_payload_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_model_plan(make_objective(), "not a plan")


def test_extract_json_finds_embedded_object():
    assert extract_json('sure: {"a": 1} thanks') == {"a": 1}
    assert extract_json("no json here") is None


# --------------------------------------------------------------------------- #
# ModelPlanner falls back rather than trusting bad output
# --------------------------------------------------------------------------- #
class FakeRouter:
    def __init__(self, completion: Completion):
        self.completion = completion
        self.prompts: list[str] = []

    def complete(self, prompt, need=None, **kwargs):
        self.prompts.append(prompt)
        return self.completion


def _completion(text: str, *, ok: bool = True) -> Completion:
    return Completion(ok=ok, text=text, model="offline-deterministic")


def test_model_planner_accepts_a_validated_plan():
    payload = {"steps": [{"description": "launch", "actions": [
        {"kind": "app_launch", "params": {"command": "gedit"}}]}]}
    planner = ModelPlanner(FakeRouter(_completion(json.dumps(payload))))
    plan = planner.plan(make_objective())
    assert plan.steps[0].actions[0].kind is ActionKind.APP_LAUNCH
    assert planner.rejections == 0


def test_model_planner_rejects_malicious_plan_and_falls_back():
    malicious = {"steps": [{"description": "wipe",
                            "actions": [{"kind": "terminal_run",
                                         "params": {"command": "rm -rf /"}}]}]}
    planner = ModelPlanner(FakeRouter(_completion(json.dumps(malicious))))
    objective = make_objective()
    plan = planner.plan(objective)
    # Falls back to the deterministic planner: an observe step, never terminal_run.
    kinds = [a.kind for step in plan.steps for a in step.actions]
    assert ActionKind.TERMINAL_RUN not in kinds
    assert planner.rejections == 1
    assert any("rejected" in c for c in objective.constraints)


def test_model_planner_rejects_unparseable_output():
    planner = ModelPlanner(FakeRouter(_completion("I cannot help with that")))
    plan = planner.plan(make_objective())
    assert planner.rejections == 1
    assert plan.steps  # deterministic fallback still produced a plan


def test_model_planner_falls_back_when_router_fails():
    planner = ModelPlanner(FakeRouter(Completion(ok=False, error_kind=FailureKind.TIMEOUT,
                                                  error="timed out")))
    objective = make_objective()
    plan = planner.plan(objective)
    assert planner.fallbacks == 1
    assert plan.steps
    assert any("unavailable" in c for c in objective.constraints)
