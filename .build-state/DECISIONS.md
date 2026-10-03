# BLAXCY — Architecture Decisions

Format: ADR-ish, append-only. Each decision records context, decision, and
consequences so a resuming agent understands *why*, not just *what*.

## DEC-001 — Build fresh in `/home/tsn/blaxxxcy`, reuse nothing at runtime

- Context: A legacy project exists at `/home/tsn/blaxcy`, and an earlier agent
  attempt of this same task exists at `/home/tsn/blaxxcy` (two x's).
- Decision: Implement a new, independent project at `/home/tsn/blaxxxcy`. The
  other two directories are inspected read-only and are never imported,
  modified, or depended upon.
- Consequences: Some design lessons were reused (from the prior attempt), but no
  file is copied/imported. `pyproject.toml` here declares its own package.

## DEC-002 — Safety-first: dry-run by default; real input is explicit opt-in

- Context: A computer-use agent that can really move the mouse/keyboard is
  dangerous and untestable in CI.
- Decision: `Settings.real_input_enabled` defaults to `False`. The Body uses a
  `DryRunBackend` unless both `BLAXCY_ENABLE_REAL_INPUT=1` **and** Policy approval
  are present. `EmergencyStop` and pause are checked before every action.
- Consequences: Tests are safe. Live control is available but must be requested.

## DEC-003 — Filesystem is the source of truth; state is reconciliable

- Context: The master prompt requires recovery by any agent after any crash.
- Decision: All persistent state is plain files under `.build-state/` plus a
  JSON task state store with atomic writes. `recovery.py` re-derives reality from
  the filesystem and reconciles it against saved claims.
- Consequences: No dependence on chat memory or process memory.

## DEC-004 — Typed, versioned contracts at the boundaries

- Context: Eye, Body, Brain, Memory, Policy and IPC must stay decoupled.
- Decision: All cross-component messages are dataclasses in `models.py`, JSON
  serializable, with an explicit `IPC_VERSION`, and (for IPC) an HMAC auth token.
- Consequences: Components can run in-process now and split into processes later
  without redesign.

## DEC-005 — Perception is a continuous sampler with event waits

- Context: The prompt forbids screenshot→sleep→screenshot designs.
- Decision: The Eye runs a background sampler thread producing timestamped
  `ScreenState` frames with change detection, and exposes `wait_for(condition)`
  built on a condition variable (no arbitrary sleeps).
- Consequences: Latency is measured (p50/p95); callers block on change, not time.

## DEC-006 — Model-agnostic Brain with honest availability

- Context: Models change fast; the router must not hard-code one provider.
- Decision: `brain/registry.py` stores capability descriptors; `brain/router.py`
  selects by need with ordered fallbacks and classifies failures
  (unavailable/quota/timeout/rate_limit/capability). A deterministic offline
  provider guarantees a working planner even with zero configured models.
- Consequences: The system never claims an unavailable model is working; adding a
  real model is a registry entry + adapter, no redesign.

## DEC-007 — Policy is the single chokepoint for risk

- Context: Security and safety requirements are broad.
- Decision: Every action is classified into a `RiskClass` (SAFE/LOW/MEDIUM/HIGH/
  AUTH_BOUNDARY/DESTRUCTIVE). HIGH/DESTRUCTIVE require explicit confirmation;
  AUTH_BOUNDARY is never auto-performed. Untrusted external content is tagged and
  cannot be promoted to trusted instructions automatically.
- Consequences: One place to audit safety; tests target Policy directly.

## DEC-008 — Memory stores experience, never secrets; provenance is mandatory

- Context: Learning requires persistent experience; security forbids leaking
  secrets.
- Decision: SQLite `memory.py` stores records with source, trust level,
  confidence, timestamp and optional expiry; values are redacted before storage.
- Consequences: Useful lessons persist across sessions without credential risk.

## DEC-009 — Observability is structured and redacted

- Context: Diagnostics and auditability are required; privacy is required too.
- Decision: JSON-line logs with task/action ids and component tags; a redaction
  filter scrubs API keys, tokens, passwords, cookies, and private-key blocks.
- Consequences: `blaxcy doctor` and logs are useful without leaking secrets.

## DEC-010 — UI is a transparent ~20% panel, never a simulated desktop

- Context: The real desktop must stay ~80% visible and be operated, not simulated.
- Decision: `ui/panel.py` is a docked PyQt6 panel occupying ~20% of screen width
  with emergency stop / pause / takeover and live status; it never renders a
  fake desktop or fake screenshots.
- Consequences: The panel degrades gracefully (import-guarded) when no display or
  no PyQt6 is available.

## DEC-013 — Browser control is real CDP, and is a tool (I3)

- Context: The prompt forbids faking browser control or substituting a headless
  browser for the computer.
- Decision: Implement a real Chrome DevTools Protocol client
  (`blaxcy/browser/cdp.py`) using `websocket-client`, launched with a private
  profile and `--remote-allow-origins=*`. Browser actions are new `BROWSER_*`
  ActionKinds routed through the Body so Policy gates them; arbitrary page JS is
  HIGH and needs explicit opt-in. The desktop remains the primary computer; the
  browser is one more tool.
- Consequence: Real navigate/query/click/type/screenshot/eval verified against a
  headless Chrome. `blaxcy browser <action>` exposes it from the CLI.

## DEC-014 — Delegation output is untrusted until independently verified (I4)

- Context: Another model's output must never be trusted blindly.
- Decision: `DelegationTool` asks the Router, then applies machine-checkable
  verification (code compiles, JSON parses) and/or a cross-check from a different
  model. Output starts UNTRUSTED; only passing verification raises it to DERIVED.
  Degraded answers from the deterministic fallback are flagged.
- Consequence: Provenance and confidence are recorded in Memory; delegation cannot
  silently become an instruction.

## DEC-015 — Installer lifecycle is scripted, argument-aware and tested (N5/P1)

- Context: install/upgrade/uninstall must be real and testable without network.
- Decision: `install.sh`/`upgrade.sh`/`uninstall.sh` support `--root`, `--dry-run`,
  `--yes`, `--purge`; upgrades never touch user data; uninstall refuses to delete
  without `--yes`. Tests run them against a temp root.
- Consequence: The full lifecycle is verifiable offline.

## DEC-016 — Wayland is portal-mediated and honestly detected (D3)

- Context: Wayland has no global screen/input; the supported route is the XDG
  portal.
- Decision: `blaxcy/eye/wayland.py` implements portal Screenshot capture with a
  synchronous Request/Response handshake, detects capability, and `select_eye_backend`
  chooses X11/Wayland/fake per session. DBus is only probed on Wayland sessions.
- Consequence: The code is correct-by-construction and unit-tested, but live
  evidence needs a Wayland host (this host is X11, no portal present).

## DEC-017 — B7 is a supervised, reversible, gated live test

- Context: Real mouse/keyboard input is dangerous and unverifiable in CI.
- Decision: `blaxcy accept-live` refuses unless `BLAXCY_ENABLE_REAL_INPUT=1`; it
  acts only on a throwaway `xterm` it creates (stdin redirected to a temp file),
  saves and restores the cursor, and always closes/deletes its artifacts. It
  verifies both the real effect (typed token appears in the file) and independent
  perception (Eye sees the cursor move and the window focused), writing evidence.
- Consequence: B7 is producible on demand with explicit authorization and cannot
  harm user windows.

## DEC-012 — Advanced perception/credentials are wired in, not left as dead code

- Context: On resume (2026-10-01) `eye/atspi.py`, `eye/vision.py`,
  `brain/providers.py` and `credentials.py` existed but were never constructed by
  `Application`, had no tests, and were described as NOT_STARTED in REQUIREMENTS.
- Decision: Construct and inject them in `app.py` (`VisionBackend` → `Eye`,
  `AtspiBackend` → `X11EyeBackend`, `CredentialStore` on the app), expose them in
  `blaxcy doctor`, and cover them with real tests. Correct the saved statuses.
- Consequences: Perception now carries AT-SPI application identity and can OCR/CV
  on demand; credentials are stored via the keyring chain. The saved build state
  matched reality again. No requirement was weakened — several were advanced.

## DEC-018 — Never use `xdotool ... --sync` for pointer moves

- Context: The first live B7 run intermittently failed with `real click: timed
  out`, and the click's internal `xdotool mousemove --sync X Y` was observed to
  hang for the full timeout when the pointer was *already* at (X,Y) — `--sync`
  waits for a motion event that never fires. A follow-up probe reproduced it:
  moving to a new point returned in 0.02s; moving to the current point hung.
- Decision: All pointer moves omit `--sync`. XTEST motion and subsequent
  button/key requests are processed in order by the X server, so `--sync` is not
  needed for correct sequencing. `windowactivate --sync` keeps a *bounded* sync
  (2s) with an asynchronous fallback because it can hang the same way when the
  window is already active.
- Consequences: Moves/clicks/drags/scrolls no longer stall; B7 is stable. Locked
  in by `tests/test_body.py::test_x11_mouse_actions_never_use_hanging_sync`.

## DEC-019 — Enumerate X11 windows in-process, not via one xdotool per window

- Context: The live B7 run also revealed perception was ~2.4–11.7s per frame.
  `windows()` spawned three `xdotool` subprocesses per window (up to ~180/frame,
  ~6.8s), which both violated the near-continuous/low-latency requirement and
  starved the X server (contributing to input timeouts). The list also used
  `xdotool search --onlyvisible --name ""` (105 junk windows) truncated to 60, so
  the focused window could be dropped and `active_window()` returned None.
- Decision: Query `_NET_CLIENT_LIST`/`_NET_WM_PID` and per-window geometry/name
  directly through a persistent python-Xlib connection (in-process, microseconds),
  with the old xdotool path retained as a fallback when Xlib is unavailable and
  the focused window guaranteed to be enumerated. Monitor geometry is cached for
  5s (xrandr was ~0.3s/frame).
- Consequences: Frames dropped to ~0.8s; window list is the ~7–8 real managed
  clients; the active window is always present. Locked in by
  `tests/test_eye.py::test_x11_windows_includes_active_window_beyond_the_cap`.

## DEC-020 — Project-local `.env` is the supported place for provider keys

- Context: Remote model providers are configured via environment variables, but
  nothing in the code read the `.gitignore`'d `.env` the repo already reserved —
  so adding a provider key meant exporting it manually every session (H5).
- Decision: `config.load_env_file()` parses `KEY=VALUE` lines (comments, `export`,
  quotes) from `<project_root>/.env` into `os.environ`, with **real environment
  variables always winning**. It is invoked from `load_settings()` and
  `default_registry()`, so both the app and every CLI command pick the key up.
  The key still never enters source, `.build-state/`, or logs.
- Consequences: A user can drop `BLAXCY_OPENAI_API_KEY=...` into `.env` (chmod
  0600) and the provider appears in `blaxcy models`. Covered by
  `tests/test_config.py` (parsing, precedence, and dotenv→registry integration).

## DEC-021 — Components can run as supervised processes over the authenticated IPC

- Context: The master prompt requires components communicating through typed,
  versioned, authenticated IPC with a supervisor that restarts failures; the IPC
  primitive and in-process supervisor existed but no component actually ran in a
  separate process (PLAN Phase-3 item 1).
- Decision: Add `blaxcy/service.py` — `ServiceServer` (explicit method whitelist),
  `ServiceClient`, and `ProcessComponent` (spawn → authenticated-ping readiness →
  health → stop). `ProcessComponent` registers with the existing `Supervisor`, so
  restart-on-crash and the pre-restart safe input release are reused unchanged.
  The first split component is the **Eye** (`blaxcy/eye/service.py`): `RemoteEye`
  mirrors the Eye API over IPC (whitelisted methods, `ScreenState` reconstructed
  from the wire) and the service warms its first real frame before reporting
  ready. Enable with `blaxcy run --split eye`; default stays in-process.
- Safety: secrets stay in the env/runtime secret file (never on a command line);
  `watch_parent` makes a service exit if its supervisor dies so it is never
  orphaned; a `RemoteEye` with a fallback counts and reports degradation instead
  of silently faking perception.
- Consequences: 10 new tests (real subprocess spawn, auth, unknown-method and
  startup-failure rejection, crash→restart with safe release, parent-watchdog,
  degradation). `blaxcy serve`/`blaxcy services` expose it from the CLI.

## DEC-011 — Legacy and prior attempts are quarantined, not deleted

- Context: The user has multiple similarly named folders; deletion is destructive.
- Decision: `/home/tsn/blaxcy` and `/home/tsn/blaxxcy` are left exactly as found.
  Their existence is recorded in `ENVIRONMENT.md` so a resuming agent is not
  confused by them.
- Consequences: No destructive operations; the user retains full control.

## DEC-022 — Memory and Brain run as supervised processes over the authenticated IPC

- Context: Only the Eye was split into a supervised process; Memory and Brain
  stayed in-process, so a slow model call or a memory fault still ran in the
  orchestrator's process.
- Decision: Add `MemoryService`/`RemoteMemory` (`blaxcy/memory.py`) and
  `BrainService`/`RemoteBrain` (`blaxcy/brain/service.py`). Each is spawned by the
  existing `ProcessComponent` via `blaxcy serve <name>`, registered with the
  existing `Supervisor` (restart + safe input release reused unchanged) and
  protected by `watch_parent`.
- Safety: exactly one process owns the SQLite file, so there are no cross-process
  write races. `RemoteMemory` has **no silent fallback**: a down service raises,
  so missing data is never mistaken for an empty (valid) result; the
  orchestrator's learning writes are wrapped and counted in `memory_degraded`.
  `RemoteBrain` preserves provider routing, retry/cooldown and the deterministic
  offline fallback, so a hung provider can no longer stall perception/control.
- Consequences: `Application(split=('memory','brain'))` / `blaxcy run --split
  memory,brain`; new real-subprocess tests in `tests/test_split_services.py`.
- No ambiguous work is replayed: a restart re-creates the service process but
  never replays an in-flight request; the orchestrator's in-process action ledger
  (`blaxcy/recovery.py`) still prevents repeating a failed action. During the
  restart window a caller sees an explicit error / `degraded` state, never a
  fabricated empty result.

## DEC-023 — Tools intentionally stay in-process (isolation NOT applied)

- Context: The task asked to split the resource/tool layer *where architecturally
  appropriate*, and to document any component that should remain in-process.
- Decision: terminal/filesystem/browser/delegation tools remain in-process.
- Why: tools are thin `Action` builders. Policy + Body is the single security
  chokepoint, and the Body's X11/Wayland backends plus `panic_release()` are
  physically bound to the local desktop session. Moving tool execution across a
  process boundary would let `Action` objects be constructed outside Policy's
  view and would separate `panic_release` from the actions it guards — strictly
  weaker, not stronger. The genuinely expensive/remote pieces are already
  isolated: browser CDP is its own backend and delegation's model calls go
  through the Brain service.
- Security implications: no new boundary; the existing Policy chokepoint is
  unchanged.
- Failure implications: a tool crash still fails the orchestrator (as today);
  acceptable because tools do no long-running work and are exercised by `Body`.
- Why isolation is unnecessary: no latency/CPU benefit and it would weaken the
  security model.

## DEC-024 — Model output can never authorize Body actions

- Context: A malformed or malicious model response must never become behaviour.
- Decision: `blaxcy/planning.py` adds `validate_model_plan`/`validate_action_dict`
  and a `ModelPlanner`. A model only ever returns text; it must parse into a
  `Plan` through a closed action-kind whitelist with per-kind parameter
  whitelists, bounded sizes, a restricted verify-key set, and **BLAXCY-assigned**
  risk classes (the model's own `risk` field is ignored). Anything invalid is
  rejected wholesale and the deterministic `RulePlanner` takes over. Every
  accepted action still passes Policy.
- Consequences: `BLAXCY_PLANNER=model` enables the validated model planner; the
  default stays `rules` (backward compatible). Covered by `tests/test_planning.py`.

## DEC-025 — IPC is authenticated, fresh, replay-proof and strict

- Context: Security review of the multi-process boundary.
- Decision: (1) the HMAC now covers `ts`, so freshness is authenticated;
  (2) the server rejects messages outside a ±60 s skew window; (3) it remembers
  message ids (bounded cache) for a 120 s window and rejects replays; (4) JSON
  parsing rejects duplicate fields. `IPC_VERSION` bumped 1 → 2.
- Unchanged: the secret is stored mode 0600, the socket is mode 0600, and the
  secret is passed to the child via the environment, never a command line.
- Consequences: `tests/test_ipc.py` covers stale, replay, tampered-time and
  duplicate-field rejection.

## DEC-026 — Memory serializes on a lock (found under real concurrent load)

- Context: `ServiceServer` is **thread-per-connection**, so several handlers run
  concurrently in one process. A real load test (8 concurrent writers) produced
  `handler error: bad parameter or other API misuse` on 44/320 memory writes and
  silently lost records — one shared `sqlite3.Connection`
  (`check_same_thread=False`) is not safe for concurrent statement execution.
- Decision: `Memory` keeps a `threading.RLock` and every public method
  (`add`/`query`/`get`/`count`/`forget`/`forget_expired`/`recent_lessons`/
  `close`) serializes on it; the lock is re-entrant so `recent_lessons` → `query`
  is safe. This makes the store correct for any caller, in-process or served.
- Consequences: under 8-way concurrency memory now reports **0 errors** and
  preserves integrity (381/381 records survived). Locked in by
  `tests/test_split_services.py::test_memory_service_survives_concurrent_callers`.
  This bug would not have been found by mock-only tests; it is exactly why the
  service tests spawn real processes and drive them concurrently.

## DEC-027 — Supervisor reports restarts truthfully and persists its counters

- Context: A soak test that crashed a service past its restart budget found that
  `Supervisor.check_once()` emitted a `"restarted"` event even when it had given
  up — the component was actually `failed`. The counters also existed only in the
  running process, so `blaxcy services` (a separate invocation) could show nothing.
- Decision: `check_once()` now emits `"restart_exhausted"` (state `failed`) when
  no restart happened. `Supervisor._persist()` writes the counters (`state`,
  `restarts`, `last_error`) to the `StateStore` on every event and on
  start/stop; `Application.service_status()` merges the live counters, and
  `blaxcy services`/`doctor` display `state`/`restarts` (persisted snapshot for a
  separate CLI run). A stopped or never-started component is reported `stopped`.
- Consequences: The soak test asserts the full contract for each service; the
  reporting is honest (`degraded` = running but recently unhealthy, `failed` =
  budget exhausted).

## DEC-028 — Repeatable load/soak harness instead of one-off measurements

- Context: Performance numbers must be reproducible and the split services must
  be provably resilient under repeated failure, not just measured once.
- Decision: Add `scripts/loadtest.py` (spawns real services, configurable
  threads/calls, optional restart-under-load, `--json`) and `tests/test_soak.py`
  (repeated crashes of **every** split service with the full safety contract,
  plus restart exhaustion and `Application` counter reporting). `tests/test_load.py`
  smoke-tests the harness at tiny scale in the normal suite.
- Consequences: Anyone can regenerate the numbers in `.build-state/PERFORMANCE.md`
  with one command, and the resilience guarantees are enforced by the suite.

## DEC-029 — Split selection is normalized in one place (`--split all` was a no-op)

- Context: `BLAXCY_SPLIT=all` went through `parse_split` (which expands
  `all`/`full`), but `blaxcy run --split all` built its tuple inline and did not
  expand it. `Application(split=("all",))` therefore matched no component and
  silently ran everything **in-process**. It was found by inspecting the
  persisted supervisor snapshot (only `eye` was registered) instead of trusting
  the run's success — a run can be `verified` while not actually split.
- Decision: add `config.normalize_split` (accepts a string or a sequence;
  expands `all`/`full`; ignores unknown names) and use it for **both**
  `BLAXCY_SPLIT` and the `Application(split=...)` argument; `cmd_run` passes the
  raw string through so there is a single normalization point.
- Consequences: `blaxcy run --split all` now really spawns Eye+Memory+Brain.
  Re-verified end-to-end after the fix: verified run, learning persisted via the
  remote Memory service, and the persisted snapshot lists all three components,
  with no orphans. Regression test:
  `tests/test_split_services.py::test_application_normalizes_split_aliases_without_starting`.

## DEC-030 — A per-provider Brain latency bench, and a genuine remote measurement

- Context: The Brain split had only been measured against a local provider. The
  claim "remote is slower than local" was unproven, and there was no repeatable
  way to regenerate the numbers for whatever provider happens to be configured.
- Decision: add `scripts/brain_provider_bench.py`. It spawns the real
  `blaxcy serve brain` subprocess once per *provider profile* (offline / local /
  remote) over an isolated `BLAXCY_ROOT` and drives it through the split
  `RemoteBrain` client. Crucially it records **which model actually served every
  call** (from `Completion.model`) in addition to wall and provider durations, so
  a router fallback can never be mistaken for the configured provider; it exits
  non-zero if the preferred provider never served or any call errored.
  `tests/test_brain_provider_bench.py` smoke-tests the harness offline (no network).
- Measurement (2026-10-02, real numbers in PERFORMANCE.md): a **genuinely remote**
  OpenAI-compatible provider reached over public HTTPS (Pollinations.ai, free
  anonymous tier — no account key exists on this host, BLOCKERS B-002) gave a
  sequential median of **505 ms** vs **556 ms** for localhost Ollama and **2.35 ms**
  for the deterministic fallback. Under 4x4 concurrency the local single model
  serialized (1848 ms, ~3.3x) while the remote service did not (511 ms, ~1.0x).
- Consequences: The remote provider path is now VERIFIED end-to-end (real network,
  real inference, no fallback). The same command measures any keyed preset by
  setting `BLAXCY_<PROVIDER>_API_KEY`; a specific account provider is a one-line
  re-run, not new code.

## DEC-031 — One canonical source of truth: `alex3430143/blaxcyds`

- Context: three local BLAXCY trees had diverged — `/home/tsn/blaxcy` (legacy,
  Phase 15, ~34.6k LOC), `/home/tsn/blaxxcy` (prior attempt) and
  `/home/tsn/blaxxxcy` (current). Two of them (`blaxcy` and `blaxxcy`) shared the
  same git remote `tasinxxx/blaxcy` despite unrelated histories, so it was unsafe
  to push from either and ambiguous where new work belonged.
- Decision: `/home/tsn/blaxxxcy` is the **single canonical source of truth**,
  published as the public repo `github.com/alex3430143/blaxcyds`. The other two
  trees are frozen and reference-only. The full inventory, the hazard, and the
  ordered port-back backlog live in `.build-state/RECONCILIATION.md`.
- Consequences: work happens only in the canonical tree; nothing is ever pushed
  to `tasinxxx/blaxcy`; legacy capabilities are ported individually with canonical
  tests rather than merging whole trees. The canonical tree is verified green
  (246 tests) with the two remaining gaps environment-gated (B-002, B-003).
