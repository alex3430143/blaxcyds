#!/usr/bin/env python3
"""Repeatable load test for the split services (Memory + Brain).

Spawns the real `blaxcy serve memory` / `blaxcy serve brain` subprocesses over an
isolated `BLAXCY_ROOT`, then drives them with configurable concurrency and prints
latency (median/p95/p99/max), throughput and error counts — plus an integrity
check that no write was lost. Optionally also crashes the Memory service while
under load to measure restart-under-load behaviour.

Run it directly:

    python3 scripts/loadtest.py                 # defaults: 8 threads x 40 calls
    python3 scripts/loadtest.py --threads 4 --per 100 --json
    python3 scripts/loadtest.py --restart       # include restart-under-load

Nothing here touches the real desktop or uses real input. The numbers are real
measurements for this host, not estimates.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Make `blaxcy` importable when run as a plain script from the repo.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blaxcy.brain.router import Need  # noqa: E402
from blaxcy.brain.service import RemoteBrain  # noqa: E402
from blaxcy.config import Settings, project_root  # noqa: E402
from blaxcy.memory import RemoteMemory  # noqa: E402
from blaxcy.service import (  # noqa: E402
    ProcessComponent,
    service_command,
    service_socket,
)
from blaxcy.supervisor import Supervisor  # noqa: E402


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _spawn(settings: Settings, name: str, root: Path) -> tuple[ProcessComponent, float]:
    comp = ProcessComponent(
        name, service_command(name),
        socket_path=service_socket(settings, name),
        secret=settings.ipc_secret(),
        env={"BLAXCY_ROOT": str(root), "PYTHONPATH": str(project_root())},
        cwd=str(project_root()), startup_timeout=40.0,
        log_path=Path(settings.runtime_dir) / "logs" / f"{name}-loadtest.log",
    )
    started = time.perf_counter()
    comp.start()
    return comp, (time.perf_counter() - started) * 1000.0


def _drive(threads: int, per: int,
           fn: Callable[[int, int], Any]) -> tuple[list[float], list[str], float]:
    latencies: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        local: list[float] = []
        for j in range(per):
            t0 = time.perf_counter()
            try:
                fn(index, j)
            except Exception as exc:  # noqa: BLE001 - count it, do not abort the run
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}")
            local.append((time.perf_counter() - t0) * 1000.0)
        with lock:
            latencies.extend(local)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, range(threads)))
    return latencies, errors, time.perf_counter() - started


def _summarise(tag: str, n: int, per: int, lat: list[float], errors: list[str],
               wall: float) -> dict[str, Any]:
    return {
        "scenario": tag,
        "calls": n * per,
        "errors": len(errors),
        "error_samples": errors[:3],
        "median_ms": round(statistics.median(lat), 3) if lat else 0.0,
        "p95_ms": round(_pct(lat, 0.95), 3),
        "p99_ms": round(_pct(lat, 0.99), 3),
        "max_ms": round(max(lat), 3) if lat else 0.0,
        "throughput_per_s": round((n * per) / wall, 1) if wall else 0.0,
    }


def run_load(*, root: Path | None = None, threads: int = 8, per: int = 40,
             restart: bool = False, keep: bool = False) -> dict[str, Any]:
    """Run the load test and return a structured result. Spawns real services."""
    created = root is None
    root = Path(root) if root is not None else Path(tempfile.mkdtemp(prefix="blaxcy-load-"))
    root.mkdir(parents=True, exist_ok=True)
    settings = Settings(root=root)
    settings.ensure_dirs()

    mem = brain = None
    result: dict[str, Any] = {"root": str(root), "threads": threads, "per": per,
                              "scenarios": [], "startup_ms": {}, "integrity": {}}
    try:
        mem, mem_startup = _spawn(settings, "memory", root)
        brain, brain_startup = _spawn(settings, "brain", root)
        result["startup_ms"] = {"memory": round(mem_startup, 1),
                                "brain": round(brain_startup, 1)}
        remote_memory = RemoteMemory(settings)
        remote_brain = RemoteBrain(settings)
        need = Need(capability="reasoning", prefer="offline-deterministic")

        # Warm up so the first call is not the outlier.
        remote_memory.add("warmup")
        remote_brain.complete("warmup", need)

        seq_lat = []
        for j in range(max(20, per)):
            t0 = time.perf_counter()
            remote_memory.add(f"seq-{j}")
            seq_lat.append((time.perf_counter() - t0) * 1000.0)
        result["scenarios"].append(_summarise("memory add sequential", len(seq_lat), 1,
                                              seq_lat, [], 1.0))

        lat, errs, wall = _drive(threads, per,
                                 lambda i, j: remote_memory.add(f"w{i}-{j}", kind="lesson"))
        result["scenarios"].append(_summarise(f"memory add {threads}x{per}", threads, per,
                                              lat, errs, wall))

        lat, errs, wall = _drive(threads, per, lambda i, j: (
            remote_memory.add(f"m{i}-{j}") if j % 2 else remote_memory.query(limit=5)))
        result["scenarios"].append(_summarise(f"memory mixed rw {threads}x{per}", threads,
                                              per, lat, errs, wall))

        lat, errs, wall = _drive(threads, per, lambda i, j: remote_brain.complete("bench", need))
        result["scenarios"].append(_summarise(f"brain complete {threads}x{per}", threads, per,
                                              lat, errs, wall))

        def _both(i: int, j: int) -> None:
            remote_memory.add(f"b{i}-{j}")
            remote_brain.complete("bench", need)

        lat, errs, wall = _drive(max(2, threads // 2), per,
                                 _both)
        result["scenarios"].append(_summarise(f"memory+brain {max(2, threads // 2)}x{per}",
                                              max(2, threads // 2), per, lat, errs, wall))

        expected = 1 + len(seq_lat) + threads * per + sum(
            1 for i in range(threads) for j in range(per) if j % 2) + max(2, threads // 2) * per
        counted = remote_memory.count()
        result["integrity"] = {"expected_writes": expected, "counted": counted,
                              "ok": counted == expected}

        if restart:
            result["restart_under_load"] = _restart_under_load(settings, mem, remote_memory)
    finally:
        if mem is not None:
            mem.stop()
        if brain is not None:
            brain.stop()
        if created and not keep:
            shutil.rmtree(root, ignore_errors=True)
    return result


def _restart_under_load(settings: Settings, mem: ProcessComponent,
                        remote_memory: RemoteMemory, seconds: float = 3.5) -> dict[str, Any]:
    class Body:
        releases = 0

        def panic_release(self) -> None:
            Body.releases += 1

    sup = Supervisor(body=Body(), max_restarts=5)
    sup.register_process(mem)
    sup.start_all()
    sup.start_monitor(interval_s=0.5)

    stop = threading.Event()
    failures: list[str] = []
    successes = [0]
    lock = threading.Lock()

    def hammer() -> None:
        while not stop.is_set():
            try:
                remote_memory.add("live")
                with lock:
                    successes[0] += 1
            except Exception as exc:  # noqa: BLE001
                with lock:
                    failures.append(type(exc).__name__)
            time.sleep(0.004)

    workers = [threading.Thread(target=hammer, daemon=True) for _ in range(6)]
    for worker in workers:
        worker.start()
    time.sleep(0.7)
    old_pid = mem.pid
    os.kill(old_pid, signal.SIGKILL)
    time.sleep(seconds)
    stop.set()
    for worker in workers:
        worker.join(timeout=2)

    health = sup.health()["memory"]
    outcome = {
        "old_pid": old_pid, "new_pid": mem.pid, "running": mem.is_running(),
        "failures_during_gap": len(failures), "successes": successes[0],
        "safe_releases": Body.releases, "state": health["state"],
        "restarts": health["restarts"],
    }
    sup.stop_monitor()
    sup.stop_all()
    return outcome


def _print_human(result: dict[str, Any]) -> None:
    print(f"BLAXCY split-service load test  (root={result['root']})")
    print(f"startup ms: {result['startup_ms']}")
    print()
    header = f"{'scenario':<28} {'calls':>6} {'err':>4} {'median':>9} {'p95':>9} {'p99':>9} {'max':>9} {'thr/s':>9}"
    print(header)
    print("-" * len(header))
    for s in result["scenarios"]:
        print(f"{s['scenario']:<28} {s['calls']:>6} {s['errors']:>4} "
              f"{s['median_ms']:>9.3f} {s['p95_ms']:>9.3f} {s['p99_ms']:>9.3f} "
              f"{s['max_ms']:>9.3f} {s['throughput_per_s']:>9.1f}")
        for sample in s["error_samples"]:
            print(f"    error: {sample}")
    integrity = result["integrity"]
    print()
    print(f"integrity: expected_writes={integrity['expected_writes']} "
          f"counted={integrity['counted']} ok={integrity['ok']}")
    if "restart_under_load" in result:
        print(f"restart-under-load: {result['restart_under_load']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load-test the BLAXCY split services")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--per", type=int, default=40, help="calls per thread")
    parser.add_argument("--root", default=None, help="runtime root (default: temp dir)")
    parser.add_argument("--restart", action="store_true",
                        help="also crash Memory under load and measure recovery")
    parser.add_argument("--keep", action="store_true", help="keep the temp runtime root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run_load(root=Path(args.root) if args.root else None,
                      threads=args.threads, per=args.per,
                      restart=args.restart, keep=args.keep)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_human(result)
    bad = any(s["errors"] for s in result["scenarios"]) or not result["integrity"]["ok"]
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
