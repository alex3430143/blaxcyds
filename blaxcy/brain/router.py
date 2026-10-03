"""Capability-aware model router with honest fallback.

Selects providers by need (capability, locality, context), then tries them in
order. Failures are classified rather than swallowed, and the router never
reports a model as working when it is not.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from .registry import ModelSpec, Registry


class FailureKind(str, Enum):
    UNAVAILABLE = "unavailable"
    QUOTA = "quota"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    API_ERROR = "api_error"
    CAPABILITY_MISMATCH = "capability_mismatch"
    UNKNOWN = "unknown"


def classify_error(exc: BaseException) -> FailureKind:
    text = f"{type(exc).__name__}: {exc}".lower()
    if isinstance(exc, TimeoutError):
        return FailureKind.TIMEOUT
    if "quota" in text or "insufficient" in text or "billing" in text:
        return FailureKind.QUOTA
    if "rate" in text and "limit" in text or "429" in text:
        return FailureKind.RATE_LIMIT
    if "unavailable" in text or "not configured" in text or "refused" in text or "connection" in text:
        return FailureKind.UNAVAILABLE
    if "capab" in text or "unsupported" in text:
        return FailureKind.CAPABILITY_MISMATCH
    if isinstance(exc, (OSError, ValueError, RuntimeError)):
        return FailureKind.API_ERROR
    return FailureKind.UNKNOWN


@dataclass
class Completion:
    ok: bool
    text: str = ""
    model: str = ""
    attempts: list[dict[str, object]] = field(default_factory=list)
    error_kind: FailureKind | None = None
    error: str | None = None
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok, "text": self.text, "model": self.model,
            "attempts": self.attempts,
            "error_kind": self.error_kind.value if self.error_kind else None,
            "error": self.error, "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "Completion":
        kind = d.get("error_kind")
        try:
            error_kind = FailureKind(kind) if kind else None
        except ValueError:
            error_kind = FailureKind.UNKNOWN
        return cls(
            ok=bool(d.get("ok")),
            text=str(d.get("text", "")),
            model=str(d.get("model", "")),
            attempts=list(d.get("attempts", [])) if isinstance(d.get("attempts"), list) else [],
            error_kind=error_kind,
            error=str(d["error"]) if d.get("error") else None,
            duration_s=float(d.get("duration_s", 0.0)),
        )


@dataclass
class Need:
    capability: str = "reasoning"
    local_only: bool = False
    min_context: int = 0
    prefer: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {"capability": self.capability, "local_only": self.local_only,
                "min_context": self.min_context, "prefer": self.prefer}

    @classmethod
    def from_dict(cls, d: dict[str, object] | None) -> "Need":
        if not d:
            return cls()
        return cls(
            capability=str(d.get("capability", "reasoning")),
            local_only=bool(d.get("local_only", False)),
            min_context=int(d.get("min_context", 0) or 0),
            prefer=str(d["prefer"]) if d.get("prefer") else None,
        )


_RETRYABLE = {FailureKind.TIMEOUT, FailureKind.RATE_LIMIT,
              FailureKind.API_ERROR, FailureKind.UNKNOWN}


class Router:
    def __init__(self, registry: Registry, timeout_s: float = 60.0, *,
                 retries: int = 1, backoff_s: float = 0.25,
                 cooldown_s: float = 30.0) -> None:
        self.registry = registry
        self.timeout_s = timeout_s
        self.retries = max(0, int(retries))
        self.backoff_s = max(0.0, float(backoff_s))
        self.cooldown_s = max(0.0, float(cooldown_s))
        self._cooldown_until: dict[str, float] = {}

    # cooldown --------------------------------------------------------------
    def _is_cooling(self, name: str) -> bool:
        return self._cooldown_until.get(name, 0.0) > time.monotonic()

    def _cool(self, name: str) -> None:
        if self.cooldown_s > 0:
            self._cooldown_until[name] = time.monotonic() + self.cooldown_s

    def cooling(self) -> dict[str, float]:
        now = time.monotonic()
        return {name: round(until - now, 2)
                for name, until in self._cooldown_until.items() if until > now}

    def candidates(self, need: Need) -> list[ModelSpec]:
        specs = [s for s in self.registry.available()
                 if s.has(need.capability)
                 and (not need.local_only or s.local)
                 and s.context >= need.min_context
                 and not self._is_cooling(s.name)]
        if need.prefer:
            specs.sort(key=lambda s: (s.name != need.prefer, s.priority, s.cost))
        else:
            specs.sort(key=lambda s: (s.priority, s.cost))
        return specs

    def complete(self, prompt: str, need: Need | None = None, **kwargs) -> Completion:
        need = need or Need()
        started = time.monotonic()
        attempts: list[dict[str, object]] = []
        candidates = self.candidates(need)
        if not candidates:
            return Completion(
                ok=False, attempts=attempts,
                error_kind=FailureKind.CAPABILITY_MISMATCH,
                error=f"no available model offers capability {need.capability!r}",
                duration_s=time.monotonic() - started,
            )
        for spec in candidates:
            provider = self.registry.provider(spec.name)
            if provider is None:
                attempts.append({"model": spec.name, "ok": False, "kind": "unavailable"})
                self._cool(spec.name)
                continue
            for retry in range(self.retries + 1):
                try:
                    text = provider.complete(prompt, **kwargs)
                    attempts.append({"model": spec.name, "ok": True, "attempt": retry})
                    return Completion(ok=True, text=text, model=spec.name, attempts=attempts,
                                      duration_s=time.monotonic() - started)
                except Exception as exc:  # noqa: BLE001 - fallback is the whole point
                    kind = classify_error(exc)
                    attempts.append({"model": spec.name, "ok": False, "kind": kind.value,
                                     "attempt": retry, "error": str(exc)})
                    if kind in _RETRYABLE and retry < self.retries:
                        if self.backoff_s:
                            time.sleep(self.backoff_s * (retry + 1))
                        continue
                    break
            self._cool(spec.name)
        kind_value = attempts[-1].get("kind") if attempts else None
        try:
            last_kind = FailureKind(kind_value) if kind_value else FailureKind.UNKNOWN
        except ValueError:
            last_kind = FailureKind.UNKNOWN
        return Completion(
            ok=False, attempts=attempts, error_kind=last_kind,
            error="all candidate models failed",
            duration_s=time.monotonic() - started,
        )

    def second_opinion(self, prompt: str, need: Need | None = None,
                       exclude: str = "") -> tuple[str, str] | None:
        """Ask a *different* candidate model the same prompt (for cross-checks).

        Exposed as a Router method so a remote Brain can offer it over IPC
        without the caller reaching into `router.registry`.
        """
        need = need or Need()
        for spec in self.candidates(need):
            if spec.name == exclude:
                continue
            provider = self.registry.provider(spec.name)
            if provider is None:
                continue
            try:
                return spec.name, str(provider.complete(prompt))
            except Exception:  # noqa: BLE001 - try the next candidate
                continue
        return None

    def status(self) -> list[dict[str, object]]:
        return self.registry.status()
