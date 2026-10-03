"""Filesystem tool — read/write through the Body; writes are confined to allowed
roots by the SystemBackend, and Policy gates the actions."""

from __future__ import annotations

from ..models import Action, ActionKind
from .base import ToolResult


class FilesystemTool:
    name = "filesystem"
    description = "Read or write files (writes confined to approved workspace roots)."

    def __init__(self, body) -> None:  # body: blaxcy.body.Body
        self.body = body

    def read(self, path: str) -> ToolResult:
        action = Action(kind=ActionKind.FS_READ, params={"path": path})
        result = self.body.execute(action)
        if not result.ok:
            return ToolResult(ok=False, results=[result], error=result.error or result.detail)
        return ToolResult(ok=True, results=[result], output=result.output)

    def write(self, path: str, content: str) -> ToolResult:
        action = Action(kind=ActionKind.FS_WRITE, params={"path": path, "content": content})
        result = self.body.execute(action)
        if not result.ok:
            return ToolResult(ok=False, results=[result], error=result.error or result.detail)
        return ToolResult(ok=True, results=[result], output=result.output)
