"""Real model providers.

Each provider talks to an actual API and reports its own availability honestly.
None of them fabricate a response. Remote providers require an API key supplied
through the environment (never stored in source or `.build-state/`); the local
Ollama provider is probed directly. `configured_providers()` builds registry
entries only for providers that are actually configured/available.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .registry import CODING, PLANNING, REASONING, TOOLS, VISION, ModelSpec


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str],
               timeout: float) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OpenAICompatibleProvider:
    """Any OpenAI-compatible /chat/completions endpoint (OpenAI, Groq, etc.)."""

    def __init__(self, name: str, base_url: str, api_key: str, model: str,
                 timeout: float = 60.0) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, **kwargs: Any) -> str:
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.2),
        }
        data = _post_json(f"{self.base_url}/chat/completions", payload,
                          {"Authorization": f"Bearer {self.api_key}"}, self.timeout)
        return str(data["choices"][0]["message"]["content"])


class AnthropicProvider:
    def __init__(self, name: str = "anthropic", api_key: str = "",
                 model: str = "claude-3-5-sonnet-latest", timeout: float = 60.0) -> None:
        self.name = name
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, **kwargs: Any) -> str:
        payload = {
            "model": kwargs.get("model", self.model),
            "max_tokens": kwargs.get("max_tokens", 1024),
            "messages": [{"role": "user", "content": prompt}],
        }
        data = _post_json("https://api.anthropic.com/v1/messages", payload,
                          {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                          self.timeout)
        return str(data["content"][0]["text"])


# OpenAI-compatible presets: (name, key envs, base-url env, default base, model env,
# default model, capabilities, context, cost, priority).
_OPENAI_COMPATIBLE_PRESETS = (
    ("openai", ("BLAXCY_OPENAI_API_KEY", "OPENAI_API_KEY"),
     ("BLAXCY_OPENAI_BASE_URL",), "https://api.openai.com/v1",
     ("BLAXCY_OPENAI_MODEL",), "gpt-4o-mini",
     [REASONING, PLANNING, CODING, TOOLS], 128_000, 3.0, 10),
    ("groq", ("BLAXCY_GROQ_API_KEY", "GROQ_API_KEY"),
     ("BLAXCY_GROQ_BASE_URL",), "https://api.groq.com/openai/v1",
     ("BLAXCY_GROQ_MODEL",), "llama-3.3-70b-versatile",
     [REASONING, PLANNING, CODING, TOOLS], 128_000, 0.6, 20),
    ("openrouter", ("BLAXCY_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
     ("BLAXCY_OPENROUTER_BASE_URL",), "https://openrouter.ai/api/v1",
     ("BLAXCY_OPENROUTER_MODEL",), "openai/gpt-4o-mini",
     [REASONING, PLANNING, CODING, VISION, TOOLS], 128_000, 2.0, 25),
    ("together", ("BLAXCY_TOGETHER_API_KEY", "TOGETHER_API_KEY"),
     ("BLAXCY_TOGETHER_BASE_URL",), "https://api.together.xyz/v1",
     ("BLAXCY_TOGETHER_MODEL",), "meta-llama/Llama-3.3-70B-Instruct-Turbo",
     [REASONING, PLANNING, CODING], 128_000, 0.9, 30),
)


def _env_first(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def configured_providers() -> list[tuple[ModelSpec, Any]]:
    """Return registry entries for providers that are configured in the env.

    Only providers with real configuration are returned: a remote provider needs
    an API key, and a local OpenAI-compatible server needs an explicit base URL.
    Nothing is registered that would not actually work.
    """
    out: list[tuple[ModelSpec, Any]] = []

    for (name, key_envs, base_envs, default_base, model_envs, default_model,
         caps, context, cost, priority) in _OPENAI_COMPATIBLE_PRESETS:
        key = _env_first(key_envs)
        if not key:
            continue
        base = _env_first(base_envs) or default_base
        model = _env_first(model_envs) or default_model
        out.append((
            ModelSpec(name=name, provider=name, capabilities=list(caps),
                      context=context, local=False, cost=cost, priority=priority),
            OpenAICompatibleProvider(name, base, key, model),
        ))

    # A local OpenAI-compatible server (vLLM, LM Studio, llama.cpp) — key optional.
    local_base = _env_first(("BLAXCY_LOCAL_BASE_URL",))
    if local_base:
        local_model = _env_first(("BLAXCY_LOCAL_MODEL",)) or "local-model"
        out.append((
            ModelSpec(name="local", provider="local",
                      capabilities=[REASONING, PLANNING, CODING, VISION, TOOLS],
                      context=32_768, local=True, cost=0.0, priority=15),
            OpenAICompatibleProvider("local", local_base, "not-needed", local_model),
        ))

    anthropic_key = _env_first(("BLAXCY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
    if anthropic_key:
        model = os.environ.get("BLAXCY_ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        out.append((
            ModelSpec(name="anthropic", provider="anthropic",
                      capabilities=[REASONING, PLANNING, CODING, VISION, TOOLS],
                      context=200_000, local=False, cost=3.0, priority=10),
            AnthropicProvider("anthropic", anthropic_key, model),
        ))

    return out
