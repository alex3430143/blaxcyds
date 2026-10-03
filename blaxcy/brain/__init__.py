"""The Brain — model registry and capability-aware router."""

from .registry import (
    CODING,
    PLANNING,
    REASONING,
    TOOLS,
    VISION,
    DeterministicProvider,
    ModelSpec,
    OllamaProvider,
    Registry,
    UnavailableProvider,
    default_registry,
)
from .providers import AnthropicProvider, OpenAICompatibleProvider, configured_providers
from .router import Completion, FailureKind, Need, Router, classify_error

__all__ = [
    "Registry", "ModelSpec", "default_registry",
    "DeterministicProvider", "UnavailableProvider", "OllamaProvider",
    "OpenAICompatibleProvider", "AnthropicProvider", "configured_providers",
    "Router", "Completion", "Need", "FailureKind", "classify_error",
    "REASONING", "PLANNING", "VISION", "CODING", "TOOLS",
]
