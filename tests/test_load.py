"""Smoke test for the repeatable load-test script (`scripts/loadtest.py`).

Runs the script's `run_load` at a tiny scale so the harness itself stays covered
in the normal suite. The full-scale run is on demand:

    python3 scripts/loadtest.py --threads 8 --per 40 --restart
"""

from __future__ import annotations

import importlib.util

from blaxcy.config import project_root


def _load_script():
    path = project_root() / "scripts" / "loadtest.py"
    spec = importlib.util.spec_from_file_location("blaxcy_loadtest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_loadtest_script_runs_and_preserves_integrity(tmp_path):
    module = _load_script()
    result = module.run_load(root=tmp_path / "loadroot", threads=2, per=5)

    assert set(result["startup_ms"]) == {"memory", "brain"}
    assert result["integrity"]["ok"] is True
    assert result["integrity"]["counted"] == result["integrity"]["expected_writes"]
    assert all(scenario["errors"] == 0 for scenario in result["scenarios"])
    # Every scenario measured something.
    assert all(scenario["calls"] > 0 for scenario in result["scenarios"])
