"""Failure recovery and universal resume.

Two responsibilities:

1. **Runtime recovery** — when an action fails, classify it and choose the next
   strategy (retry, alternative method/tool/model, rollback, replan, escalate),
   never repeating the same failing action forever.

2. **Resume/reconcile** — implement the master protocol
   LOCATE → READ BUILD STATE → INSPECT FILESYSTEM → VERIFY → RECONCILE → CONTINUE,
   so any agent can pick the project up from the filesystem alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .models import ActionResult, ActionStatus
from .state_store import StateStore

BUILD_STATE_FILES = [
    "STATE.md", "REQUIREMENTS.md", "PLAN.md", "DECISIONS.md",
    "CHECKPOINT.md", "TESTS.md", "BLOCKERS.md", "ENVIRONMENT.md", "manifest.json",
]


# --------------------------------------------------------------------------- #
# Runtime recovery
# --------------------------------------------------------------------------- #
class FailureClass(str, Enum):
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    AUTH_BOUNDARY = "auth_boundary"
    VERIFICATION = "verification"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class Strategy(str, Enum):
    RETRY = "retry"
    ALT_METHOD = "alt_method"
    ALT_TOOL = "alt_tool"
    ALT_MODEL = "alt_model"
    ROLLBACK = "rollback"
    REPLAN = "replan"
    ESCALATE = "escalate"
    STOP = "stop"


def classify_result(result: ActionResult | None, *, verified: bool | None = None,
                    error: str | None = None) -> FailureClass:
    if error and "capab" in error.lower():
        return FailureClass.PERMANENT
    if result is None:
        return FailureClass.TRANSIENT if not error else FailureClass.UNKNOWN
    if result.status is ActionStatus.BLOCKED:
        if result.observed.get("escalate_to_user"):
            return FailureClass.AUTH_BOUNDARY
        return FailureClass.BLOCKED
    if result.status is ActionStatus.TIMEOUT:
        return FailureClass.TIMEOUT
    if result.status is ActionStatus.FAILED:
        return FailureClass.TRANSIENT
    if verified is False:
        return FailureClass.VERIFICATION
    return FailureClass.UNKNOWN


@dataclass
class Attempt:
    signature: str
    count: int = 0
    last: FailureClass | None = None


class AttemptLedger:
    """Tracks how many times a given action signature has been tried, so the
    loop never endlessly repeats the same failed action."""

    def __init__(self, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts
        self._attempts: dict[str, Attempt] = {}

    def record(self, signature: str, failure: FailureClass | None = None) -> Attempt:
        attempt = self._attempts.setdefault(signature, Attempt(signature=signature))
        attempt.count += 1
        attempt.last = failure
        return attempt

    def count(self, signature: str) -> int:
        return self._attempts.get(signature, Attempt(signature)).count

    def should_retry(self, signature: str) -> bool:
        return self.count(signature) < self.max_attempts

    def reset(self, signature: str) -> None:
        self._attempts.pop(signature, None)


class RecoveryManager:
    """Chooses the next strategy for a failing action signature."""

    _CHAIN = [Strategy.RETRY, Strategy.ALT_METHOD, Strategy.ALT_TOOL,
              Strategy.ALT_MODEL, Strategy.REPLAN, Strategy.ESCALATE]

    def __init__(self, max_attempts: int = 3) -> None:
        self.ledger = AttemptLedger(max_attempts=max_attempts)

    def next_strategy(self, signature: str, failure: FailureClass) -> Strategy:
        if failure in (FailureClass.AUTH_BOUNDARY, FailureClass.BLOCKED):
            return Strategy.ESCALATE
        if failure is FailureClass.VERIFICATION:
            return Strategy.REPLAN
        if failure is FailureClass.PERMANENT:
            return Strategy.ESCALATE
        attempts = self.ledger.count(signature)
        if attempts >= self.ledger.max_attempts:
            return Strategy.ESCALATE
        return self._CHAIN[min(attempts, len(self._CHAIN) - 1)]


# --------------------------------------------------------------------------- #
# Universal resume / reconcile
# --------------------------------------------------------------------------- #
@dataclass
class ResumeReport:
    root: str
    exists: bool
    build_state_present: dict[str, bool] = field(default_factory=dict)
    package_present: bool = False
    modules: list[str] = field(default_factory=list)
    tests_present: list[str] = field(default_factory=list)
    last_checkpoint: dict | None = None
    interrupted_tasks: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)
    next_action: str = ""
    mode: str = "first_execution"

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def reconcile(root: str | Path, *, claimed_files: list[str] | None = None) -> ResumeReport:
    """Compare saved claims against the real filesystem. Reality wins."""
    root = Path(root)
    report = ResumeReport(root=str(root), exists=root.exists())
    if not report.exists:
        report.discrepancies.append("project root does not exist")
        report.next_action = f"create project root {root} and initialize .build-state/"
        return report

    bs = root / ".build-state"
    report.build_state_present = {name: (bs / name).exists() for name in BUILD_STATE_FILES}
    missing_bs = [n for n, ok in report.build_state_present.items() if not ok]
    if missing_bs:
        report.discrepancies.append(f"missing build-state files: {', '.join(missing_bs)}")

    pkg = root / "blaxcy"
    report.package_present = pkg.is_dir() and (pkg / "__init__.py").exists()
    if report.package_present:
        report.modules = sorted(str(p.relative_to(root))
                                for p in pkg.rglob("*.py") if "__pycache__" not in str(p))
    else:
        report.discrepancies.append("package blaxcy/ not found")

    tests = root / "tests"
    if tests.is_dir():
        report.tests_present = sorted(p.name for p in tests.glob("test_*.py"))
    if not report.tests_present:
        report.discrepancies.append("no tests found")

    for claimed in (claimed_files or []):
        if not (root / claimed).exists():
            report.discrepancies.append(f"claimed file missing: {claimed}")

    store_path = root / ".runtime" / "state" / "state.json"
    if store_path.exists():
        store = StateStore(store_path)
        report.interrupted_tasks = store.mark_interrupted()
        report.last_checkpoint = store.last_checkpoint()

    has_work = report.package_present or any(report.build_state_present.values())
    report.mode = "recovery" if has_work else "first_execution"
    if report.discrepancies:
        report.next_action = "reconcile discrepancies: " + "; ".join(report.discrepancies[:3])
    elif report.interrupted_tasks:
        report.next_action = ("resume interrupted task(s): "
                              + ", ".join(report.interrupted_tasks)
                              + " (verify whether each already completed before retrying)")
    else:
        report.next_action = "read .build-state/PLAN.md 'Exact next actions' and continue"
    return report


def read_build_state(root: str | Path) -> dict[str, str]:
    """Read every present `.build-state/` text file (for a resuming agent)."""
    bs = Path(root) / ".build-state"
    out: dict[str, str] = {}
    for name in BUILD_STATE_FILES:
        path = bs / name
        if path.exists() and path.suffix == ".md":
            try:
                out[name] = path.read_text(encoding="utf-8")
            except OSError:
                continue
    return out
