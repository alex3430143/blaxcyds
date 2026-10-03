"""The Body — executes policy-approved actions and returns an ActionResult.

Safety guarantees enforced here:
* every action is checked by Policy before running;
* real input only occurs when Policy says the action is not simulated;
* a per-action timeout is enforced, and on timeout the backend releases all
  held buttons/keys;
* every action produces an ActionResult — "action sent" is never reported as
  success on its own.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from ..models import Action, ActionResult, ActionStatus
from ..policy import Policy
from .backends import BodyBackend, DryRunBackend

Heartbeat = Callable[[], None]


class Body:
    def __init__(self, backend: BodyBackend, policy: Policy, *,
                 on_heartbeat: Heartbeat | None = None) -> None:
        self.backend = backend
        self.dry_backend = DryRunBackend()
        self.policy = policy
        self.on_heartbeat = on_heartbeat
        self.executed = 0
        self.blocked = 0
        self._last_heartbeat = time.time()

    # heartbeat -------------------------------------------------------------
    def touch(self) -> None:
        self._last_heartbeat = time.time()
        if self.on_heartbeat is not None:
            self.on_heartbeat()

    def heartbeat_age(self) -> float:
        return time.time() - self._last_heartbeat

    def alive(self, max_age_s: float = 30.0) -> bool:
        return self.heartbeat_age() <= max_age_s

    # execution -------------------------------------------------------------
    def execute(self, action: Action,
                postcondition_verifier: Callable[[Action, ActionResult], bool] | None = None,
                ) -> ActionResult:
        self.touch()
        started = time.time()
        decision = self.policy.check(action)

        if not decision.allowed:
            self.blocked += 1
            return ActionResult(
                action_id=action.action_id, status=ActionStatus.BLOCKED,
                correlation_id=action.correlation_id, started_at=started,
                finished_at=time.time(), backend="none", error=decision.reason,
                observed={
                    "risk": decision.risk.value,
                    "requires_confirmation": decision.requires_confirmation,
                    "escalate_to_user": decision.escalate_to_user,
                },
                detail=decision.reason,
            )

        backend = self.dry_backend if decision.simulated else self.backend
        status = ActionStatus.DRY_RUN if decision.simulated else ActionStatus.SUCCEEDED
        try:
            output = self._run_with_timeout(backend, action)
        except TimeoutError:
            self._safe_release()
            return ActionResult(
                action_id=action.action_id, status=ActionStatus.TIMEOUT,
                correlation_id=action.correlation_id, started_at=started,
                finished_at=time.time(), backend=backend.name,
                error=f"action exceeded timeout {action.timeout_s}s",
                observed={"risk": decision.risk.value},
                detail="timed out; inputs released",
            )
        except Exception as exc:  # noqa: BLE001 - report, never crash the loop
            self._safe_release()
            return ActionResult(
                action_id=action.action_id, status=ActionStatus.FAILED,
                correlation_id=action.correlation_id, started_at=started,
                finished_at=time.time(), backend=backend.name, error=str(exc),
                observed={"risk": decision.risk.value, "simulated": decision.simulated},
                detail="backend raised",
            )

        self.executed += 1
        result = ActionResult(
            action_id=action.action_id, status=status,
            correlation_id=action.correlation_id, started_at=started,
            finished_at=time.time(), backend=backend.name, output=output,
            observed={"risk": decision.risk.value, "simulated": decision.simulated,
                      **(output if isinstance(output, dict) else {})},
            detail="simulated (dry-run)" if decision.simulated else "performed",
        )

        if postcondition_verifier is not None and result.status in (
                ActionStatus.SUCCEEDED, ActionStatus.DRY_RUN):
            try:
                result.verified = bool(postcondition_verifier(action, result))
            except Exception as exc:  # noqa: BLE001
                result.verified = False
                result.detail += f" | verifier error: {exc}"
        return result

    def _run_with_timeout(self, backend: BodyBackend, action: Action) -> Any:
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["out"] = backend.perform(action)
            except BaseException as exc:  # noqa: BLE001
                box["err"] = exc

        thread = threading.Thread(target=target, name="blaxcy-body", daemon=True)
        thread.start()
        thread.join(timeout=max(0.01, action.timeout_s))
        if thread.is_alive():
            raise TimeoutError()
        if "err" in box:
            raise box["err"]
        return box.get("out")

    def _safe_release(self) -> None:
        try:
            self.backend.release_all()
        except Exception:  # noqa: BLE001
            pass

    def panic_release(self) -> None:
        self._safe_release()

    def health(self) -> dict[str, Any]:
        return {
            "backend": self.backend.name,
            "executed": self.executed,
            "blocked": self.blocked,
            "heartbeat_age_s": round(self.heartbeat_age(), 3),
            "alive": self.alive(),
        }
