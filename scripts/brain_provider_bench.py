#!/usr/bin/env python3
"""Repeatable latency benchmark for the split Brain service, per provider.

Spawns the real ``blaxcy serve brain`` subprocess for a set of *provider profiles*,
each over an isolated ``BLAXCY_ROOT``, then drives it through the split
``RemoteBrain`` client over the authenticated IPC. For every call it records both
the wall-clock round trip (IPC + provider) and the router-measured provider
duration, and it reports **which model actually served each call** so a silent
fallback to a different provider can never be mistaken for the configured one.

Profiles are configured through the same environment variables the app uses, so
this measures the real code path, not a stub:

* ``offline`` — no provider configured, the deterministic offline fallback.
* ``local``  — a real HTTP provider on this host (Ollama's OpenAI-compatible
  ``/v1`` endpoint), selected by pointing ``BLAXCY_LOCAL_BASE_URL`` at it.
* ``remote`` — a genuinely remote OpenAI-compatible provider, configured with
  ``BLAXCY_OPENAI_API_KEY`` / ``BLAXCY_OPENAI_BASE_URL`` / ``BLAXCY_OPENAI_MODEL``
  (or a gitignored ``.env``). Any remote preset (openai/groq/openrouter/together/
  anthropic) works; the script only reports what the service actually used.

Examples::

    # Offline baseline only (no network, hermetic):
    python3 scripts/brain_provider_bench.py --profiles offline

    # Local real HTTP provider (Ollama /v1):
    python3 scripts/brain_provider_bench.py --profiles offline,local \
        --local-base-url http://127.0.0.1:11434/v1 --local-model tinyllama:latest

    # Genuinely remote provider:
    BLAXCY_OPENAI_API_KEY=... BLAXCY_OPENAI_BASE_URL=https://api.groq.com/openai/v1 \
    BLAXCY_OPENAI_MODEL=llama-3.3-70b-versatile \
        python3 scripts/brain_provider_bench.py --profiles offline,remote

Nothing here touches the real desktop or uses real input. The numbers are real
measurements for this host, not estimates.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Make `blaxcy` importable when run as a plain script from the repo.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blaxcy.brain.router import Need  # noqa: E402
from blaxcy.brain.service import RemoteBrain  # noqa: E402
from blaxcy.config import Settings, project_root  # noqa: E402
from blaxcy.service import (  # noqa: E402
    ProcessComponent,
    service_command,
    service_socket,
)

# Provider name (registry spec) each profile prefers. `prefer` only reorders the
# candidates; the observed `Completion.model` is what proves which one ran.
_PROFILE_PREFER = {"offline": "offline-deterministic", "local": "local",
                   "remote": "openai", "anthropic": "anthropic"}

DEFAULT_PROMPT = "Reply with the single word: PONG"


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _spawn_brain(settings: Settings, root: Path, extra_env: dict[str, str]) -> tuple[ProcessComponent, float]:
    env = {"BLAXCY_ROOT": str(root), "PYTHONPATH": str(project_root()), **extra_env}
    comp = ProcessComponent(
        "brain", service_command("brain"),
        socket_path=service_socket(settings, "brain"),
        secret=settings.ipc_secret(),
        env=env,
        cwd=str(project_root()), startup_timeout=60.0,
        log_path=Path(settings.runtime_dir) / "logs" / "brain-bench.log",
    )
    started = time.perf_counter()
    comp.start()
    return comp, (time.perf_counter() - started) * 1000.0


def _drive(threads: int, per: int, call) -> tuple[list[float], list[float], list[str], dict[str, int]]:
    """Run `call` `threads x per` times; return (wall_ms, provider_ms, errors, models)."""
    wall: list[float] = []
    provider: list[float] = []
    errors: list[str] = []
    models: dict[str, int] = {}
    lock = threading.Lock()

    def worker(_index: int) -> None:
        local_wall: list[float] = []
        local_provider: list[float] = []
        local_models: dict[str, int] = {}
        for j in range(per):
            t0 = time.perf_counter()
            try:
                completion = call(j)
                local_provider.append(float(completion.duration_s) * 1000.0)
                local_models[completion.model or "<none>"] = local_models.get(completion.model or "<none>", 0) + 1
                if not completion.ok:
                    with lock:
                        errors.append(f"not ok: {completion.error_kind} {completion.error}")
            except Exception as exc:  # noqa: BLE001 - record, do not abort the run
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}")
            local_wall.append((time.perf_counter() - t0) * 1000.0)
        with lock:
            wall.extend(local_wall)
            provider.extend(local_provider)
            for model, count in local_models.items():
                models[model] = models.get(model, 0) + count

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, range(threads)))
    return wall, provider, errors, models


def _summarise(wall: list[float], provider: list[float], errors: list[str],
               models: dict[str, int]) -> dict[str, Any]:
    return {
        "calls": len(wall),
        "errors": len(errors),
        "error_samples": errors[:3],
        "models": models,
        "wall_median_ms": round(statistics.median(wall), 3) if wall else 0.0,
        "wall_p95_ms": round(_pct(wall, 0.95), 3),
        "wall_min_ms": round(min(wall), 3) if wall else 0.0,
        "wall_max_ms": round(max(wall), 3) if wall else 0.0,
        "provider_median_ms": round(statistics.median(provider), 3) if provider else 0.0,
        "provider_p95_ms": round(_pct(provider, 0.95), 3),
    }


def _run_profile(profile: dict[str, Any], *, root: Path, seq: int, threads: int,
                 per: int, prompt: str) -> dict[str, Any]:
    name = profile["name"]
    prefer = profile["prefer"]
    settings = Settings(root=root / name)
    settings.ensure_dirs()
    comp, startup_ms = _spawn_brain(settings, settings.root, profile["env"])
    out: dict[str, Any] = {"profile": name, "prefer": prefer,
                           "env": sorted(profile["env"]), "startup_ms": round(startup_ms, 1)}
    try:
        brain = RemoteBrain(settings)
        out["status"] = [row for row in brain.status()]
        need = Need(capability="reasoning", prefer=prefer)

        # Warm up so the first call is not the outlier.
        warm = brain.complete(prompt, need)
        out["warmup"] = {"ok": warm.ok, "model": warm.model,
                         "error_kind": warm.error_kind.value if warm.error_kind else None}

        seq_wall: list[float] = []
        seq_provider: list[float] = []
        seq_models: dict[str, int] = {}
        seq_errors: list[str] = []
        for _ in range(max(1, seq)):
            t0 = time.perf_counter()
            try:
                completion = brain.complete(prompt, need)
                seq_provider.append(float(completion.duration_s) * 1000.0)
                seq_models[completion.model or "<none>"] = seq_models.get(completion.model or "<none>", 0) + 1
                if not completion.ok:
                    seq_errors.append(str(completion.error_kind))
            except Exception as exc:  # noqa: BLE001
                seq_errors.append(f"{type(exc).__name__}: {exc}")
            seq_wall.append((time.perf_counter() - t0) * 1000.0)

        wall, provider, errors, models = _drive(
            threads, per, lambda _j: brain.complete(prompt, need))
        out["sequential"] = _summarise(seq_wall, seq_provider, seq_errors, seq_models)
        out["concurrent"] = _summarise(wall, provider, errors, models)
        out["degraded_calls"] = brain.degraded_calls
        out["last_error"] = brain.last_error
    finally:
        comp.stop()
    return out


def run_bench(*, root: Path | None = None, profiles: list[dict[str, Any]] | None = None,
              seq: int = 8, threads: int = 4, per: int = 4,
              prompt: str = DEFAULT_PROMPT, keep: bool = False) -> dict[str, Any]:
    """Run the benchmark and return a structured result. Spawns real services."""
    created = root is None
    root = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="blaxcy-brainbench-"))
    root.mkdir(parents=True, exist_ok=True)
    profiles = profiles or [{"name": "offline", "prefer": "offline-deterministic", "env": {}}]
    result: dict[str, Any] = {"root": str(root), "seq": seq, "threads": threads,
                              "per": per, "prompt": prompt, "profiles": []}
    try:
        for profile in profiles:
            result["profiles"].append(
                _run_profile(profile, root=root, seq=seq, threads=threads, per=per,
                             prompt=prompt))
    finally:
        if created and not keep:
            shutil.rmtree(root, ignore_errors=True)
    return result


def _profile_from_args(args: argparse.Namespace, name: str) -> dict[str, Any] | None:
    if name == "offline":
        return {"name": "offline", "prefer": _PROFILE_PREFER["offline"], "env": {}}
    if name == "local":
        base = args.local_base_url or os.environ.get("BLAXCY_LOCAL_BASE_URL", "")
        if not base:
            base = "http://127.0.0.1:11434/v1"  # Ollama's OpenAI-compatible path
        model = args.local_model or os.environ.get("BLAXCY_LOCAL_MODEL", "")
        env = {"BLAXCY_LOCAL_BASE_URL": base}
        if model:
            env["BLAXCY_LOCAL_MODEL"] = model
        return {"name": "local", "prefer": _PROFILE_PREFER["local"], "env": env}
    if name == "remote":
        key = args.remote_key or os.environ.get("BLAXCY_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
        base = args.remote_base_url or os.environ.get("BLAXCY_OPENAI_BASE_URL", "")
        model = args.remote_model or os.environ.get("BLAXCY_OPENAI_MODEL", "")
        if not (key and base):
            return None
        env = {"BLAXCY_OPENAI_API_KEY": key, "BLAXCY_OPENAI_BASE_URL": base}
        if model:
            env["BLAXCY_OPENAI_MODEL"] = model
        return {"name": "remote", "prefer": _PROFILE_PREFER["remote"], "env": env}
    return None


def _print_human(result: dict[str, Any]) -> None:
    print(f"BLAXCY Brain provider latency bench  (root={result['root']})")
    print(f"prompt: {result['prompt']!r}   seq={result['seq']}  "
          f"concurrent={result['threads']}x{result['per']}")
    print()
    for prof in result["profiles"]:
        print(f"--- profile: {prof['profile']}  (prefer={prof['prefer']}, "
              f"startup={prof['startup_ms']} ms) ---")
        print(f"    providers: " + ", ".join(
            f"{row['name']}{'(local)' if row['local'] else ''}"
            f"{'' if row['available'] else ' [unavailable]'}" for row in prof["status"]))
        for label in ("sequential", "concurrent"):
            s = prof[label]
            models = ", ".join(f"{m}×{c}" for m, c in sorted(s["models"].items()))
            print(f"    {label:<11} n={s['calls']:<4} err={s['errors']:<3} "
                  f"wall med={s['wall_median_ms']:>9.3f} p95={s['wall_p95_ms']:>9.3f} "
                  f"min={s['wall_min_ms']:>8.3f} max={s['wall_max_ms']:>9.3f} ms  "
                  f"| provider med={s['provider_median_ms']:>9.3f} ms  "
                  f"| served by: {models}")
            for sample in s["error_samples"]:
                print(f"        error: {sample}")
        print()
    # The headline comparison: sequential wall and provider medians per profile.
    print("Latency difference (sequential, median wall / provider ms):")
    for prof in result["profiles"]:
        s = prof["sequential"]
        print(f"    {prof['profile']:<8} wall={s['wall_median_ms']:>9.3f}  "
              f"provider={s['provider_median_ms']:>9.3f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark Brain latency per provider.")
    parser.add_argument("--profiles", default="offline",
                        help="comma list: offline,local,remote (default: offline)")
    parser.add_argument("--seq", type=int, default=8, help="sequential calls per profile")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--per", type=int, default=4, help="calls per thread")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--root", default=None, help="runtime root (default: temp dir)")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--local-base-url", default=None)
    parser.add_argument("--local-model", default=None)
    parser.add_argument("--remote-base-url", default=None)
    parser.add_argument("--remote-model", default=None)
    parser.add_argument("--remote-key", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    requested = [p.strip().lower() for p in args.profiles.split(",") if p.strip()]
    profiles: list[dict[str, Any]] = []
    for name in requested:
        built = _profile_from_args(args, name)
        if built is None:
            if name == "remote":
                print("skip 'remote': set BLAXCY_OPENAI_API_KEY + "
                      "BLAXCY_OPENAI_BASE_URL (or --remote-key/--remote-base-url)",
                      file=sys.stderr)
            else:
                print(f"skip unknown profile {name!r}", file=sys.stderr)
            continue
        profiles.append(built)
    if not profiles:
        print("no profiles to run", file=sys.stderr)
        return 2

    result = run_bench(root=Path(args.root) if args.root else None,
                       profiles=profiles, seq=args.seq, threads=args.threads,
                       per=args.per, prompt=args.prompt, keep=args.keep)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)

    bad = False
    for prof in result["profiles"]:
        expected_served = prof["sequential"]["models"].get(prof["prefer"], 0)
        if prof["sequential"]["models"] and expected_served == 0:
            # Configured provider never served a call in the sequential pass.
            bad = True
        if prof["sequential"]["errors"] or prof["concurrent"]["errors"]:
            bad = True
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
