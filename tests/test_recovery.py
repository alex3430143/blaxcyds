from pathlib import Path

from blaxcy.models import ActionResult, ActionStatus
from blaxcy.recovery import (
    BUILD_STATE_FILES,
    AttemptLedger,
    FailureClass,
    RecoveryManager,
    Strategy,
    classify_result,
    read_build_state,
    reconcile,
)


def test_classify_result_variants():
    assert classify_result(ActionResult(action_id="a", status=ActionStatus.TIMEOUT)) is FailureClass.TIMEOUT
    assert classify_result(ActionResult(action_id="a", status=ActionStatus.FAILED)) is FailureClass.TRANSIENT
    blocked = ActionResult(action_id="a", status=ActionStatus.BLOCKED,
                           observed={"escalate_to_user": True})
    assert classify_result(blocked) is FailureClass.AUTH_BOUNDARY
    blocked2 = ActionResult(action_id="a", status=ActionStatus.BLOCKED)
    assert classify_result(blocked2) is FailureClass.BLOCKED
    ok = ActionResult(action_id="a", status=ActionStatus.SUCCEEDED)
    assert classify_result(ok, verified=False) is FailureClass.VERIFICATION


def test_attempt_ledger_tracks_and_limits():
    ledger = AttemptLedger(max_attempts=2)
    assert ledger.should_retry("sig")
    ledger.record("sig", FailureClass.TRANSIENT)
    assert ledger.should_retry("sig")
    ledger.record("sig", FailureClass.TRANSIENT)
    assert ledger.count("sig") == 2
    assert not ledger.should_retry("sig")
    ledger.reset("sig")
    assert ledger.should_retry("sig")


def test_recovery_strategy_chain_progresses_and_escalates():
    mgr = RecoveryManager(max_attempts=3)
    assert mgr.next_strategy("s", FailureClass.TRANSIENT) is Strategy.RETRY
    mgr.ledger.record("s", FailureClass.TRANSIENT)
    assert mgr.next_strategy("s", FailureClass.TRANSIENT) is Strategy.ALT_METHOD
    mgr.ledger.record("s", FailureClass.TRANSIENT)
    assert mgr.next_strategy("s", FailureClass.TRANSIENT) is Strategy.ALT_TOOL
    mgr.ledger.record("s", FailureClass.TRANSIENT)
    assert mgr.next_strategy("s", FailureClass.TRANSIENT) is Strategy.ESCALATE


def test_auth_boundary_and_verification_short_circuit():
    mgr = RecoveryManager()
    assert mgr.next_strategy("s", FailureClass.AUTH_BOUNDARY) is Strategy.ESCALATE
    assert mgr.next_strategy("s", FailureClass.VERIFICATION) is Strategy.REPLAN


def _seed_project(root: Path) -> None:
    bs = root / ".build-state"
    bs.mkdir(parents=True)
    for name in BUILD_STATE_FILES:
        (bs / name).write_text("x", encoding="utf-8")
    pkg = root / "blaxcy"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("", encoding="utf-8")


def test_reconcile_first_execution_when_empty(tmp_path):
    report = reconcile(tmp_path)
    assert report.mode == "first_execution"
    assert report.discrepancies
    assert "next_action" in report.to_dict()


def test_reconcile_recovery_when_work_present(tmp_path):
    _seed_project(tmp_path)
    report = reconcile(tmp_path)
    assert report.mode == "recovery"
    assert report.package_present
    assert report.tests_present == ["test_x.py"]
    assert not report.discrepancies


def test_reconcile_flags_claimed_missing_file(tmp_path):
    _seed_project(tmp_path)
    report = reconcile(tmp_path, claimed_files=["does/not/exist.py"])
    assert any("claimed file missing" in d for d in report.discrepancies)


def test_read_build_state(tmp_path):
    _seed_project(tmp_path)
    state = read_build_state(tmp_path)
    assert "STATE.md" in state and "manifest.json" not in state
