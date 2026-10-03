"""Smoke test for the provider latency bench (`scripts/brain_provider_bench.py`).

Runs only the **offline** profile at a tiny scale so the harness stays covered in
the normal suite without any network I/O. The real provider measurements are on
demand:

    BLAXCY_OPENAI_API_KEY=... BLAXCY_OPENAI_BASE_URL=... \\
        python3 scripts/brain_provider_bench.py --profiles offline,local,remote
"""

from __future__ import annotations

import importlib.util
import os

from blaxcy.config import project_root


def _load_script():
    path = project_root() / "scripts" / "brain_provider_bench.py"
    spec = importlib.util.spec_from_file_location("blaxcy_brain_bench", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_brain_provider_bench_offline_profile(tmp_path):
    module = _load_script()
    result = module.run_bench(root=tmp_path / "benchroot", seq=3, threads=2, per=2)

    assert [p["profile"] for p in result["profiles"]] == ["offline"]
    prof = result["profiles"][0]
    assert prof["startup_ms"] > 0
    # The configured (preferred) provider actually served every call.
    assert prof["sequential"]["models"] == {"offline-deterministic": 3}
    assert prof["concurrent"]["models"] == {"offline-deterministic": 4}
    assert prof["sequential"]["calls"] == 3 and prof["concurrent"]["calls"] == 4
    assert prof["sequential"]["errors"] == 0 and prof["concurrent"]["errors"] == 0
    names = {row["name"] for row in prof["status"]}
    assert "offline-deterministic" in names


class _Args:
    local_base_url = None
    local_model = None
    remote_base_url = None
    remote_model = None
    remote_key = None


def test_brain_provider_bench_remote_profile_requires_config(monkeypatch):
    module = _load_script()
    for var in ("BLAXCY_OPENAI_API_KEY", "OPENAI_API_KEY", "BLAXCY_OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    # Without a key/base URL the remote profile is skipped, never faked.
    assert module._profile_from_args(_Args(), "remote") is None
    # Offline always builds.
    assert module._profile_from_args(_Args(), "offline")["prefer"] == "offline-deterministic"
