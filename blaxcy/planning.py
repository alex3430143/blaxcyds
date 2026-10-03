"""Validated planning — the only bridge from model text to Body actions.

A model (local or remote) can only ever return *text*. That text is never turned
into behaviour directly: it must be parsed into a `Plan` by
`validate_model_plan`, which enforces a conservative whitelist:

* only known `ActionKind`s are allowed (unknown kinds are rejected, never
  `getattr`-ed);
* each kind may carry only its declared, closed set of parameters;
* parameter values must be JSON primitives of the right shape;
* the model may **not** choose a risk class — BLAXCY assigns a conservative risk
  per kind, so a model cannot label a launch as "safe";
* verify keys are restricted to a small known set;
* size is bounded (steps, actions per step, string lengths).

Anything that fails is rejected wholesale and the deterministic `RulePlanner`
takes over. Rejected model output therefore can never authorize a Body action,
and every accepted action still passes Policy like any in-process action.
"""

from __future__ import annotations

import json
from typing import Any

from .brain.router import Need
from .models import Action, ActionKind, Plan, PlanStep, RiskClass

MAX_MODEL_STEPS = 25
MAX_ACTIONS_PER_STEP = 8
MAX_TEXT_LEN = 4_000
MAX_TARGET_LEN = 512

# The closed set of action kinds a model may propose, with their allowed params.
_MODEL_ACTION_PARAMS: dict[ActionKind, set[str]] = {
    ActionKind.APP_LAUNCH: {"command"},
    ActionKind.TYPE_TEXT: {"text"},
    ActionKind.KEY_PRESS: {"key"},
    ActionKind.HOTKEY: {"keys"},
    ActionKind.CLIPBOARD_SET: {"text"},
    ActionKind.CLIPBOARD_GET: set(),
    ActionKind.MOUSE_MOVE: {"x", "y"},
    ActionKind.CLICK: {"x", "y", "button"},
    ActionKind.DOUBLE_CLICK: {"x", "y", "button"},
    ActionKind.RIGHT_CLICK: {"x", "y", "button"},
    ActionKind.SCROLL: {"amount"},
    ActionKind.WINDOW_SWITCH: {"window_id"},
    ActionKind.WAIT_FOR: {"seconds"},
    ActionKind.NOOP: {"observe"},
}

# BLAXCY assigns the risk; the model never gets to declare itself safe.
_MODEL_ACTION_RISK: dict[ActionKind, RiskClass] = {
    ActionKind.APP_LAUNCH: RiskClass.HIGH,
    ActionKind.CLIPBOARD_SET: RiskClass.LOW,
    ActionKind.CLIPBOARD_GET: RiskClass.LOW,
    ActionKind.NOOP: RiskClass.SAFE,
    ActionKind.WAIT_FOR: RiskClass.SAFE,
}
_DEFAULT_MODEL_RISK = RiskClass.MEDIUM

_ALLOWED_VERIFY_KEYS = {"screen_changed", "window_exists", "text_visible",
                        "file_exists", "value_equals"}


class PlanValidationError(ValueError):
    """A model-produced plan was malformed, over-broad, or out of bounds."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanValidationError(message)


def _validate_params(kind: ActionKind, params: Any) -> dict[str, Any]:
    _require(isinstance(params, dict), "action params must be an object")
    allowed = _MODEL_ACTION_PARAMS[kind]
    for key, value in params.items():
        _require(isinstance(key, str), "param keys must be strings")
        _require(key in allowed,
                 f"param {key!r} is not allowed for {kind.value}")
        _require(isinstance(value, (str, int, float, bool, type(None))),
                 f"param {key!r} must be a JSON primitive")
        if isinstance(value, str):
            _require(len(value) <= MAX_TEXT_LEN, f"param {key!r} is too long")
    return dict(params)


def _validate_verify(verify: Any) -> dict[str, Any] | None:
    if verify is None:
        return None
    _require(isinstance(verify, dict), "verify must be an object")
    for key, value in verify.items():
        _require(key in _ALLOWED_VERIFY_KEYS, f"verify key {key!r} is not allowed")
        _require(isinstance(value, (str, int, float, bool)),
                 f"verify value for {key!r} must be a primitive")
        if isinstance(value, str):
            _require(len(value) <= MAX_TEXT_LEN, f"verify value for {key!r} is too long")
    return dict(verify)


def validate_action_dict(raw: Any) -> Action:
    """Turn one model-proposed action object into a typed, risk-assigned Action."""
    _require(isinstance(raw, dict), "action must be an object")
    kind_raw = raw.get("kind")
    _require(isinstance(kind_raw, str), "action kind must be a string")
    try:
        kind = ActionKind(kind_raw)
    except ValueError as exc:
        raise PlanValidationError(f"unknown action kind {kind_raw!r}") from exc
    _require(kind in _MODEL_ACTION_PARAMS,
             f"action kind {kind_raw!r} is not permitted in a model plan")

    params = _validate_params(kind, raw.get("params", {}))
    target = raw.get("target")
    if target is not None:
        _require(isinstance(target, str), "target must be a string")
        _require(len(target) <= MAX_TARGET_LEN, "target is too long")
    timeout = raw.get("timeout_s", 10.0)
    _require(isinstance(timeout, (int, float)) and not isinstance(timeout, bool),
             "timeout_s must be a number")
    timeout = max(0.1, min(float(timeout), 60.0))

    return Action(
        kind=kind,
        params=params,
        target=target,
        expected_postcondition=_validate_verify(raw.get("expected_postcondition")),
        timeout_s=timeout,
        risk=_MODEL_ACTION_RISK.get(kind, _DEFAULT_MODEL_RISK),
    )


def validate_model_plan(objective: Any, payload: Any) -> Plan:
    """Parse a model's JSON plan into a typed Plan, or raise.

    The model's own `risk`, unknown kinds, unknown params, oversized plans and
    malformed JSON are all rejected. On success every action is a real `Action`
    with a BLAXCY-assigned risk class, still subject to Policy.
    """
    _require(isinstance(payload, dict), "plan must be a JSON object")
    steps_raw = payload.get("steps")
    _require(isinstance(steps_raw, list) and steps_raw, "plan must have a non-empty steps list")
    _require(len(steps_raw) <= MAX_MODEL_STEPS,
             f"plan has too many steps ({len(steps_raw)} > {MAX_MODEL_STEPS})")

    steps: list[PlanStep] = []
    for index, step_raw in enumerate(steps_raw, start=1):
        _require(isinstance(step_raw, dict), f"step {index} must be an object")
        description = step_raw.get("description", "")
        _require(isinstance(description, str), f"step {index} description must be a string")
        actions_raw = step_raw.get("actions")
        _require(isinstance(actions_raw, list) and actions_raw,
                 f"step {index} must have a non-empty actions list")
        _require(len(actions_raw) <= MAX_ACTIONS_PER_STEP,
                 f"step {index} has too many actions")
        actions = [validate_action_dict(a) for a in actions_raw]
        steps.append(PlanStep(
            step_id=str(step_raw.get("step_id") or f"s{index}")[:64],
            description=description[:MAX_TEXT_LEN],
            actions=actions,
            verify=_validate_verify(step_raw.get("verify")),
            optional=bool(step_raw.get("optional", False)),
        ))
    return Plan(objective_id=getattr(objective, "objective_id", ""), steps=steps)


def extract_json(text: str) -> Any:
    """Return the first JSON object/array embedded in `text`, or None."""
    if not text:
        return None
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    return None


_PLAN_PROMPT = """\
You are BLAXCY's planner. Return ONLY a JSON object of the form
{{"steps": [{{"description": "...", "actions": [{{"kind": "...", "params": {{...}}, \
"target": "...", "expected_postcondition": {{...}}}}], "verify": {{...}} }}]}}.
Allowed action kinds and their params: {schema}.
Do not include any other text.
GOAL: {goal}
SUCCESS CRITERIA: {criteria}
"""


class ModelPlanner:
    """A model-backed planner whose output is validated before use.

    On any model failure or rejected plan it falls back to the deterministic
    planner — never to unvalidated model output.
    """

    def __init__(self, router: Any, fallback: Any = None,
                 need: Need | None = None) -> None:
        self.router = router
        self.need = need or Need(capability="planning")
        if fallback is None:
            from .orchestrator import RulePlanner

            fallback = RulePlanner(router)
        self.fallback = fallback
        self.rejections = 0
        self.fallbacks = 0

    def _prompt(self, objective: Any) -> str:
        schema = {kind.value: sorted(params) for kind, params in _MODEL_ACTION_PARAMS.items()}
        return _PLAN_PROMPT.format(schema=json.dumps(schema, sort_keys=True),
                                   goal=getattr(objective, "goal", ""),
                                   criteria="; ".join(getattr(objective, "success_criteria", [])))

    def plan(self, objective: Any) -> Plan:
        completion = self.router.complete(self._prompt(objective), self.need)
        if not completion.ok:
            self.fallbacks += 1
            objective.constraints.append("model planner unavailable; used deterministic planner")
            return self.fallback.plan(objective)
        try:
            plan = validate_model_plan(objective, extract_json(completion.text))
        except PlanValidationError as exc:
            self.rejections += 1
            self.fallbacks += 1
            objective.constraints.append(f"model plan rejected ({exc}); used deterministic planner")
            return self.fallback.plan(objective)
        return plan
