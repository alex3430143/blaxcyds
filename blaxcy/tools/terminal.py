"""Terminal tool — runs commands through the Body, so Policy gates them.

Commands are never run through a shell (no shell metacharacter expansion), which
removes a large class of injection risks. High-risk and destructive commands are
refused by Policy unless explicitly approved.
"""

from __future__ import annotations

import shlex
from typing import Any

from ..models import Action, ActionKind
from .base import ToolResult


class TerminalTool:
    name = "terminal"
    description = "Run a command on the local machine (policy-gated, no shell)."

    def __init__(self, body) -> None:  # body: blaxcy.body.Body
        self.body = body

    def actions(self, command: str, *, cwd: str | None = None,
                timeout_s: float = 30.0) -> list[Action]:
        params: dict[str, Any] = {"command": command}
        if cwd:
            params["cwd"] = cwd
        return [Action(kind=ActionKind.TERMINAL_RUN, params=params, timeout_s=timeout_s)]

    def run(self, command: str, *, cwd: str | None = None, timeout_s: float = 30.0) -> ToolResult:
        if not shlex.split(command):
            return ToolResult(ok=False, error="empty command")
        results = [self.body.execute(a) for a in self.actions(command, cwd=cwd, timeout_s=timeout_s)]
        result = results[0]
        if result.status.value == "blocked":
            return ToolResult(ok=False, results=results, error=result.error)
        if not result.ok:
            return ToolResult(ok=False, results=results, error=result.error or "command failed")
        output = result.output or {}
        if isinstance(output, dict) and output.get("returncode") not in (0, None):
            return ToolResult(ok=False, results=results, output=output,
                              error=f"exit code {output.get('returncode')}")
        return ToolResult(ok=True, results=results, output=output)
