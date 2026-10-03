"""Tests for real model provider adapters and `configured_providers` (H5).

HTTP is never really performed: `_post_json` / `urlopen` are monkeypatched so we
verify the request shape and parsing, not the network.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from blaxcy.brain import providers
from blaxcy.brain.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    configured_providers,
)
from blaxcy.brain.registry import REASONING, ModelSpec, OllamaProvider, Registry
from blaxcy.brain.router import FailureKind, Need, Router

_CREDENTIAL_VARS = (
    "BLAXCY_OPENAI_API_KEY", "OPENAI_API_KEY",
    "BLAXCY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY",
    "BLAXCY_GROQ_API_KEY", "GROQ_API_KEY",
    "BLAXCY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY",
    "BLAXCY_TOGETHER_API_KEY", "TOGETHER_API_KEY",
    "BLAXCY_LOCAL_BASE_URL",
)


class _Failing:
    def __init__(self, name, exc):
        self.name = name
        self.exc = exc

    def is_available(self):
        return True

    def complete(self, prompt, **kwargs):
        raise self.exc


class _FlakyOnce:
    def __init__(self, name, error, text="ok"):
        self.name = name
        self.error = error
        self.text = text
        self.calls = 0

    def is_available(self):
        return True

    def complete(self, prompt, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return self.text


class _Static:
    def __init__(self, name, text):
        self.name = name
        self.text = text

    def is_available(self):
        return True

    def complete(self, prompt, **kwargs):
        return self.text


class _FakeResponse:
    status = 200

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def test_configured_providers_empty_without_credentials(monkeypatch):
    for var in _CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    assert configured_providers() == []


def test_configured_providers_uses_env_key(monkeypatch):
    for var in _CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BLAXCY_OPENAI_API_KEY", "sk-test")
    entries = {spec.name: provider for spec, provider in configured_providers()}
    assert "openai" in entries
    assert entries["openai"].is_available() is True


def test_openai_compatible_provider_posts_and_parses(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update(url=url, payload=payload, headers=headers)
        return {"choices": [{"message": {"content": "hello"}}]}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    provider = OpenAICompatibleProvider("openai", "https://api.example/v1/", "sk-x", "gpt-test")
    assert provider.is_available() is True
    assert provider.complete("hi") == "hello"
    assert captured["url"] == "https://api.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-x"
    assert captured["payload"]["model"] == "gpt-test"


def test_anthropic_provider_posts_and_parses(monkeypatch):
    captured = {}

    def fake_post(url, payload, headers, timeout):
        captured.update(url=url, headers=headers)
        return {"content": [{"text": "claude says hi"}]}

    monkeypatch.setattr(providers, "_post_json", fake_post)
    provider = AnthropicProvider(api_key="ak-test")
    assert provider.complete("hi") == "claude says hi"
    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "ak-test"


def test_providers_report_unavailable_without_key():
    assert OpenAICompatibleProvider("openai", "https://x/v1", "", "m").is_available() is False
    assert AnthropicProvider(api_key="").is_available() is False


def test_ollama_availability_and_model_detection(monkeypatch):
    def fake_urlopen(url, timeout=None):
        assert url.endswith("/api/tags")
        return _FakeResponse(json.dumps({"models": [{"name": "llama3"}]}).encode())

    monkeypatch.setattr("blaxcy.brain.registry.urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider(host="http://127.0.0.1:11434")
    assert provider.is_available() is True
    assert provider.detect_model() == "llama3"


def test_ollama_unavailable_when_api_absent(monkeypatch):
    def boom(url, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("blaxcy.brain.registry.urllib.request.urlopen", boom)
    provider = OllamaProvider()
    assert provider.is_available() is False
    assert provider.detect_model() is None


def test_configured_providers_groq_and_openrouter_presets(monkeypatch):
    for var in _CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    entries = {spec.name: provider for spec, provider in configured_providers()}
    assert {"groq", "openrouter"} <= set(entries)
    assert entries["groq"].is_available()


def test_configured_providers_local_requires_base_url(monkeypatch):
    for var in _CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    assert "local" not in {s.name for s, _ in configured_providers()}
    monkeypatch.setenv("BLAXCY_LOCAL_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("BLAXCY_LOCAL_MODEL", "qwen")
    entries = {spec.name: provider for spec, provider in configured_providers()}
    assert "local" in entries and entries["local"].is_available()


def test_router_retries_transient_failure():
    registry = Registry()
    provider = _FlakyOnce("flaky", TimeoutError("timed out"))
    registry.register(ModelSpec(name="flaky", provider="flaky", capabilities=[REASONING]), provider)
    router = Router(registry, retries=1, backoff_s=0.0, cooldown_s=0.0)
    completion = router.complete("x", Need(capability=REASONING))
    assert completion.ok and completion.text == "ok"
    assert provider.calls == 2
    assert [a["attempt"] for a in completion.attempts] == [0, 1]


def test_router_cools_down_failed_provider():
    registry = Registry()
    registry.register(ModelSpec(name="bad", provider="bad", capabilities=[REASONING]),
                      _Failing("bad", RuntimeError("api exploded")))
    router = Router(registry, retries=0, cooldown_s=30.0)
    assert not router.complete("x", Need(capability=REASONING)).ok
    assert "bad" in router.cooling()
    second = router.complete("x", Need(capability=REASONING))
    assert not second.ok
    assert second.error_kind is FailureKind.CAPABILITY_MISMATCH


def test_router_uses_alternative_after_primary_cools():
    registry = Registry()
    registry.register(ModelSpec(name="bad", provider="bad", capabilities=[REASONING], priority=1),
                      _Failing("bad", RuntimeError("down")))
    registry.register(ModelSpec(name="good", provider="good", capabilities=[REASONING], priority=2),
                      _Static("good", "from-good"))
    router = Router(registry, retries=0, cooldown_s=30.0)
    first = router.complete("x", Need(capability=REASONING))
    assert first.ok and first.model == "good"
    assert "bad" in router.cooling()
    second = router.complete("x", Need(capability=REASONING))
    assert second.ok and second.attempts[0]["model"] == "good"


def test_ollama_end_to_end_when_available():
    """Real local model round-trip; skips honestly when Ollama has no model."""
    provider = OllamaProvider(timeout=30.0)
    if not provider.is_available() or not provider.detect_model():
        pytest.skip("no local Ollama model available")
    out = provider.complete("Reply with the single word: PONG")
    assert isinstance(out, str) and out.strip()


def test_default_registry_router_uses_local_model_when_available():
    """End-to-end: `default_registry` → Router selects the live Ollama model."""
    from blaxcy.brain import default_registry

    registry = default_registry()
    provider = registry.provider("ollama")
    if provider is None or not provider.is_available() or not provider.detect_model():
        pytest.skip("no local Ollama model available")
    completion = Router(registry).complete("Reply with the single word: PONG",
                                           Need(capability=REASONING))
    assert completion.ok
    assert completion.model in {"ollama", "offline-deterministic"}
    assert completion.text.strip()


def test_router_routes_to_a_configured_provider(monkeypatch):
    monkeypatch.setattr(
        providers, "_post_json",
        lambda url, payload, headers, timeout: {"choices": [{"message": {"content": "routed"}}]},
    )
    registry = Registry()
    registry.register(
        ModelSpec(name="openai", provider="openai", capabilities=[REASONING], priority=1),
        OpenAICompatibleProvider("openai", "https://api.example/v1", "sk", "m"),
    )
    completion = Router(registry).complete("plan", Need(capability=REASONING))
    assert completion.ok
    assert completion.text == "routed"
    assert completion.model == "openai"
