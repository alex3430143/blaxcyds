# BLAXCY — Implementation Plan

## Phase 0 — Foundation (COMPLETE)

1. Confirm `/home/tsn/blaxxxcy` is the empty, intended project root; leave legacy
   `/home/tsn/blaxcy` and the prior attempt `/home/tsn/blaxxcy` untouched.
2. Establish `.build-state/` persistent memory and reproducible Python packaging.
3. Define versioned typed contracts for actions, observations, goals, policy,
   memory, and IPC.

## Phase 1 — First usable vertical slice (CURRENT — mostly implemented)

1. Atomic project/task state + checkpointing (`state_store.py`).
2. Safety controls + typed Body actions; dry-run default, opt-in X11 backend
   (`body/`, `policy.py`).
3. Near-continuous X11 Eye with change detection, window/cursor metadata,
   `wait_for`, latency stats (`eye/`).
4. Goal ownership + deterministic planner + verification + retry/replan +
   model registry fallback (`orchestrator.py`, `verifier.py`, `brain/`).
5. SQLite experience memory, structured redacted logs, supervisor health/restart,
   `blaxcy doctor`, ~20% PyQt control panel (`memory.py`, `logging_utils.py`,
   `supervisor.py`, `cli.py`, `ui/panel.py`).
6. Unit / negative / integration tests that never move the real mouse/keyboard
   (`tests/`).

## Phase 2 — Capability expansion (IN PROGRESS)

1. ✅ AT-SPI accessibility metadata (wired + tested, C8); ✅ local OCR/CV (wired +
   tested, C9). Remaining: XDamage subscription; multi-monitor calibration and
   HiDPI validation on real hardware.
2. ✅ Tool contracts: terminal/filesystem, ✅ **browser (I3, real CDP)**, ✅
   **delegation (I4)**.
3. ✅ Real provider adapters (OpenAI/Groq/OpenRouter/Together/Anthropic/Ollama/local)
   + capability routing + retry/cooldown; local Ollama verified end-to-end.
   Remaining: a real remote call needs credentials (H5 remote half).
4. ✅ User-takeover / auth-boundary handoff (D6, L7); ✅ B7 acceptance harness
   built (supervised, reversible). Remaining: B7 *live run* under authorization.

## Phase 3 — Production hardening (COMPLETE)

1. ✅ Separate services over authenticated Unix IPC — `blaxcy/service.py`
   (`ServiceServer`/`ServiceClient`/`ProcessComponent`, `watch_parent`). Split
   components: **Eye** (`blaxcy/eye/service.py`), **Memory** (`blaxcy/memory.py`)
   and **Brain** (`blaxcy/brain/service.py`), each supervised with restart + safe
   input release and a parent watchdog (DEC-021, DEC-022). Configurable via
   `BLAXCY_SPLIT` / `blaxcy run --split eye,memory,brain|all`; default in-process.
   Tools intentionally stay in-process (DEC-023).
2. ✅ Installer / upgrade / uninstall with `--dry-run`/`--yes`/`--purge` and
   tests (N5, P1).
3. ✅ Controlled live-desktop acceptance **harness** on X11 (`blaxcy accept-live`);
   ✅ document Wayland limits (portal path implemented, not exercisable here).
4. Security, privacy, failure-recovery, performance and operational audit.

## Working rules

- The real filesystem and fresh checks overrule saved claims.
- Real input stays disabled in tests and by default.
- Never modify or import the legacy project(s).
- Update `.build-state/STATE.md`, `TESTS.md`, `CHECKPOINT.md`, `manifest.json` at
  every checkpoint.

## Exact next actions (for a resuming agent)

1. Run `python -m pytest` and `python -m blaxcy doctor`; reconcile with
   `TESTS.md` (expect **244 passed**, doctor OK).
2. B7 is **done** (VERIFIED, 4/4 runs; `.build-state/B7_EVIDENCE.md`). Do not
   re-run it unless the harness or X11 backend changes; if you do, it is gated on
   `BLAXCY_ENABLE_REAL_INPUT=1` and remains reversible.
3. If a remote model key is available, set e.g. `BLAXCY_OPENAI_API_KEY` and verify
   `python -m blaxcy models` shows it available (H5 remote half).
4. Optional Phase-3 follow-ups: split components into processes over IPC;
   packaging/reproducible builds; a deeper security/performance audit.
