# BLAXCY — Checkpoint

## Last safe checkpoint

- 2026-10-03 (public release packaging): version `1.0.0`, complete PEP 639
  metadata + per-feature extras, one-line `install.sh` bootstrap, MIT license,
  CHANGELOG/CONTRIBUTING/SECURITY/CoC, CI, templates. Ruff found and this
  session fixed a real undefined-`Any` defect in `blaxcy/eye/x11.py`. 246 tests
  pass, `./install.sh --dev` verified, error-only Ruff clean. Published to
  `alex3430143/blaxcyds`.
- 2026-10-03 (evidence integrity): fixed a bug where an **unauthorized**
  `accept-live` run overwrote the real B7 evidence artifact. Root cause: the CLI
  test ran against the project root, so `Application()` wrote into the real
  `.build-state/`. The test is now isolated with `BLAXCY_ROOT`,
  `blaxcy/acceptance.py` writes refusals to `B7_EVIDENCE.refused.md` and never
  overwrites real evidence, and a regression test guards it. The genuine
  artifact is still missing (B-010), so B7 is downgraded from VERIFIED to
  IMPLEMENTED until `BLAXCY_ENABLE_REAL_INPUT=1 blaxcy accept-live` regenerates it.
  The suite is now 247 tests.
- 2026-10-03T08:03Z (B7 regenerated, B-010 RESOLVED): the operator authorized a
  real run. `BLAXCY_ENABLE_REAL_INPUT=1 blaxcy accept-live` completed with
  **13/13 steps, `verified: True`, token `blaxcy-ef473f8a`** — real cursor
  save (1003,668), real mouse move to (688,445), real click, real typing confirmed
  in the throwaway terminal's file, **independent Eye observation** of the cursor
  and the focused `BLAXCY_ACCEPT` window, EOF, cursor restored, target closed.
  Artifact: `.build-state/B7_EVIDENCE.md`. B7 is VERIFIED again, and B-001/B-010
  are RESOLVED. Requirements, manifest, README and STATE.md reflect this.

- Timestamp: 2026-10-01 (Phase-2/3 pass: browser, delegation, installer, Wayland,
  provider hardening, B7 harness)
- Safe point: entire `/home/tsn/blaxxxcy` tree is consistent; **183 tests pass**
  and `blaxcy doctor` is OK. `blaxcy resume` reports no discrepancies.
- What this pass added:
  - `blaxcy/browser/cdp.py` + `blaxcy/tools/browser.py`: real Chrome/Chromium
    control over the DevTools Protocol; new `BROWSER_*` ActionKinds + Policy risks;
    `AutoBackend`/`make_backend("browser")` routing; `blaxcy browser` CLI.
  - `blaxcy/delegation.py`: delegate to another model + independent verification
    (code/JSON checks, cross-model agreement) + provenance; `blaxcy delegate` CLI.
  - `install.sh` (rewritten), `upgrade.sh`, `uninstall.sh`: full lifecycle with
    `--dry-run`/`--root`/`--yes`/`--purge`.
  - `blaxcy/eye/wayland.py`: portal screenshot capture + capability detection +
    `select_eye_backend`; `app.py` now selects the backend per session.
  - `blaxcy/brain/providers.py`: OpenAI/Groq/OpenRouter/Together/Anthropic/local
    presets; `blaxcy/brain/router.py`: retry + per-provider cooldown.
  - `blaxcy/acceptance.py` + `blaxcy accept-live`: supervised, reversible B7
    harness (gated on `BLAXCY_ENABLE_REAL_INPUT=1`).
- Tests run: `python3 -m pytest -q` → **183 passed**; `python -m blaxcy doctor` → OK.
- Safe resume action: run `python -m pytest -q` and `python -m blaxcy doctor`,
  reconcile against `TESTS.md`, then see `PLAN.md` "Exact next actions".

## Re-verification pass — 2026-10-01T12:05Z (resuming agent, same day)

Re-derive everything from the filesystem; do not trust the entries above.

- `python3 -m pytest` → **183 passed in 26.62s** (matches the saved claim).
- `python -m blaxcy doctor` → OK (18 components; X11/XFCE; AT-SPI windows=2;
  OCR/CV available; browser `/usr/bin/google-chrome`; credentials `encrypted-file`;
  `real_input=disabled (dry-run)`).
- `python -m blaxcy resume` → `discrepancies: []`, `interrupted_tasks: []`.
- `python -m blaxcy run "list the files in the current directory" --json` → completed
  the autonomy loop honestly (`status=escalated`: the deterministic planner refused
  to invent steps from a vague goal) with **no real input**.
- Legacy `/home/tsn/blaxcy` and prior attempt `/home/tsn/blaxxcy`: read-only;
  not modified by this pass.
- Result: saved state and reality agree; no reconciliation was needed.
- New observation (risk, not a defect): on this host `blaxcy delegate` can exceed
  2 minutes because the local `tinyllama` model is saturated (load average ~9).
  The Router's per-provider timeout is 60 s, so this is honest timeout behaviour;
  see BLOCKERS B-007.
- Safe resume action: unchanged — run the tests + doctor, reconcile, then PLAN.md.

## Live-acceptance pass — 2026-10-01T12:35Z (B7 closed)

- User explicitly authorized real input; ran `BLAXCY_ENABLE_REAL_INPUT=1 python -m
  blaxcy accept-live`.
- **B7 VERIFIED** — 4/4 consecutive runs passed. Real pointer move, click, typing
  and key press; the unique token was read back out of the throwaway terminal's
  file AND independently perceived by the Eye (cursor at the exact coords,
  focused window `BLAXCY_ACCEPT`). Evidence: `.build-state/B7_EVIDENCE.md`
  (`verified: True`, timestamp 2026-10-01T12:34:24Z). Cursor restored, xterm
  closed, temp file deleted.
- The live run exposed and fixed two real defects:
  - DEC-018: `xdotool mousemove --sync` hangs when the pointer is already at the
    target → removed `--sync` from all pointer moves (`blaxcy/body/backends.py`,
    `blaxcy/acceptance.py`); `windowactivate` uses a bounded sync + fallback.
  - DEC-019: `windows()` spawned ~180 xdotool processes/frame (~6.8s) via a
    capped, junk-heavy list that could drop the focused window → now enumerated
    in-process via python-Xlib (`_NET_CLIENT_LIST`), active window guaranteed,
    monitors cached. Frames ~2.4–11.7s → ~0.8s.
- Tests: `python3 -m pytest` → **185 passed** (added 2 regressions:
  `test_eye.py::test_x11_windows_includes_active_window_beyond_the_cap`,
  `test_body.py::test_x11_mouse_actions_never_use_hanging_sync`).
  `blaxcy doctor` → OK; `blaxcy resume` → no discrepancies.
- Safe resume action: run the tests + doctor, reconcile, then PLAN.md.

## Process-split pass — 2026-10-01 (Phase-3 item 1 complete)

- Added `blaxcy/service.py` (generic `ServiceServer`/`ServiceClient`/
  `ProcessComponent` + `watch_parent`) and `blaxcy/eye/service.py` (`build_eye`,
  `EyeService`, `RemoteEye`). `Application(split=("eye",))` runs the Eye as a
  supervised subprocess; `blaxcy run --split eye`, `blaxcy serve eye`, and
  `blaxcy services` were added. Default remains in-process.
- Verified end-to-end on the real desktop: the service answered an authenticated
  ping, served a real `ScreenState` (`source=x11:import`, real windows/cursor),
  and `SIGKILL`-ing it triggered `heartbeat_lost` → `safe_release` → restart with
  a new pid (state `degraded`). `blaxcy services` reports `stopped` after exit.
- Fixed a real robustness gap found while testing: a service whose parent died
  without `stop()` would be orphaned; `watch_parent` now makes it self-terminate.
- Tests: **199 passed** (added `tests/test_service.py`, 10 tests, which spawn real
  child processes). `blaxcy doctor` → OK; `blaxcy resume` → no discrepancies.
- Safe resume action: run the tests + doctor, reconcile, then PLAN.md.

## Multi-process pass — 2026-10-02 (Memory + Brain split, IPC hardening)

- Added `MemoryService`/`RemoteMemory` (`blaxcy/memory.py`) and
  `BrainService`/`RemoteBrain` (`blaxcy/brain/service.py`), both spawned by the
  existing `ProcessComponent` via `blaxcy serve <name>` and supervised by the
  existing `Supervisor`. The Brain service preserves provider routing, retry /
  cooldown and the deterministic offline fallback.
- Added `blaxcy/planning.py`: a model's text can only become a `Plan` through a
  closed action/param whitelist with BLAXCY-assigned risk; invalid output is
  rejected and the deterministic planner takes over (H6, DEC-024).
- Hardened the IPC boundary: HMAC now covers `ts`, a ±60 s freshness window,
  a bounded replay cache and duplicate-field rejection; `IPC_VERSION` 1 → 2
  (L8, DEC-025).
- Made split mode configurable: `BLAXCY_SPLIT` env + `blaxcy run --split
  eye,memory,brain|all`; default remains fully in-process (M7). CLI `blaxcy
  serve` now accepts eye/memory/brain and `blaxcy services` reports every
  component with mode/pid/health (a service is `running` only if it answers).
- Fixed a real bug found while testing: a split component under a non-default
  `Settings.root` resolved the wrong runtime root, so the parent never saw its
  socket; `_make_service_process` now passes `BLAXCY_ROOT` to the child.
- Tools deliberately stay in-process, documented in DEC-023 (security chokepoint
  and local Body), so they are not marked as split.
- Verified end-to-end on the real desktop: `blaxcy run --split memory,brain`
  completed and exited with no orphan processes; `blaxcy services` reports
  `stopped` afterwards. `blaxcy doctor` reports the split honestly (a stopped
  split service is `warn`, never `ok`). NOTE: an earlier claim that `--split
  all` did this was later found to be **wrong** — the flag was a silent no-op;
  see the DEC-029 bullet below, where it was fixed and re-verified.
- Measured real IPC/startup/restart latency (`.build-state/PERFORMANCE.md`):
  in-process IPC round-trip median 0.61 ms; memory add median 0.92 ms; memory
  startup/restart ~152 ms; brain startup ~304 ms.
- **Load-validated (2026-10-02):** Memory and Brain were spawned for real and
  driven with 6–8 concurrent threads. After a fix they stayed error-free under
  load (Memory 8x40 writes: 0 errors, integrity preserved; mixed rw: 0 errors;
  Brain 8x30: 0 errors; both loaded together: 0 errors) and a `SIGKILL` under
  load was detected, safe-released (1 release) and restarted with a new pid
  (601 callers saw an explicit `ServiceError` during the gap, never fake data),
  with no orphan processes. Full numbers in `.build-state/PERFORMANCE.md`.
- Load testing found and fixed a **real bug** (DEC-026): `ServiceServer` is
  thread-per-connection and all handlers shared one `sqlite3.Connection`, which
  caused `bad parameter or other API misuse` and silently dropped 44/320 writes;
  `Memory` now serializes on a re-entrant lock with a regression test.
- Added a **supervisor soak test** (`tests/test_soak.py`): each split service
  (memory, brain, and a headless eye) is crashed **3 times** in a row and the
  contract is asserted every cycle — heartbeat loss, safe input release, a new
  pid, `degraded` reported while recovering, and genuinely serving again;
  restart exhaustion ends in `failed`, and no orphan/socket remains.
- Fixed an honest-reporting bug found by the soak test (DEC-027):
  `Supervisor.check_once()` used to emit `restarted` even when it had exhausted
  its budget; it now emits `restart_exhausted` and the state is `failed`.
- The Supervisor now **persists restart/health counters**, and
  `Application.service_status()` / `blaxcy services` / `blaxcy doctor` expose
  `state` and `restarts` (M9). A stopped/never-started component is reported as
  `stopped`, never healthy.
- Added the **repeatable load harness** `scripts/loadtest.py` (M/N8):
  `python3 scripts/loadtest.py --threads 8 --per 40 --restart` reproduces the
  concurrency + restart-under-load numbers; `tests/test_load.py` smoke-tests it.
- Recorded a **real HTTP provider** measurement for the Brain service
  (`.build-state/PERFORMANCE.md`): with Ollama's OpenAI-compatible `/v1` endpoint
  configured as `local`, `RemoteBrain.complete` used it (median 459.5 ms); the
  offline fallback is 2.9 ms; an unreachable provider is cooled and the router
  falls through to `ollama` (151 ms) — never a fabricated answer.
- Found and fixed a **silent split bug** (DEC-029) while inspecting the
  persisted counters: `blaxcy run --split all` built its selection inline and did
  not expand `all`, so it ran everything in-process (a `verified` run that was
  not actually split). Split selection is now normalized in one place
  (`config.normalize_split`) for both `BLAXCY_SPLIT` and `Application(split=...)`.
  Re-verified after the fix: `blaxcy run --split all` really spawns
  Eye+Memory+Brain (the persisted snapshot lists all three), the run is verified,
  learning is persisted via the remote Memory service, and there are no orphans.
- Tests: **244 passed** (199 → 244; added `tests/test_planning.py`,
  `tests/test_split_services.py`, IPC-security, config and CLI tests, the
  concurrent-caller regression, `tests/test_soak.py`, `tests/test_load.py`, and
  the split-alias regression).
  `blaxcy doctor` → OK; `blaxcy resume` → no discrepancies.

## Brain provider latency pass — 2026-10-02 (genuine remote provider measured)

- Added `scripts/brain_provider_bench.py`: spawns the real `blaxcy serve brain`
  once per provider profile (offline / local / remote) over an isolated
  `BLAXCY_ROOT` and drives it through the split `RemoteBrain` client. It records
  the wall round trip, the router-measured provider duration, and **which model
  actually served every call** (so a router fallback can never masquerade as the
  configured provider), and exits non-zero if the preferred provider never served
  or any call errored. `tests/test_brain_provider_bench.py` (2) smoke-tests it
  offline (no network).
- Measured with a **genuinely remote** OpenAI-compatible endpoint over public
  HTTPS (`https://text.pollinations.ai/v1`, free anonymous tier) because no
  account key exists on this host (B-002). Sequential median: remote **505 ms**,
  local Ollama 556 ms, offline deterministic 2.35 ms. Under 4x4 concurrency the
  local single model serialized to 1848 ms (~3.3x) while the remote service stayed
  flat at 511 ms (~1.0x). Every call was served by the configured provider with
  **0 errors**. Full table in `PERFORMANCE.md`.
- Tests: **246 passed** (244 -> 246). `blaxcy doctor` -> OK; `blaxcy resume` ->
  no discrepancies; no orphan processes.
- Safe resume action: run `python3 -m pytest -q`, `blaxcy doctor`,
  `blaxcy resume`; regenerate the latency numbers with
  `scripts/brain_provider_bench.py --profiles offline,local,remote`.

## Remaining (see REQUIREMENTS.md)

- **B7 live evidence** — the only acceptance item not produced. The harness exists
  and is tested; producing the evidence requires explicit authorization
  (`BLAXCY_ENABLE_REAL_INPUT=1 blaxcy accept-live`).
- H5 remote half — remote provider presets are implemented and honest; a real
  remote call needs API credentials (BLOCKERS B-002).
- D3 — the portal path is implemented and tested; live evidence needs a Wayland
  host (BLOCKERS B-003).

## Interruption notes

- What was being done? → `STATE.md` / this file.
- What actually finished? → `TESTS.md` + a fresh `pytest` run.
- What is safe to continue? → `PLAN.md` "Exact next actions".
- What must be verified again? → anything claimed IMPLEMENTED but not VERIFIED.

Recovery: read `.build-state/`, inspect the filesystem, run the tests,
reconcile, resume. Never trust a saved claim over a fresh check.
