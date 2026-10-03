"""Tools are resources, not identity.

A tool turns an intent into one or more typed Actions and submits them through
the Body, so Policy and the safety latches apply uniformly. Tools never bypass
Policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import Action, ActionResult


@dataclass
class ToolResult:
    ok: bool
    output: Any = None
    results: list[ActionResult] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "output": self.output,
                "results": [r.to_dict() for r in self.results], "error": self.error}


class Tool(Protocol):
    name: str
    description: str

    def actions(self, **kwargs: Any) -> list[Action]: ...
