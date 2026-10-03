"""The Orchestrator — BLAXCY's autonomy loop.

Takes a high-level goal, turns it into an internal Objective (constraints,
success criteria, budget, stopping conditions), plans, executes each step
through the Body, verifies observed postconditions, recovers from failure, and
records lessons in memory. Success means the criteria were observed and
verified — not that an action was merely sent.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .eye import Eye
from .memory import Memory
from .models import (
    Action,
    ActionKind,
    Objective,
    ObjectiveStatus,
    Plan,
    PlanStep,
    RiskClass,
    ScreenState,
    VerificationResult,
)
from .policy import Policy, max_risk_from_str
from .recovery import FailureClass, RecoveryManager, Strategy, classify_result
from .state_store import StateStore
from .verifier import Verifier

# Small, honest app-name map for planning. Unknown apps are passed through.
APP_ALIASES = {
    "text editor": "gedit", "editor": "gedit", "file manager": "thunar",
    "files": "thunar", "terminal": "xterm", "browser": "firefox",
    "web browser": "firefox", "calculator": "galculator",
}


def action_signature(action: Action) -> str:
    keys = ",".join(sorted(action.params.keys()))
    return f"{action.kind.value}[{keys}]->{action.target or ''}"


def _quoted(text: str) -> str | None:
    m = re.search(r"['\"](.+?)['\"]", text)
    return m.group(1) if m else None


class RulePlanner:
    """A deterministic, rules-based planner.

    It understands a small set of explicit intents and otherwise produces an
    observation step and flags the objective for user clarification rather than
    pretending to understand. A model-backed planner can be injected later.
    """

    def __init__(self, router: Any = None) -> None:
        self.router = router

    def plan(self, objective: Objective) -> Plan:
        g = objective.goal.strip()
        low = g.lower()
        steps: list[PlanStep] = []
        sid = 0

        def step(desc: str, actions: list[Action], verify: dict[str, Any] | None = None) -> None:
            nonlocal sid
            sid += 1
            steps.append(PlanStep(step_id=f"s{sid}", description=desc, actions=actions, verify=verify))

        # 1) type text, optionally after launching an app
        if "type" in low and _quoted(g):
            typed = _quoted(g) or ""
            app = self._app_mentioned(low)
            if app:
                step(f"launch {app}", [self._app_action(app)])
                step(f"wait for {app} window", [self._observe_action()],
                     verify={"window_exists": app})
            step(f"type {typed!r}", [Action(kind=ActionKind.TYPE_TEXT, params={"text": typed})],
                 verify={"screen_changed": True})
            return Plan(objective_id=objective.objective_id, steps=steps)

        # 2) open an application
        if low.startswith("open") or " launch " in f" {low} ":
            app = self._app_mentioned(low)
            if app:
                step(f"launch {app}", [self._app_action(app)])
                step(f"verify {app} window", [self._observe_action()],
                     verify={"window_exists": app})
                return Plan(objective_id=objective.objective_id, steps=steps)

        # 3) observe the desktop
        if any(w in low for w in ("observe", "look at", "describe", "what is on screen")):
            step("observe desktop", [self._observe_action()])
            return Plan(objective_id=objective.objective_id, steps=steps)

        # 4) unrecognized — observe, then escalate honestly
        objective.constraints.append("planner could not derive concrete steps from goal")
        step("observe desktop", [self._observe_action()])
        return Plan(objective_id=objective.objective_id, steps=steps)

    @staticmethod
    def _app_mentioned(low: str) -> str | None:
        for phrase, command in APP_ALIASES.items():
            if phrase in low:
                return command
        m = re.search(r"(?:open|launch|start)\s+([a-z0-9._-]+)", low)
        return m.group(1) if m else None

    @staticmethod
    def _app_action(command: str) -> Action:
        return Action(kind=ActionKind.APP_LAUNCH, params={"command": command},
                      target=command, risk=RiskClass.HIGH)

    @staticmethod
    def _observe_action() -> Action:
        return Action(kind=ActionKind.NOOP, params={"observe": True}, timeout_s=1.0)


@dataclass
class RunResult:
    objective_id: str
    goal: str
    status: str
    verified: bool
    steps_attempted: int = 0
    steps_succeeded: int = 0
    verifications: list[VerificationResult] = field(default_factory=list)
    escalations: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    detail: str = ""
    plan: Plan | None = None
    learnings: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id, "goal": self.goal, "status": self.status,
            "verified": self.verified, "steps_attempted": self.steps_attempted,
            "steps_succeeded": self.steps_succeeded,
            "verifications": [v.to_dict() for v in self.verifications],
            "escalations": self.escalations, "strategies": self.strategies,
            "detail": self.detail, "learnings": self.learnings,
            "plan": self.plan.to_dict() if self.plan else None,
        }


class Orchestrator:
    def __init__(self, *, settings: Any, policy: Policy, eye: Eye, body: Any,
                 router: Any, memory: Memory, logger: Any = None,
                 state_store: StateStore | None = None, verifier: Verifier | None = None,
                 recovery: RecoveryManager | None = None, planner: Any = None) -> None:
        self.settings = settings
        self.policy = policy
        self.eye = eye
        self.body = body
        self.router = router
        self.memory = memory
        self.logger = logger
        self.state_store = state_store
        self.verifier = verifier or Verifier(eye)
        self.recovery = recovery or RecoveryManager()
        self.planner = planner or RulePlanner(router)
        # Counts memory writes that could not be persisted (e.g. a remote Memory
        # service was momentarily unavailable). Never silently treated as stored.
        self.memory_degraded = 0

    # objective -------------------------------------------------------------
    def objective_from_goal(self, goal: str) -> Objective:
        objective = Objective(
            goal=goal,
            success_criteria=self._default_criteria(goal),
            priorities=["safety", "correctness", "completeness"],
            max_risk=max_risk_from_str(self.settings.max_risk),
            budget={"max_steps": 50, "max_seconds": 1800},
            stopping_conditions=["success criteria verified", "budget exhausted",
                                 "escalated to user"],
        )
        return objective

    @staticmethod
    def _default_criteria(goal: str) -> list[str]:
        g = goal.lower()
        if "type" in g:
            return ["screen changes (typed text observed)"]
        if g.startswith("open") or "launch" in g:
            return ["window for target application exists"]
        return ["desktop observed"]

    # run -------------------------------------------------------------------
    def run(self, goal: str) -> RunResult:
        objective = self.objective_from_goal(goal)
        result = RunResult(objective_id=objective.objective_id, goal=goal,
                           status="pending", verified=False)
        if self.state_store is not None:
            self.state_store.begin_task(objective.objective_id, description=goal,
                                        expected_result="; ".join(objective.success_criteria))
        objective.status = ObjectiveStatus.ACTIVE
        plan = self.planner.plan(objective)
        result.plan = plan
        unrecognized = any("could not derive" in c for c in objective.constraints)
        if unrecognized:
            result.escalations.append(
                "planner could not derive concrete steps from the goal; ask the user to clarify")

        started = time.monotonic()
        max_steps = int(objective.budget.get("max_steps", 50))
        max_seconds = float(objective.budget.get("max_seconds", 1800))

        all_verified = True
        for step in plan.steps[:max_steps]:
            if time.monotonic() - started > max_seconds:
                result.escalations.append("budget: time exhausted")
                all_verified = False
                break
            if self.policy.emergency_stopped:
                result.escalations.append("emergency stop")
                all_verified = False
                break
            result.steps_attempted += 1
            ok, verdict = self._execute_step(step, objective)
            if verdict is not None:
                result.verifications.append(verdict)
            if ok:
                result.steps_succeeded += 1
            else:
                all_verified = False
                if verdict is not None and "escalate" in verdict.detail.lower():
                    result.escalations.append(f"step {step.step_id}: {verdict.detail}")

        result.verified = all_verified and result.steps_attempted > 0 and not unrecognized
        result.status = "verified" if result.verified else (
            "escalated" if result.escalations else "incomplete")
        objective.status = ObjectiveStatus.VERIFIED if result.verified else ObjectiveStatus.FAILED
        result.detail = (
            f"{result.steps_succeeded}/{result.steps_attempted} steps verified"
            + (f"; escalations: {len(result.escalations)}" if result.escalations else ""))
        result.learnings = self._learn(goal, result, plan)

        if self.state_store is not None:
            self.state_store.finish_task(
                objective.objective_id,
                status="success" if result.verified else "partial",
                note=result.detail)
            self.state_store.checkpoint(
                f"run:{objective.objective_id[:8]}",
                note=result.detail,
                data={"last_goal": goal, "verified": result.verified})
        return result

    # step ------------------------------------------------------------------
    def _execute_step(self, step: PlanStep, objective: Objective
                      ) -> tuple[bool, VerificationResult | None]:
        before = self._screen()
        for action in step.actions:
            ok = self._run_action(action, before)
            if not ok:
                verdict = VerificationResult(
                    ok=False, criterion=step.description,
                    detail=f"step {step.step_id} failed and could not be safely recovered; "
                           "escalate to user if needed")
                return False, verdict
        if step.verify:
            verdict = self.verifier.verify_postcondition(
                Action(kind=ActionKind.NOOP, expected_postcondition=step.verify),
                before=before)
        else:
            verdict = self.verifier.verify_criterion("desktop observed", before=before)
        return verdict.ok, verdict

    def _run_action(self, action: Action, before: ScreenState | None) -> bool:
        signature = action_signature(action)
        pcv = None
        if action.expected_postcondition:
            pcv = lambda a, r: self.verifier.verify_postcondition(a, r, before).ok  # noqa: E731

        while True:
            result = self.body.execute(action, postcondition_verifier=pcv)
            if result.ok:
                self.recovery.ledger.reset(signature)
                return True

            # Before retrying, check whether it may already have succeeded.
            if action.expected_postcondition and self._already_satisfied(action):
                return True

            failure = classify_result(result)
            # Choose the strategy based on attempts so far, THEN record this one,
            # so the first failure yields RETRY (not ALT_METHOD).
            strategy = self.recovery.next_strategy(signature, failure)
            self.recovery.ledger.record(signature, failure)
            self._log("action failed", action_id=result.action_id,
                      data={"kind": action.kind.value, "failure": failure.value,
                            "strategy": strategy.value, "error": result.error})
            if strategy is Strategy.RETRY and self.recovery.ledger.should_retry(signature):
                continue
            return False

    def _already_satisfied(self, action: Action) -> bool:
        cond = action.expected_postcondition
        if not cond:
            return False
        return self.verifier.verify_postcondition(
            Action(kind=ActionKind.NOOP, expected_postcondition=cond)).ok

    # learning --------------------------------------------------------------
    def _learn(self, goal: str, result: RunResult, plan: Plan) -> int:
        entries: list[tuple[str, str, float, list[str]]] = []
        if result.verified:
            entries.append((f"goal succeeded: {goal!r} via {len(plan.steps)} step(s)",
                            "lesson", 0.7, ["success", "planning"]))
        else:
            entries.append((f"goal incomplete: {goal!r} — {result.detail}",
                            "lesson", 0.6, ["failure", "planning"]))
        if result.escalations:
            entries.append((f"escalation needed for {goal!r}: {result.escalations[0]}",
                            "environment", 0.5, ["escalation"]))
        count = 0
        for content, kind, confidence, tags in entries:
            try:
                self.memory.add(content, kind=kind, confidence=confidence, tags=tags)
                count += 1
            except Exception as exc:  # noqa: BLE001 - memory must not abort a run
                # A write that could not be persisted is never counted as stored.
                self.memory_degraded += 1
                self._log("memory write failed", data={"error": str(exc)})
        return count

    # evaluation ------------------------------------------------------------
    def evaluate(self, result: RunResult) -> dict[str, Any]:
        attempted = max(1, result.steps_attempted)
        return {
            "progress": result.steps_succeeded / attempted,
            "verified": result.verified,
            "verifications_passed": sum(1 for v in result.verifications if v.ok),
            "verifications_failed": sum(1 for v in result.verifications if not v.ok),
            "recommendation": "stop" if result.verified else (
                "escalate" if result.escalations else "replan"),
        }

    # helpers ---------------------------------------------------------------
    def _screen(self) -> ScreenState | None:
        current = getattr(self.eye, "current", None)
        if callable(current):
            return current()
        snap = getattr(self.eye, "snapshot", None)
        if callable(snap):
            try:
                return snap()
            except TypeError:
                return snap(wait=False)
        return None

    def _log(self, msg: str, *, action_id: str = "", data: dict[str, Any] | None = None) -> None:
        if self.logger is not None:
            try:
                from .logging_utils import log_event

                log_event(self.logger, msg, event="action", data=data or {}, action_id=action_id)
            except Exception:  # noqa: BLE001
                pass
