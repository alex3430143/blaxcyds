"""Policy — the single chokepoint for risk and safety.

Every action passes through `Policy.check()` before the Body is allowed to run
it. Policy also owns the global safety latches: emergency stop, pause, and user
takeover. Auth boundaries (lock screen, sudo/polkit, keyrings, 2FA, CAPTCHA) are
never auto-performed; they are escalated to the user.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from .models import Action, ActionKind, RiskClass, TrustLevel

# Risk ranking for comparisons.
_RANK = {
    RiskClass.SAFE: 0,
    RiskClass.LOW: 1,
    RiskClass.MEDIUM: 2,
    RiskClass.HIGH: 3,
    RiskClass.AUTH_BOUNDARY: 4,
    RiskClass.DESTRUCTIVE: 5,
}

DEFAULT_RISK: dict[ActionKind, RiskClass] = {
    ActionKind.NOOP: RiskClass.SAFE,
    ActionKind.WAIT_FOR: RiskClass.SAFE,
    ActionKind.MOUSE_MOVE: RiskClass.LOW,
    ActionKind.SCROLL: RiskClass.LOW,
    ActionKind.CLIPBOARD_GET: RiskClass.LOW,
    ActionKind.CLICK: RiskClass.MEDIUM,
    ActionKind.DOUBLE_CLICK: RiskClass.MEDIUM,
    ActionKind.RIGHT_CLICK: RiskClass.MEDIUM,
    ActionKind.TYPE_TEXT: RiskClass.MEDIUM,
    ActionKind.KEY_PRESS: RiskClass.MEDIUM,
    ActionKind.HOTKEY: RiskClass.MEDIUM,
    ActionKind.CLIPBOARD_SET: RiskClass.MEDIUM,
    ActionKind.FS_READ: RiskClass.MEDIUM,
    ActionKind.DRAG: RiskClass.HIGH,
    ActionKind.WINDOW_SWITCH: RiskClass.LOW,
    ActionKind.APP_LAUNCH: RiskClass.HIGH,  # launching an app requires confirmation
    ActionKind.FS_WRITE: RiskClass.MEDIUM,
    ActionKind.TERMINAL_RUN: RiskClass.MEDIUM,  # destructive commands escalate via markers
    # Browser control: reading is cheap; navigating/clicking/typing act on the
    # outside world; running arbitrary page JS is the most powerful, so it needs
    # explicit confirmation.
    ActionKind.BROWSER_QUERY: RiskClass.LOW,
    ActionKind.BROWSER_SCREENSHOT: RiskClass.LOW,
    ActionKind.BROWSER_TITLE: RiskClass.LOW,
    ActionKind.BROWSER_URL: RiskClass.LOW,
    ActionKind.BROWSER_NAVIGATE: RiskClass.MEDIUM,
    ActionKind.BROWSER_CLICK: RiskClass.MEDIUM,
    ActionKind.BROWSER_TYPE: RiskClass.MEDIUM,
    ActionKind.BROWSER_EVAL: RiskClass.HIGH,
}

INPUT_KINDS = {
    ActionKind.MOUSE_MOVE, ActionKind.CLICK, ActionKind.DOUBLE_CLICK,
    ActionKind.RIGHT_CLICK, ActionKind.DRAG, ActionKind.SCROLL,
    ActionKind.TYPE_TEXT, ActionKind.KEY_PRESS, ActionKind.HOTKEY,
    ActionKind.WINDOW_SWITCH,
}

# Textual markers that indicate an authentication boundary or destructive op.
_AUTH_MARKERS = re.compile(
    r"(?i)\b(sudo|pkexec|polkit|password|passwd|keyring|gnome-keyring|2fa|otp|"
    r"captcha|unlock|login|sign[\s-]?in|authenticate)\b")
_DESTRUCTIVE_MARKERS = re.compile(
    r"(?i)(\brm\s+-rf\b|\bmkfs\b|\bdd\s+if=|\bshred\b|:\(\)\s*\{|>\s*/dev/sd|"
    r"\bchmod\s+-R\s+777\b|\buserdel\b|\bwipefs\b)")


def classify(action: Action) -> RiskClass:
    """Classify an action's risk. Explicit high-risk markers escalate."""
    blob = " ".join(str(v) for v in (action.params or {}).values()) + " " + str(action.target or "")
    if _DESTRUCTIVE_MARKERS.search(blob):
        return RiskClass.DESTRUCTIVE
    if _AUTH_MARKERS.search(blob):
        return RiskClass.AUTH_BOUNDARY
    declared = action.risk
    default = DEFAULT_RISK.get(action.kind, RiskClass.MEDIUM)
    # Take the more severe of declared and default.
    return declared if _RANK.get(declared, 2) >= _RANK[default] else default


def max_risk_from_str(value: str) -> RiskClass:
    try:
        return RiskClass(value)
    except ValueError:
        return RiskClass.MEDIUM


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    risk: RiskClass
    requires_confirmation: bool = False
    simulated: bool = False  # run in dry-run (no real effect)
    escalate_to_user: bool = False


@dataclass
class Policy:
    max_risk: RiskClass = RiskClass.MEDIUM
    real_input_enabled: bool = False
    _approved: set[str] = field(default_factory=set)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    emergency_stopped: bool = False
    paused: bool = False
    user_takeover: bool = False

    # latches ---------------------------------------------------------------
    def emergency_stop(self) -> None:
        with self._lock:
            self.emergency_stopped = True

    def clear_emergency_stop(self) -> None:
        with self._lock:
            self.emergency_stopped = False

    def pause(self) -> None:
        with self._lock:
            self.paused = True

    def resume(self) -> None:
        with self._lock:
            self.paused = False

    def request_takeover(self) -> None:
        with self._lock:
            self.user_takeover = True

    def clear_takeover(self) -> None:
        with self._lock:
            self.user_takeover = False

    # approvals -------------------------------------------------------------
    def approve(self, action_id: str) -> None:
        with self._lock:
            self._approved.add(action_id)

    def revoke(self, action_id: str) -> None:
        with self._lock:
            self._approved.discard(action_id)

    def is_approved(self, action_id: str) -> bool:
        with self._lock:
            return action_id in self._approved

    # the gate --------------------------------------------------------------
    def check(self, action: Action) -> PolicyDecision:
        risk = classify(action)
        with self._lock:
            if self.emergency_stopped:
                return PolicyDecision(False, "emergency stop engaged", risk)
            if self.user_takeover:
                return PolicyDecision(False, "user takeover in progress", risk)
            if self.paused:
                return PolicyDecision(False, "paused", risk)

            if risk is RiskClass.AUTH_BOUNDARY:
                return PolicyDecision(
                    False, "authentication boundary: must be performed by the user",
                    risk, escalate_to_user=True)
            if _RANK[risk] > _RANK[self.max_risk]:
                if not self.is_approved(action.action_id):
                    return PolicyDecision(
                        False, f"risk {risk.value} exceeds max {self.max_risk.value}",
                        risk, requires_confirmation=True)
            if risk in (RiskClass.HIGH, RiskClass.DESTRUCTIVE) and not self.is_approved(action.action_id):
                return PolicyDecision(
                    False, f"{risk.value} action requires explicit confirmation",
                    risk, requires_confirmation=True)

            simulated = action.kind in INPUT_KINDS and not self.real_input_enabled
            return PolicyDecision(True, "allowed", risk, simulated=simulated)

    # untrusted-instruction gate -------------------------------------------
    def may_follow_instructions(self, trust: TrustLevel) -> bool:
        """Untrusted external content must never be executed as an instruction."""
        return trust in (TrustLevel.TRUSTED, TrustLevel.DERIVED)
