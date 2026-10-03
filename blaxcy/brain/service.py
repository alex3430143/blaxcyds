"""Run the Brain (model router) as a supervised process.

Model calls can be slow and remote, so isolating them from the orchestrator is a
real win: a hung or crashed provider can never take down perception or control.
This module provides:

* `build_router()` — the exact same `Router`/`default_registry` the in-process
  app builds, so provider routing, cooldown and the deterministic fallback are
  unchanged;
* `BrainService` — serves the router over the authenticated IPC with an explicit
  method whitelist and bounded inputs;
* `RemoteBrain` — a drop-in client mirroring the Router API the app uses.

Safety boundary: the Brain returns *text only*. It can never construct or
authorize a Body action. Any plan derived from model output must first pass
`blaxcy.planning.validate_model_plan` and then Policy, exactly as in-process.
"""

from __future__ import annotations

import os
from typing import Any

from ..config import Settings
from ..service import ServiceClient, ServiceError, ServiceServer, service_socket
from .registry import ModelSpec, default_registry
from .router import Completion, Need, Router

# A model prompt is bounded so a compromised/buggy caller cannot push an
# unbounded payload through the socket.
MAX_PROMPT = 200_000
# Primitive option values only — never arbitrary nested objects.
_ALLOWED_OPTION_TYPES = (str, int, float, bool, type(None))


def build_router() -> Router:
    return Router(default_registry())


def _clean_options(options: Any) -> dict[str, Any]:
    if not isinstance(options, dict):
        raise ServiceError("options must be a JSON object")
    clean: dict[str, Any] = {}
    for key, value in options.items():
        if not isinstance(key, str):
            raise ServiceError("option keys must be strings")
        if not isinstance(value, _ALLOWED_OPTION_TYPES):
            raise ServiceError(f"option {key!r} must be a JSON primitive")
        clean[key] = value
    return clean


class BrainService:
    """The model router, served over IPC (runs inside `blaxcy serve brain`)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.router = build_router()
        self.server = ServiceServer(
            "brain", self._handlers(),
            service_socket(settings, "brain"), settings.ipc_secret())

    def _handlers(self) -> dict[str, Any]:
        return {
            "health": self._health,
            "status": self.router.status,
            "cooling": self.router.cooling,
            "complete": self._complete,
            "candidates": self._candidates,
            "second_opinion": self._second_opinion,
        }

    def _health(self) -> dict[str, Any]:
        return {"ok": True, "pid": os.getpid(), "service": "brain"}

    def _complete(self, prompt: str = "", need: dict[str, Any] | None = None,
                  options: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(prompt, str):
            raise ServiceError("prompt must be a string")
        if len(prompt) > MAX_PROMPT:
            raise ServiceError(f"prompt too large ({len(prompt)} > {MAX_PROMPT})")
        completion = self.router.complete(prompt, Need.from_dict(need),
                                          **_clean_options(options))
        return completion.to_dict()

    def _candidates(self, need: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [spec.to_dict() for spec in self.router.candidates(Need.from_dict(need))]

    def _second_opinion(self, prompt: str = "", need: dict[str, Any] | None = None,
                        exclude: str = "") -> dict[str, Any] | None:
        if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT:
            raise ServiceError("invalid prompt")
        found = self.router.second_opinion(prompt, Need.from_dict(need), exclude)
        if found is None:
            return None
        model, text = found
        return {"model": model, "text": text}

    def run_forever(self) -> None:
        self.server.run_forever()


class RemoteBrain:
    """Client-side Brain that talks to `BrainService` over IPC.

    Mirrors the subset of the Router API the application uses. There is no silent
    fallback: if the service is unreachable the call raises, and callers report a
    degraded/unavailable state rather than inventing a model answer.
    """

    def __init__(self, settings: Settings, *, client: ServiceClient | None = None,
                 timeout: float = 180.0) -> None:
        self.socket_path = str(service_socket(settings, "brain"))
        self._client = client or ServiceClient(self.socket_path, settings.ipc_secret(),
                                               timeout=timeout)
        self.degraded_calls = 0
        self.last_error: str | None = None

    # transport -------------------------------------------------------------
    def _call(self, method: str, **args: Any) -> Any:
        try:
            return self._client.call(method, **args)
        except Exception as exc:  # noqa: BLE001
            self.degraded_calls += 1
            self.last_error = str(exc)
            raise

    # Router API ------------------------------------------------------------
    def complete(self, prompt: str, need: Need | None = None, **kwargs: Any) -> Completion:
        raw = self._call("complete", prompt=prompt, need=(need or Need()).to_dict(),
                         options=_clean_options(kwargs))
        return Completion.from_dict(raw if isinstance(raw, dict) else {})

    def candidates(self, need: Need | None = None) -> list[ModelSpec]:
        rows = self._call("candidates", need=(need or Need()).to_dict())
        return [ModelSpec(**row) for row in rows or []]

    def cooling(self) -> dict[str, float]:
        return dict(self._call("cooling") or {})

    def status(self) -> list[dict[str, Any]]:
        return list(self._call("status") or [])

    def second_opinion(self, prompt: str, need: Need | None = None,
                       exclude: str = "") -> tuple[str, str] | None:
        found = self._call("second_opinion", prompt=prompt,
                           need=(need or Need()).to_dict(), exclude=exclude)
        if not found:
            return None
        return str(found.get("model", "")), str(found.get("text", ""))

    # diagnostics -----------------------------------------------------------
    def health(self) -> dict[str, Any]:
        base: dict[str, Any]
        try:
            payload = self._client.call("health")
            base = dict(payload) if isinstance(payload, dict) else {"health": payload}
        except Exception as exc:  # noqa: BLE001
            base = {"service_reachable": False, "error": str(exc)}
        base["remote"] = True
        base["degraded_calls"] = self.degraded_calls
        if self.last_error:
            base["last_error"] = self.last_error
        return base
