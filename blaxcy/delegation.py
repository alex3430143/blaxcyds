"""Agent delegation — ask another model/agent to do a sub-task, then verify it.

BLAXCY can delegate work (research, code, debugging, a second opinion) to other
models. The result is **never trusted blindly**:

* the raw output starts at `TrustLevel.UNTRUSTED`;
* the caller asks for concrete, machine-checkable verification (does the code
  compile? is it valid JSON?) and/or a **cross-check** from a *different* model;
* only when independent verification passes does the trust level rise to
  `DERIVED` — and even then it is not silently promoted to a trusted instruction.

Delegation itself is a safe resource; any *action* the result later suggests still
has to pass through Policy like everything else.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .models import TrustLevel

_CODE_RE = re.compile(r"```[a-zA-Z0-9_+\-]*\n(.*?)```", re.S)


# --------------------------------------------------------------------------- #
# verification helpers (pure, testable)
# --------------------------------------------------------------------------- #
@dataclass
class Verification:
    ok: bool
    method: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "method": self.method, "detail": self.detail}


def extract_code(text: str) -> str:
    blocks = _CODE_RE.findall(text or "")
    return "\n\n".join(block.strip("\n") for block in blocks) if blocks else ""


def verify_code(text: str) -> Verification:
    """Verify the delegated text contains Python that actually compiles."""
    code = extract_code(text)
    if not code:
        return Verification(False, "code", "no fenced code block found")
    try:
        compile(code, "<delegated>", "exec")
    except SyntaxError as exc:
        return Verification(False, "code", f"syntax error: {exc}")
    return Verification(True, "code", f"compiles ({len(code.splitlines())} lines)")


def _extract_json_blob(text: str) -> str | None:
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                json.loads(candidate)
                return candidate
            except ValueError:
                continue
    return None


def verify_json(text: str) -> Verification:
    blob = _extract_json_blob(text or "")
    if blob is None:
        return Verification(False, "json", "no valid JSON found")
    return Verification(True, "json", "valid JSON")


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def verify_agreement(first: str, second: str) -> Verification:
    """Cross-check: two independent models must broadly agree."""
    if not second.strip():
        return Verification(False, "cross_check", "no second opinion available")
    a, b = _normalise(first), _normalise(second)
    if a == b:
        return Verification(True, "cross_check", "two models agree exactly")
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return Verification(False, "cross_check", "empty response")
    overlap = len(ta & tb) / len(ta | tb)
    if overlap >= 0.8:
        return Verification(True, "cross_check", f"high overlap ({overlap:.2f})")
    return Verification(False, "cross_check", f"models disagree (overlap {overlap:.2f})")


_VERIFIERS = {"code": verify_code, "json": verify_json}


# --------------------------------------------------------------------------- #
# result
# --------------------------------------------------------------------------- #
@dataclass
class DelegationResult:
    ok: bool
    task: str
    model: str = ""
    output: str = ""
    trust: TrustLevel = TrustLevel.UNTRUSTED
    verified: bool = False
    verifications: list[Verification] = field(default_factory=list)
    cross_model: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    degraded: bool = False  # answered by the deterministic offline fallback, not a model

    def is_instruction_safe(self) -> bool:
        """Only independently verified output may be treated as BLAXCY's own."""
        return bool(self.verified and self.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok, "task": self.task, "model": self.model,
            "output": self.output, "trust": self.trust.value,
            "verified": self.verified, "cross_model": self.cross_model,
            "verifications": [v.to_dict() for v in self.verifications],
            "attempts": self.attempts, "error": self.error,
            "degraded": self.degraded,
            "instruction_safe": self.is_instruction_safe(),
        }


# --------------------------------------------------------------------------- #
# tool
# --------------------------------------------------------------------------- #
class DelegationTool:
    name = "delegation"
    description = "Delegate a sub-task to another model and independently verify the result."

    def __init__(self, router: Any, *, memory: Any = None, policy: Any = None) -> None:
        self.router = router
        self.memory = memory
        self.policy = policy

    def _build_prompt(self, task: str) -> str:
        return (
            "You are being delegated a task by BLAXCY. Do the task and return only the "
            "result. If the task asks for code, put it in a single fenced code block. "
            "If the task asks for data, return JSON.\n\nTASK:\n" + task
        )

    def _second_opinion(self, task: str, capability: str, exclude: str
                        ) -> tuple[str, str] | None:
        """Ask a different model the same task.

        Uses `Router.second_opinion` so this works whether the Brain is local or
        a `RemoteBrain` service — the caller never reaches into the registry.
        """
        from .brain.router import Need

        method = getattr(self.router, "second_opinion", None)
        if not callable(method):
            return None
        return method(self._build_prompt(task), Need(capability=capability), exclude)

    def delegate(self, task: str, *, capability: str = "reasoning",
                 verify: tuple[str, ...] = (), cross_check: bool = False) -> DelegationResult:
        from .brain.router import Need

        completion = self.router.complete(self._build_prompt(task), Need(capability=capability))
        if not completion.ok:
            return DelegationResult(ok=False, task=task, attempts=completion.attempts,
                                    error=completion.error or "all delegate models failed")

        output = completion.text
        verifications: list[Verification] = []
        for name in verify:
            checker = _VERIFIERS.get(name)
            if checker is not None:
                verifications.append(checker(output))

        cross_model = ""
        if cross_check:
            second = self._second_opinion(task, capability, exclude=completion.model)
            if second is not None:
                cross_model, second_text = second
                agreement = verify_agreement(output, second_text)
                agreement.detail = f"{cross_model}: {agreement.detail}"
                verifications.append(agreement)

        verified = bool(verifications) and all(v.ok for v in verifications)
        trust = TrustLevel.DERIVED if verified else TrustLevel.UNTRUSTED

        result = DelegationResult(
            ok=True, task=task, model=completion.model, output=output, trust=trust,
            verified=verified, verifications=verifications, cross_model=cross_model,
            attempts=completion.attempts,
            degraded=(completion.model == "offline-deterministic"))

        if self.memory is not None:
            self.memory.add(
                f"delegated {task!r} to {completion.model} (verified={verified})",
                kind="lesson", source=f"delegate:{completion.model}", trust=trust,
                confidence=0.7 if verified else 0.4, tags=["delegation"])
        return result
