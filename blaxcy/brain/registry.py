"""Model / provider registry.

BLAXCY must not hard-code a single model as its only intelligence. Providers are
registered with capability descriptors; the router selects among them. A
deterministic offline provider is always present so the system has a working
planner even with zero configured models — and providers report their own
availability honestly.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Capability names
REASONING = "reasoning"
PLANNING = "planning"
VISION = "vision"
CODING = "coding"
TOOLS = "tools"


@dataclass
class ModelSpec:
    name: str
    provider: str
    capabilities: list[str] = field(default_factory=lambda: [REASONING])
    context: int = 8192
    local: bool = False
    cost: float = 1.0
    priority: int = 100  # lower = preferred

    def has(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@runtime_checkable
class Provider(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def complete(self, prompt: str, **kwargs: Any) -> str: ...


class DeterministicProvider:
    """Always-available offline provider.

    It does not pretend to be an LLM. It produces a deterministic plan skeleton
    so the orchestrator is functional without any external model, and clearly
    labels its output as a deterministic fallback.
    """

    name = "offline-deterministic"

    def is_available(self) -> bool:
        return True

    def complete(self, prompt: str, **kwargs: Any) -> str:
        return json.dumps({
            "provider": self.name,
            "note": "deterministic offline fallback (not a language model)",
            "prompt_digest": prompt[:280],
        })


class UnavailableProvider:
    """Reports itself unavailable; used to prove we never claim it works."""

    def __init__(self, name: str, reason: str = "not configured") -> None:
        self.name = name
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def complete(self, prompt: str, **kwargs: Any) -> str:  # pragma: no cover - never called
        raise RuntimeError(f"provider {self.name} is unavailable: {self.reason}")


class OllamaProvider:
    """Minimal, honest Ollama adapter.

    Availability is determined by actually probing the local API; if Ollama is
    not running, this provider reports unavailable rather than pretending.
    """

    def __init__(self, name: str = "ollama", host: str = "http://127.0.0.1:11434",
                 model: str = "", timeout: float = 60.0) -> None:
        self.name = name
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._resolved: str | None = None

    def detect_model(self) -> str | None:
        """Return the installed model to use (first available if unspecified)."""
        if self.model:
            return self.model
        if self._resolved:
            return self._resolved
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=1.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = data.get("models", [])
            if models:
                self._resolved = str(models[0].get("name", ""))
                return self._resolved
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            return None
        return None

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=1.5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, TimeoutError):
            return False

    def complete(self, prompt: str, **kwargs: Any) -> str:
        model = kwargs.get("model") or self.detect_model()
        if not model:
            raise RuntimeError("no ollama model installed")
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(f"{self.host}/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return str(data.get("response", ""))


class Registry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}
        self._specs: dict[str, ModelSpec] = {}

    def register(self, spec: ModelSpec, provider: Provider) -> None:
        self._specs[spec.name] = spec
        self._providers[spec.name] = provider

    def specs(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def provider(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def spec(self, name: str) -> ModelSpec | None:
        return self._specs.get(name)

    def available(self) -> list[ModelSpec]:
        out = []
        for spec in self._specs.values():
            provider = self._providers.get(spec.name)
            if provider is not None:
                try:
                    if provider.is_available():
                        out.append(spec)
                except Exception:  # noqa: BLE001 - availability probe must not raise
                    continue
        return out

    def status(self) -> list[dict[str, Any]]:
        rows = []
        for spec in self._specs.values():
            provider = self._providers.get(spec.name)
            try:
                avail = bool(provider and provider.is_available())
            except Exception:  # noqa: BLE001
                avail = False
            rows.append({**spec.to_dict(), "available": avail})
        return rows


def default_registry() -> Registry:
    """A registry with the offline provider, an honestly-probed Ollama, and any
    remote providers configured via the environment (including a project-local
    gitignored `.env`, so keys need not be exported manually)."""
    try:
        from ..config import load_env_file

        load_env_file()
    except Exception:  # noqa: BLE001 - env loading must never break startup
        pass
    reg = Registry()
    reg.register(
        ModelSpec(name="offline-deterministic", provider="offline-deterministic",
                  capabilities=[REASONING, PLANNING], local=True, cost=0.0, priority=999),
        DeterministicProvider(),
    )
    reg.register(
        ModelSpec(name="ollama", provider="ollama",
                  capabilities=[REASONING, PLANNING, CODING, VISION, TOOLS],
                  local=True, cost=0.1, priority=50),
        OllamaProvider(name="ollama"),
    )
    # Remote providers are added only when credentials are configured.
    try:
        from .providers import configured_providers

        for spec, provider in configured_providers():
            reg.register(spec, provider)
    except Exception:  # noqa: BLE001 - a bad provider config must not break startup
        pass
    return reg
