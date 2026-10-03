"""Browser tool — real Chrome/Chromium control through the Body.

Like every tool, it turns an intent into typed `Action`s and submits them through
the Body, so Policy and the safety latches apply uniformly. It never bypasses
Policy: the powerful `evaluate` (arbitrary page JS, classified HIGH) is refused
unless the caller explicitly opts in *and* the action is approved.

A blocked result carries the `action_id` (and whether it requires confirmation or
an auth hand-off) so a caller can approve it and retry.
"""

from __future__ import annotations

from typing import Any

from ..models import Action, ActionKind
from .base import ToolResult


class BrowserTool:
    name = "browser"
    description = "Drive a real Chrome/Chromium over the DevTools Protocol (policy-gated)."

    def __init__(self, body: Any, policy: Any = None) -> None:
        self.body = body
        self.policy = policy

    # low-level -------------------------------------------------------------
    def _execute(self, action: Action, *, allow_high_risk: bool = False) -> ToolResult:
        if allow_high_risk and self.policy is not None:
            self.policy.approve(action.action_id)
        result = self.body.execute(action)
        if result.status.value == "blocked":
            return ToolResult(
                ok=False, results=[result], error=result.error or "blocked by policy",
                output={
                    "blocked": True,
                    "action_id": action.action_id,
                    "requires_confirmation": bool(result.observed.get("requires_confirmation")),
                    "escalate_to_user": bool(result.observed.get("escalate_to_user")),
                })
        if not result.ok:
            return ToolResult(ok=False, results=[result],
                              error=result.error or "browser action failed")
        return ToolResult(ok=True, results=[result], output=result.output)

    @staticmethod
    def _action(kind: ActionKind, params: dict[str, Any], *, target: str | None = None,
                timeout_s: float = 30.0) -> Action:
        return Action(kind=kind, params=params, target=target, timeout_s=timeout_s)

    # high-level ------------------------------------------------------------
    def navigate(self, url: str, *, timeout_s: float = 30.0) -> ToolResult:
        return self._execute(self._action(ActionKind.BROWSER_NAVIGATE, {"url": url},
                                          target=url, timeout_s=timeout_s))

    def query(self, selector: str, *, timeout_s: float = 10.0) -> ToolResult:
        return self._execute(self._action(ActionKind.BROWSER_QUERY, {"selector": selector},
                                          target=selector, timeout_s=timeout_s))

    def click(self, selector: str, *, timeout_s: float = 10.0) -> ToolResult:
        return self._execute(self._action(ActionKind.BROWSER_CLICK, {"selector": selector},
                                          target=selector, timeout_s=timeout_s))

    def type_text(self, selector: str, text: str, *, timeout_s: float = 10.0) -> ToolResult:
        return self._execute(self._action(ActionKind.BROWSER_TYPE,
                                          {"selector": selector, "text": text},
                                          target=selector, timeout_s=timeout_s))

    def screenshot(self, path: str | None = None, *, timeout_s: float = 20.0) -> ToolResult:
        params: dict[str, Any] = {}
        if path:
            params["path"] = path
        return self._execute(self._action(ActionKind.BROWSER_SCREENSHOT, params,
                                          timeout_s=timeout_s))

    def evaluate(self, expression: str, *, allow_high_risk: bool = False,
                 timeout_s: float = 20.0) -> ToolResult:
        """Run arbitrary page JS. Classified HIGH — refused unless explicitly allowed."""
        return self._execute(self._action(ActionKind.BROWSER_EVAL, {"expression": expression},
                                          timeout_s=timeout_s),
                             allow_high_risk=allow_high_risk)

    # convenience reads (LOW risk; no arbitrary JS required) --------------
    def title(self) -> ToolResult:
        return self._execute(self._action(ActionKind.BROWSER_TITLE, {}))

    def current_url(self) -> ToolResult:
        return self._execute(self._action(ActionKind.BROWSER_URL, {}))
