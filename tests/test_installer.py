"""Tests for the installer lifecycle (requirement N5).

The scripts run against a throwaway temp root via `--root`, so nothing real is
installed and no package index is contacted. Real deletion is exercised in a temp
directory only.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
UPGRADE = ROOT / "upgrade.sh"
UNINSTALL = ROOT / "uninstall.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True)


def make_root(tmp_path: Path, *, with_pyproject: bool = True) -> Path:
    (tmp_path / "blaxcy").mkdir(exist_ok=True)
    if with_pyproject:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "blaxcy"\nversion = "9.9.9"\n', encoding="utf-8")
    return tmp_path


def test_shell_scripts_are_syntactically_valid():
    for script in (INSTALL, UPGRADE, UNINSTALL):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_install_dry_run_changes_nothing(tmp_path):
    root = make_root(tmp_path)
    result = run(INSTALL, "--root", str(root), "--dry-run")
    assert result.returncode == 0
    assert "[dry-run]" in result.stdout
    assert "9.9.9" in result.stdout
    assert not (root / ".venv").exists()


def test_install_reports_version_and_plan(tmp_path):
    root = make_root(tmp_path)
    result = run(INSTALL, "--root", str(root), "--dry-run", "--no-venv")
    assert result.returncode == 0
    assert "--no-venv" in result.stdout


def test_install_rejects_unknown_option(tmp_path):
    result = run(INSTALL, "--root", str(tmp_path), "--nope")
    assert result.returncode == 2


def test_upgrade_dry_run_preserves_user_data(tmp_path):
    root = make_root(tmp_path)
    (root / ".runtime").mkdir()
    (root / ".build-state").mkdir()
    (root / ".runtime" / "memory.sqlite3").write_text("data", encoding="utf-8")
    result = run(UPGRADE, "--root", str(root), "--dry-run")
    assert result.returncode == 0
    assert "preserving .runtime" in result.stdout
    assert "preserving .build-state" in result.stdout
    assert (root / ".runtime" / "memory.sqlite3").read_text() == "data"


def test_upgrade_requires_a_project_root(tmp_path):
    result = run(UPGRADE, "--root", str(tmp_path), "--dry-run")
    assert result.returncode == 1


def test_uninstall_preview_removes_nothing(tmp_path):
    root = make_root(tmp_path)
    (root / ".venv").mkdir()
    (root / ".venv" / "bin").mkdir()
    result = run(UNINSTALL, "--root", str(root))
    assert result.returncode == 3
    assert (root / ".venv").exists()


def test_uninstall_yes_removes_artifacts_but_keeps_data(tmp_path):
    root = make_root(tmp_path)
    for name in (".venv", "blaxcy.egg-info", "build", ".runtime", ".build-state"):
        (root / name).mkdir()
    (root / "blaxcy" / "__pycache__").mkdir()

    result = run(UNINSTALL, "--root", str(root), "--yes")
    assert result.returncode == 0
    assert not (root / ".venv").exists()
    assert not (root / "blaxcy.egg-info").exists()
    assert not (root / "build").exists()
    assert not (root / "blaxcy" / "__pycache__").exists()
    # user data preserved without --purge
    assert (root / ".runtime").exists()
    assert (root / ".build-state").exists()


def test_uninstall_purge_removes_user_data(tmp_path):
    root = make_root(tmp_path)
    for name in (".runtime", ".build-state", "logs"):
        (root / name).mkdir()
    result = run(UNINSTALL, "--root", str(root), "--yes", "--purge")
    assert result.returncode == 0
    assert not (root / ".runtime").exists()
    assert not (root / ".build-state").exists()
    assert not (root / "logs").exists()


def test_full_lifecycle_dry_runs(tmp_path):
    """install → upgrade → uninstall preview all succeed against a temp root."""
    root = make_root(tmp_path)
    for script, extra in ((INSTALL, ("--dry-run",)), (UPGRADE, ("--dry-run",)),
                          (UNINSTALL, ("--dry-run",))):
        result = run(script, "--root", str(root), *extra)
        assert result.returncode == 0, result.stderr
