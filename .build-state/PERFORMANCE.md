# BLAXCY — IPC / service performance

All numbers below were **measured on this host** (2026-10-02, X11, Python 3.14.6)
with a throwaway benchmark run against real sockets, not estimated. Re-run to
re-verify; treat these as indicative, not as guarantees.

## Measurement method

- In-process IPC: `ServiceServer` + `ServiceClient` over a real Unix socket,
  300 sequential `call("echo")` round-trips; median and p95.
- Services: spawned with the real `blaxcy serve <name>` command over an isolated
  `BLAXCY_ROOT` temp directory; startup = `ProcessComponent.start()` (spawn →
  authenticated `ping` answered).
- Restart = `SIGKILL` the child, then `ProcessComponent.start()` (spawn → ready).

## Results

| Measurement | Value |
|-------------|-------|
| In-process IPC round-trip (`call`), n=300 | median **0.606 ms**, p95 **0.884 ms** |
| Memory service startup (spawn → ready) | **152.4 ms** |
| Memory `add` over IPC, n=50 | median **0.924 ms**, p95 **1.377 ms** |
| Memory `query` over IPC, n=50 | median **1.060 ms**, p95 **1.436 ms** |
| Memory restart (SIGKILL → ready) | **152.2 ms** |
| Memory health probe (`call("health")`), n=20 | median **0.637 ms** |
| Brain service startup (spawn → ready) | **303.8 ms** |
| Brain `complete` (deterministic offline fallback) over IPC, n=20 | median **2.874 ms**, p95 **20.893 ms** |

## Under real concurrent load (2026-10-02)

Both services were spawned for real (`blaxcy serve memory` / `serve brain`) over
an isolated `BLAXCY_ROOT`, then driven concurrently by Python threads. Host load
avg at start: **2.27** (1 min), 8 cores. Latency in milliseconds.

| Scenario | n | errors | median | p95 | p99 | max | throughput |
|---|---|---|---|---|---|---|---|
| Memory `add`, sequential | 60 | 0 | 0.852 | 0.993 | 1.176 | 1.176 | — |
| Memory `add`, 8 concurrent writers | 320 | **0** | 5.188 | 6.407 | 7.892 | 8.126 | 1492.7/s |
| Memory mixed read/write, 8 concurrent | 400 | **0** | 5.817 | 6.802 | 7.307 | 7.616 | 1369.1/s |
| Brain `complete`, 8 concurrent | 240 | **0** | 9.196 | 12.693 | 14.283 | 14.995 | 835.3/s |
| Memory + Brain simultaneously loaded | 120 | **0** | 7.645 | 10.493 | 13.595 | 16.002 | 718.9/s |

Integrity check: after 1 warm-up + 60 sequential + 320 concurrent writes, the
service reported exactly **381** records — no write was dropped.

## Restart under real load (2026-10-02)

6 threads hammered `RemoteMemory.add` continuously while the Memory service was
`SIGKILL`ed and the `Supervisor` monitor (interval **0.5 s** in this run) was left
to detect and restart it:

| Metric | Value |
|---|---|
| old pid → new pid | 75613 → **77740** (new process) |
| safe input release before restart | **1** |
| service state after restart | `degraded` (running, recently unhealthy) |
| restarts | 1 |
| failures observed by callers during the gap | **601**, all explicit `ServiceError` (never a fabricated empty result) |
| successes | 4184 |
| orphan processes after teardown | **none** |

Conclusion: under real concurrent load the services stay correct (zero errors,
integrity preserved) and a crash is detected, restarted with a new pid, and
recovered from with the caller seeing an explicit degraded/unavailable state
rather than silently-wrong data.

## Bug found and fixed under this load test

Before the fix, 8 concurrent writers produced `handler error: bad parameter or
other API misuse` on **44 / 320** memory writes and **17 / 400** mixed ops and
silently lost records. Cause: `ServiceServer` is thread-per-connection, and all
connection threads shared one `sqlite3.Connection` (`check_same_thread=False`),
which is not safe for concurrent statement execution. Fix: `Memory` now
serializes every public method on a re-entrant lock (`blaxcy/memory.py`).
Regression test: `tests/test_split_services.py::test_memory_service_survives_concurrent_callers`.

## Brain latency: offline vs local vs genuinely remote (2026-10-02)

The split `BrainService` was spawned for real (`blaxcy serve brain`) once per
provider profile over an isolated `BLAXCY_ROOT`, then driven through the split
`RemoteBrain` client over the authenticated IPC. Reproduced with
`scripts/brain_provider_bench.py`; **the model that actually served each call is
recorded**, so a router fallback can never be mistaken for the configured
provider. Every profile showed `err=0` and every call was served by the intended
provider (no fallback).

| Profile (provider configured) | transport | n (seq) | wall median | wall min | wall max | provider median | concurrent 4x4 median |
|---|---|---|---|---|---|---|---|
| `offline-deterministic` | in-process, no network | 8 | **2.35 ms** | 2.01 | 2.83 | 1.61 ms | 4.04 ms |
| `local` -> Ollama `/v1` (`tinyllama:latest`) | real HTTP to `127.0.0.1:11434` | 8 | **555.7 ms** | 95.0 | 756.9 | 555.0 ms | 1848.3 ms |
| `openai` -> **Pollinations.ai** (`openai` / gpt-oss-20b) | **real HTTPS over the internet** | 8 | **505.2 ms** | 404.5 | 1020.5 | 503.8 ms | 511.4 ms |

- **The remote profile is genuinely remote**: configured with
  `BLAXCY_OPENAI_BASE_URL=https://text.pollinations.ai/v1`, a real
  internet-hosted inference service reached over public HTTPS. The measured
  provider duration reflects real network + remote inference, not a localhost
  mock; the served model was the remote provider on every call.
- **Remote vs local-by-transport**: the remote endpoint's sequential median
  (505 ms) is in the same range as the localhost Ollama model (556 ms) — the
  inference dominates, not the network leg (a direct HTTPS round trip to the
  remote host is sub-second). The architectural difference shows under
  concurrency: the single local model **serializes** (4x4 median 1848 ms, ~3.3x),
  while the remote service handled the same 16 concurrent requests with almost no
  degradation (511 ms, ~1.0x).
- **Remote vs offline**: remote inference is ~2 orders of magnitude slower than
  the deterministic fallback (505 ms vs 2.35 ms, ~215x) — which is exactly why
  model calls run in their own supervised process instead of the control loop.
- Credentials note: no user-supplied remote **account** credentials exist on this
  host (BLOCKERS B-002), so the remote profile used Pollinations.ai's free
  anonymous OpenAI-compatible endpoint. The code path is identical for any keyed
  preset (openai/groq/openrouter/together/anthropic): set
  `BLAXCY_<PROVIDER>_API_KEY` (+ `_BASE_URL`/`_MODEL`) and re-run the same command.
- Failure path (unchanged): with a provider pointed at an unreachable address the
  router classifies it `unavailable`, cools it (30 s) and falls through to the
  still-available provider, returning a real answer and **no fabricated
  response**. The client timeout must exceed the provider timeout; the default
  `RemoteBrain` timeout is **180 s**.

## Reproduce these numbers

    python3 scripts/loadtest.py --threads 8 --per 40 --restart
    python3 -m pytest -q                     # runs tests/test_soak.py, tests/test_load.py

    # Brain provider latency (offline baseline; add local/remote as configured):
    python3 scripts/brain_provider_bench.py --profiles offline,local
    BLAXCY_OPENAI_API_KEY=... BLAXCY_OPENAI_BASE_URL=... BLAXCY_OPENAI_MODEL=... \
        python3 scripts/brain_provider_bench.py --profiles offline,remote

The soak test (`tests/test_soak.py`) crashes each split service repeatedly and
asserts detection, safe release, a new pid, `degraded` reporting, restart
exhaustion → `failed`, and no orphans.

## Notes

- The IPC layer is a newline-delimited JSON protocol with an HMAC-SHA256 token
  per message, a freshness window and a replay cache. The round-trip cost above
  is *with* those checks enabled.
- Brain startup is dominated by the local Ollama availability probe (~1.5 s
  budget) plus registry construction; it is a one-time cost per service start.
- Supervisor health **detection granularity** is the monitor interval
  (`Supervisor.start_monitor(interval_s=...)`, default **2.0 s**), not a fixed
  constant; `check_once()` itself is cheap because a dead child is detected via
  `process.poll()` without a socket call.
- These are single-host loopback measurements; there is no network transport.
