"""Typed, versioned domain contracts.

Everything that crosses a component boundary (Eye, Body, Brain, Memory, Policy,
Orchestrator, IPC) is expressed as a dataclass here. They are plain dataclasses
(no third-party dependency) and are JSON-serializable so components can run
in-process now and split into separate processes later without a redesign.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# Bump when the wire shape of IPCMessage or the core contracts changes.
# v2: the HMAC also covers `ts` (freshness is authenticated) and the server
# enforces a freshness window plus replay rejection.
IPC_VERSION = 2


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class RiskClass(str, Enum):
    """How dangerous an action is; drives Policy approval."""

    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    AUTH_BOUNDARY = "auth_boundary"  # lock screen, sudo, keyring, 2FA, CAPTCHA
    DESTRUCTIVE = "destructive"


class ActionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"  # refused by policy / emergency stop / not approved
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    DRY_RUN = "dry_run"  # simulated, no real effect


class ActionKind(str, Enum):
    MOUSE_MOVE = "mouse_move"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    DRAG = "drag"
    SCROLL = "scroll"
    TYPE_TEXT = "type_text"
    KEY_PRESS = "key_press"
    HOTKEY = "hotkey"
    WINDOW_SWITCH = "window_switch"
    APP_LAUNCH = "app_launch"
    CLIPBOARD_SET = "clipboard_set"
    CLIPBOARD_GET = "clipboard_get"
    WAIT_FOR = "wait_for"
    TERMINAL_RUN = "terminal_run"
    FS_READ = "fs_read"
    FS_WRITE = "fs_write"
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_EVAL = "browser_eval"
    BROWSER_QUERY = "browser_query"
    BROWSER_CLICK = "browser_click"
    BROWSER_TYPE = "browser_type"
    BROWSER_SCREENSHOT = "browser_screenshot"
    BROWSER_TITLE = "browser_title"
    BROWSER_URL = "browser_url"
    NOOP = "noop"


class TrustLevel(str, Enum):
    """Provenance trust for memory/inputs. Untrusted content is never promoted
    to trusted instructions automatically."""

    TRUSTED = "trusted"  # user / system
    DERIVED = "derived"  # produced by BLAXCY's own reasoning
    UNTRUSTED = "untrusted"  # web pages, files, third-party tool output


class ObjectiveStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    VERIFIED = "verified"
    FAILED = "failed"
    ABANDONED = "abandoned"


class ComponentState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Serialization helpers
# --------------------------------------------------------------------------- #
def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"not JSON serializable: {type(obj)!r}")


def dumps(obj: Any) -> str:
    """JSON-encode a dataclass/enum tree deterministically."""
    return json.dumps(obj, default=_json_default, separators=(",", ":"), sort_keys=True)


def loads(raw: str) -> Any:
    return json.loads(raw)


def to_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)


def _enum(cls: type[Enum], value: Any, default: Any = None) -> Any:
    if isinstance(value, cls):
        return value
    if value is None:
        return default
    return cls(value)


# --------------------------------------------------------------------------- #
# Screen / perception
# --------------------------------------------------------------------------- #
@dataclass
class MonitorInfo:
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MonitorInfo":
        return cls(**d)


@dataclass
class WindowInfo:
    window_id: str
    title: str = ""
    app: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    pid: int = 0
    focused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WindowInfo":
        return cls(
            window_id=d["window_id"],
            title=d.get("title", ""),
            app=d.get("app", ""),
            x=d.get("x", 0),
            y=d.get("y", 0),
            width=d.get("width", 0),
            height=d.get("height", 0),
            pid=d.get("pid", 0),
            focused=d.get("focused", False),
        )


@dataclass
class ScreenState:
    """A timestamped snapshot of the real desktop.

    `frame_bytes` is deliberately excluded from serialization: frames are not
    persisted by default.
    """

    timestamp: float
    width: int
    height: int
    sequence: int = 0
    monitors: list[MonitorInfo] = field(default_factory=list)
    windows: list[WindowInfo] = field(default_factory=list)
    active_window_id: str | None = None
    cursor: tuple[int, int] | None = None
    frame_hash: str = ""
    changed: bool = True
    changed_ratio: float = 1.0
    source: str = "unknown"
    confidence: float = 1.0
    accessibility: dict[str, Any] = field(default_factory=dict)
    frame_bytes: bytes | None = field(default=None, repr=False, compare=False)

    # freshness -------------------------------------------------------------
    def age(self, now: float | None = None) -> float:
        return (now if now is not None else time.time()) - self.timestamp

    def is_fresh(self, max_age_s: float, now: float | None = None) -> bool:
        return self.age(now) <= max_age_s

    def active_window(self) -> WindowInfo | None:
        for w in self.windows:
            if self.active_window_id and w.window_id == self.active_window_id:
                return w
        return None

    def to_dict(self, include_frame: bool = False) -> dict[str, Any]:
        d = {
            "timestamp": self.timestamp,
            "width": self.width,
            "height": self.height,
            "sequence": self.sequence,
            "monitors": [m.to_dict() for m in self.monitors],
            "windows": [w.to_dict() for w in self.windows],
            "active_window_id": self.active_window_id,
            "cursor": list(self.cursor) if self.cursor else None,
            "frame_hash": self.frame_hash,
            "changed": self.changed,
            "changed_ratio": self.changed_ratio,
            "source": self.source,
            "confidence": self.confidence,
            "accessibility": self.accessibility,
        }
        if include_frame and self.frame_bytes is not None:
            import base64

            d["frame_bytes_b64"] = base64.b64encode(self.frame_bytes).decode("ascii")
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScreenState":
        cursor = d.get("cursor")
        return cls(
            timestamp=d["timestamp"],
            width=d["width"],
            height=d["height"],
            sequence=d.get("sequence", 0),
            monitors=[MonitorInfo.from_dict(m) for m in d.get("monitors", [])],
            windows=[WindowInfo.from_dict(w) for w in d.get("windows", [])],
            active_window_id=d.get("active_window_id"),
            cursor=tuple(cursor) if cursor else None,
            frame_hash=d.get("frame_hash", ""),
            changed=d.get("changed", True),
            changed_ratio=d.get("changed_ratio", 1.0),
            source=d.get("source", "unknown"),
            confidence=d.get("confidence", 1.0),
            accessibility=d.get("accessibility", {}) or {},
        )


# --------------------------------------------------------------------------- #
# Actions / results
# --------------------------------------------------------------------------- #
@dataclass
class Action:
    kind: ActionKind
    params: dict[str, Any] = field(default_factory=dict)
    target: str | None = None
    expected_postcondition: dict[str, Any] | None = None
    timeout_s: float = 10.0
    risk: RiskClass = RiskClass.SAFE
    correlation_id: str = ""
    action_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["risk"] = self.risk.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Action":
        return cls(
            kind=ActionKind(d["kind"]),
            params=d.get("params", {}),
            target=d.get("target"),
            expected_postcondition=d.get("expected_postcondition"),
            timeout_s=d.get("timeout_s", 10.0),
            risk=_enum(RiskClass, d.get("risk"), RiskClass.SAFE),
            correlation_id=d.get("correlation_id", ""),
            action_id=d.get("action_id", uuid.uuid4().hex),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class ActionResult:
    action_id: str
    status: ActionStatus
    correlation_id: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    output: Any = None
    error: str | None = None
    backend: str = ""
    observed: dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (ActionStatus.SUCCEEDED, ActionStatus.DRY_RUN)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionResult":
        return cls(
            action_id=d["action_id"],
            status=ActionStatus(d["status"]),
            correlation_id=d.get("correlation_id", ""),
            started_at=d.get("started_at", 0.0),
            finished_at=d.get("finished_at", 0.0),
            output=d.get("output"),
            error=d.get("error"),
            backend=d.get("backend", ""),
            observed=d.get("observed", {}),
            verified=d.get("verified", False),
            detail=d.get("detail", ""),
        )


# --------------------------------------------------------------------------- #
# Goals / objectives / plans
# --------------------------------------------------------------------------- #
@dataclass
class Objective:
    goal: str
    objective_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    priorities: list[str] = field(default_factory=list)
    max_risk: RiskClass = RiskClass.MEDIUM
    budget: dict[str, Any] = field(default_factory=lambda: {"max_steps": 50, "max_seconds": 1800})
    stopping_conditions: list[str] = field(default_factory=list)
    status: ObjectiveStatus = ObjectiveStatus.PENDING
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["max_risk"] = self.max_risk.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Objective":
        return cls(
            goal=d["goal"],
            objective_id=d.get("objective_id", uuid.uuid4().hex),
            constraints=d.get("constraints", []),
            success_criteria=d.get("success_criteria", []),
            priorities=d.get("priorities", []),
            max_risk=_enum(RiskClass, d.get("max_risk"), RiskClass.MEDIUM),
            budget=d.get("budget", {"max_steps": 50, "max_seconds": 1800}),
            stopping_conditions=d.get("stopping_conditions", []),
            status=_enum(ObjectiveStatus, d.get("status"), ObjectiveStatus.PENDING),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class PlanStep:
    step_id: str
    description: str
    actions: list[Action] = field(default_factory=list)
    verify: dict[str, Any] | None = None
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "actions": [a.to_dict() for a in self.actions],
            "verify": self.verify,
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PlanStep":
        return cls(
            step_id=d["step_id"],
            description=d["description"],
            actions=[Action.from_dict(a) for a in d.get("actions", [])],
            verify=d.get("verify"),
            optional=d.get("optional", False),
        )


@dataclass
class Plan:
    objective_id: str
    steps: list[PlanStep] = field(default_factory=list)
    revision: int = 1
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "steps": [s.to_dict() for s in self.steps],
            "revision": self.revision,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Plan":
        return cls(
            objective_id=d["objective_id"],
            steps=[PlanStep.from_dict(s) for s in d.get("steps", [])],
            revision=d.get("revision", 1),
            created_at=d.get("created_at", time.time()),
        )


@dataclass
class VerificationResult:
    ok: bool
    criterion: str = ""
    detail: str = ""
    observed: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VerificationResult":
        return cls(**d)


@dataclass
class MemoryRecord:
    content: str
    kind: str = "experience"  # experience | lesson | preference | environment | tool
    source: str = "blaxcy"
    trust: TrustLevel = TrustLevel.DERIVED
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["trust"] = self.trust.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryRecord":
        return cls(
            content=d["content"],
            kind=d.get("kind", "experience"),
            source=d.get("source", "blaxcy"),
            trust=_enum(TrustLevel, d.get("trust"), TrustLevel.DERIVED),
            confidence=float(d.get("confidence", 0.5)),
            tags=list(d.get("tags", [])),
            record_id=d.get("record_id", uuid.uuid4().hex),
            created_at=d.get("created_at", time.time()),
            expires_at=d.get("expires_at"),
        )


# --------------------------------------------------------------------------- #
# IPC
# --------------------------------------------------------------------------- #
@dataclass
class IPCMessage:
    """One line of the newline-delimited JSON IPC protocol."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = IPC_VERSION
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: str = ""
    token: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "IPCMessage":
        return cls(
            type=d["type"],
            payload=d.get("payload", {}),
            version=d.get("version", 0),
            message_id=d.get("message_id", uuid.uuid4().hex),
            correlation_id=d.get("correlation_id", ""),
            token=d.get("token", ""),
            ts=d.get("ts", time.time()),
        )

    def to_json(self) -> str:
        return dumps(self.to_dict())

    @classmethod
    def from_json(cls, raw: str) -> "IPCMessage":
        return cls.from_dict(loads(raw))
