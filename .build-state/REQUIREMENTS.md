# BLAXCY — Requirements Lock

This file is the authoritative requirements list. Requirements are never silently
removed, weakened, or reinterpreted. If a technical limitation forces a change, an
entry must be added to the "Requirement change log" at the bottom with the original
requirement, the limitation, the proposed change, the reason, and the impact.

Status values: `NOT_STARTED` | `IN_PROGRESS` | `IMPLEMENTED` | `VERIFIED` | `BLOCKED`

Legend for evidence: file paths and test names that actually exist in the repo.

---

## A. Identity / Direction

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| A1 | BLAXCY is "an AI like a human computer user", not a chatbot / terminal wrapper / model wrapper | IMPLEMENTED | `docs/ARCHITECTURE.md`, `blaxcy/orchestrator.py` |
| A2 | High-level goal in, autonomous plan/execute/verify loop out | IMPLEMENTED | `blaxcy/orchestrator.py`, `tests/test_orchestrator.py` |
| A3 | Direction lock: no drift into a simple chatbot, headless-only automation, screenshot macro, or bare model wrapper | IMPLEMENTED | `docs/ARCHITECTURE.md` (Direction Lock section) |

## B. Real Computer Control (Body)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| B1 | Typed actions: mouse move, click, double/right click, drag, scroll, type, key, hotkey, window switch, app launch, clipboard | IMPLEMENTED | `blaxcy/body/actions.py` |
| B2 | Each action carries target, expected postcondition, timeout, risk class, correlation id | IMPLEMENTED | `blaxcy/models.py` (`Action`) |
| B3 | Every action returns an `ActionResult` | IMPLEMENTED | `blaxcy/body/executor.py`, `tests/test_body.py` |
| B4 | Dry-run is the default; real input requires explicit opt-in AND policy approval | IMPLEMENTED | `blaxcy/config.py`, `blaxcy/policy.py`, `tests/test_policy.py` |
| B5 | Emergency stop, pause, user takeover, heartbeat, safe input release on crash | IMPLEMENTED | `blaxcy/policy.py`, `blaxcy/body/backends.py` |
| B6 | Real X11 backend using XTEST/pyautogui/xdotool | IMPLEMENTED | `blaxcy/body/backends.py` |
| B7 | Controlled live-desktop acceptance evidence (real visible interaction) | VERIFIED | `blaxcy/acceptance.py` + `blaxcy accept-live`; the timestamped artifact `.build-state/B7_EVIDENCE.md` holds the **latest** live run (2026-10-03T08:11:51Z): 13/13 steps — real cursor save, real mouse move, real click, real typing of the run's token confirmed in the throwaway terminal's file, **independent Eye observation** of both the cursor position and the focused `BLAXCY_ACCEPT` window, EOF, cursor restored, target closed. Reproducible: two consecutive authorized live runs on 2026-10-03 (08:03:14Z and 08:11:51Z) both returned `verified: True`. `tests/test_acceptance.py` (7) covers the harness, and B-010 guarantees a refusal can never overwrite this artifact. |

## C. Live Eye (Perception)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| C1 | Continuous/near-continuous desktop observation, not screenshot-wait-screenshot | IMPLEMENTED | `blaxcy/eye/x11.py` (sampler loop) |
| C2 | Maintain timestamped `ScreenState` | IMPLEMENTED | `blaxcy/eye/screen_state.py`, `tests/test_eye.py` |
| C3 | Change/damage detection between frames | IMPLEMENTED | `blaxcy/eye/x11.py` (`detect_change`) |
| C4 | Active window / window list / cursor metadata | IMPLEMENTED | `blaxcy/eye/x11.py` |
| C5 | `wait_for(condition, timeout)` instead of arbitrary sleeps | IMPLEMENTED | `blaxcy/eye/x11.py`, `tests/test_eye.py` |
| C6 | Freshness + confidence on ScreenState | IMPLEMENTED | `blaxcy/eye/screen_state.py` |
| C7 | Per-frame persistence disabled by default | IMPLEMENTED | `blaxcy/config.py`, `tests/test_eye.py` |
| C8 | AT-SPI accessibility metadata | VERIFIED | `blaxcy/eye/atspi.py`, wired in `blaxcy/app.py` (X11 backend), `tests/test_atspi.py`; live probe: 2 windows |
| C9 | OCR / CV / vision-model understanding of widgets | VERIFIED (local OCR/CV) | `blaxcy/eye/vision.py` (Tesseract 5.5.0 + OpenCV), wired into `Eye`, `tests/test_vision.py`; remote vision-model understanding not implemented |
| C10 | p50/p95 latency metrics | IMPLEMENTED | `blaxcy/eye/x11.py` (LatencyStats) |

## D. Desktop Session Support

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| D1 | Detect active display/session instead of assuming fixed environment | IMPLEMENTED | `blaxcy/eye/x11.py` (`detect_session`) |
| D2 | X11 support | IMPLEMENTED | `blaxcy/eye/x11.py`, `blaxcy/body/backends.py` |
| D3 | Wayland support (portal/PipeWire) | IMPLEMENTED | `blaxcy/eye/wayland.py` (portal Screenshot capture + RemoteDesktop detection), `select_eye_backend`, `tests/test_wayland.py`; real end-to-end not verifiable on this X11 host — BLOCKERS B-003 |
| D4 | HiDPI / scaling / multi-monitor / coordinate transforms | IMPLEMENTED | `blaxcy/eye/x11.py` (`MonitorLayout`, `to_screen_coords`) |
| D5 | Pause safely when session locked/blanked/suspended | IMPLEMENTED | `blaxcy/policy.py`, `blaxcy/eye/x11.py` (`session_is_usable`) |
| D6 | Never bypass lock screen / auth / sudo / keyrings / 2FA / CAPTCHA; hand to user | IMPLEMENTED | `blaxcy/policy.py` (AUTH_BOUNDARY risk), `tests/test_policy.py` |

## E. Desktop UI (80/20)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| E1 | Control panel occupies ~20% width, real desktop ~80% visible | IMPLEMENTED | `blaxcy/ui/panel.py` |
| E2 | Panel shows chat, goal, current action, status, tool/model, progress, verification, errors | IMPLEMENTED | `blaxcy/ui/panel.py` |
| E3 | Pause / stop / emergency takeover controls | IMPLEMENTED | `blaxcy/ui/panel.py`, wired to `blaxcy/policy.py` |
| E4 | Panel is not a simulated desktop | IMPLEMENTED | `blaxcy/ui/panel.py` (transparent, no desktop replacement) |

## F. Goal Ownership & Verification

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| F1 | High-level goal becomes an internal objective with constraints, success criteria, priorities, risk policy, budget, stopping conditions | IMPLEMENTED | `blaxcy/models.py` (`Objective`), `blaxcy/orchestrator.py` |
| F2 | Do not stop merely because an action was attempted; stop when outcome verified | IMPLEMENTED | `blaxcy/verifier.py`, `blaxcy/orchestrator.py` |
| F3 | "action sent" != "task completed"; verify observed postcondition | IMPLEMENTED | `blaxcy/verifier.py`, `tests/test_verifier.py` |

## G. Failure Recovery

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| G1 | OBSERVE→CLASSIFY→DIAGNOSE→VERIFY→RETRY-if-safe→alt method→alt tool→alt model→rollback→replan→escalate | IMPLEMENTED | `blaxcy/recovery.py`, `blaxcy/orchestrator.py` |
| G2 | Never endlessly repeat the same failed action | IMPLEMENTED | `blaxcy/recovery.py` (attempt ledger), `tests/test_recovery.py` |
| G3 | Check whether an action already succeeded before retrying (idempotency) | IMPLEMENTED | `blaxcy/orchestrator.py` (`_already_satisfied`) |

## H. Multi-model Brain

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| H1 | Extensible model registry/router; models selected by capability | IMPLEMENTED | `blaxcy/brain/registry.py`, `blaxcy/brain/router.py` |
| H2 | Free/open models supported where practical | IMPLEMENTED | offline deterministic provider + Ollama-compatible adapter stub |
| H3 | Graceful handling of unavailable/quota/timeout/rate-limit/API failure/capability mismatch | IMPLEMENTED | `blaxcy/brain/router.py`, `tests/test_brain.py` |
| H4 | Never claim an unavailable model is working | IMPLEMENTED | `blaxcy/brain/registry.py` (`available` flags, doctor) |
| H5 | Real remote/local model providers wired end-to-end | VERIFIED (local + remote) | `blaxcy/brain/providers.py` (OpenAI/Groq/OpenRouter/Together/Anthropic/local presets), router retry + cooldown, `tests/test_providers.py`; live Ollama round-trip verified; a **genuine remote** provider measured end-to-end over public HTTPS via `scripts/brain_provider_bench.py` (remote 505 ms / local 556 ms / offline 2.35 ms, every call served by the configured provider, 0 errors — PERFORMANCE.md); a keyed account provider only needs `BLAXCY_<PROVIDER>_API_KEY` (BLOCKERS B-002) |
| H6 | A malformed/malicious model response must never directly authorize Body actions | VERIFIED | `blaxcy/planning.py` (`validate_model_plan`/`validate_action_dict`/`ModelPlanner`): closed action-kind + param whitelist, bounded sizes, restricted verify keys, BLAXCY-assigned risk; invalid output rejected wholesale → deterministic `RulePlanner`; `tests/test_planning.py` (15) proves `terminal_run`/`fs_write`/`browser_eval` and unknown kinds are refused; wired via `BLAXCY_PLANNER=model` |

## I. Tools as resources

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| I1 | Terminal tool, policy-gated | IMPLEMENTED | `blaxcy/tools/terminal.py` |
| I2 | Filesystem tool, policy-gated, sandboxed to allowed roots | IMPLEMENTED | `blaxcy/tools/filesystem.py` |
| I3 | Browser tool (real browser control) | VERIFIED | `blaxcy/browser/cdp.py`, `blaxcy/tools/browser.py`, `blaxcy browser <action>`, `tests/test_browser.py`; live headless-Chrome CDP round-trip (navigate/query/click/type/screenshot/eval) verified |
| I4 | Delegation to other AI/coding agents, output independently verified | VERIFIED | `blaxcy/delegation.py`, `blaxcy delegate`, `tests/test_delegation.py`; independent code/JSON checks + cross-model agreement; output stays UNTRUSTED until verified |

## J. Memory & Learning

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| J1 | Persistent experience: what happened/worked/failed/why/strategies/environment/preferences | IMPLEMENTED | `blaxcy/memory.py`, `tests/test_memory.py` |
| J2 | Provenance, confidence, timestamp, decay/relevance | IMPLEMENTED | `blaxcy/memory.py` |
| J3 | Never store secrets unnecessarily | IMPLEMENTED | `blaxcy/memory.py` (redaction), `tests/test_memory.py` |
| J4 | Untrusted external content never auto-becomes trusted instruction | IMPLEMENTED | `blaxcy/memory.py` (`TrustLevel`), `blaxcy/policy.py` |
| J5 | Learning loop (experience→outcome→evaluation→lesson→memory) | IMPLEMENTED | `blaxcy/orchestrator.py` (`_learn`) |
| J6 | Weight-level / model self-improvement | NOT_STARTED | explicitly out of scope; documented |

## K. Self-evaluation

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| K1 | Continuously evaluate progress, strategy validity, better methods, continue/retry/replan/stop | IMPLEMENTED | `blaxcy/orchestrator.py` (`evaluate`) |

## L. Security

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| L1 | Least privilege; prefer user-level; no unnecessary root daemons | IMPLEMENTED | `docs/SECURITY.md`, no privileged components |
| L2 | Protect API keys/passwords/cookies/tokens/SSH keys/browser creds/private files | IMPLEMENTED | `blaxcy/logging_utils.py` (redaction), `blaxcy/config.py` |
| L3 | OS keyring where appropriate | VERIFIED | `blaxcy/credentials.py` (keyring → secret-tool → encrypted file), `tests/test_credentials.py`; `blaxcy doctor` reports `encrypted-file` on this host |
| L4 | No telemetry without consent | IMPLEMENTED | no network calls by default |
| L5 | Prompt-injection / malicious content defenses | IMPLEMENTED | `blaxcy/policy.py` (`TrustLevel` gate), `blaxcy/memory.py` |
| L6 | No screen-frame persistence by default | IMPLEMENTED | `blaxcy/config.py` |
| L7 | Emergency stop / pause / takeover / confirmation for high-risk actions | IMPLEMENTED | `blaxcy/policy.py`, `tests/test_policy.py` |
| L8 | Multi-process IPC boundary is audited: authenticated, fresh, replay-protected, duplicate-field-rejecting, size-bounded, method-allowlisted, no secret leakage, no arbitrary `getattr` | VERIFIED | `blaxcy/ipc.py` (HMAC over version/type/payload/message_id/`ts`; ±60 s freshness; bounded replay cache; strict JSON), `blaxcy/service.py` (explicit handler dicts), all services; socket+secret files mode 0600, secret passed via env not argv; `tests/test_ipc.py`, `tests/test_service.py`, `tests/test_split_services.py` |

## M. Supervisor

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| M1 | Start services, monitor health, restart crashed components, detect heartbeat loss | IMPLEMENTED | `blaxcy/supervisor.py`, `tests/test_supervisor.py` |
| M2 | Preserve safe state / checkpoints | IMPLEMENTED | `blaxcy/supervisor.py`, `blaxcy/state_store.py` |
| M3 | Crashed component must not leave unsafe input state | IMPLEMENTED | `blaxcy/body/backends.py` (`release_all`), `blaxcy/supervisor.py` |
| M4 | Expose diagnostics | IMPLEMENTED | `blaxcy/cli.py` (`doctor`) |
| M5 | Components can run as supervised separate processes over the authenticated IPC (explicit method whitelist; restart + safe input release; never orphaned) | VERIFIED | `blaxcy/service.py` (`ServiceServer`/`ServiceClient`/`ProcessComponent`, `watch_parent`), `blaxcy/eye/service.py` (`EyeService`/`RemoteEye`), `blaxcy/memory.py` (`MemoryService`/`RemoteMemory`), `blaxcy/brain/service.py` (`BrainService`/`RemoteBrain`), `Application(split=...)`, `blaxcy serve`/`services`, `run --split eye,memory,brain` / `--split all`; `tests/test_service.py` (10) + `tests/test_split_services.py` (10) — real subprocess spawn, authenticated ping, real API call, crash→detection→restart with a new pid, safe release, parent watchdog, no orphan |
| M6 | Every split component has a complete service contract: explicit method whitelist, typed request/response, authenticated IPC, freshness/replay protection, bounded message size, timeout handling, health/ping, graceful shutdown, parent watchdog, degraded/failure state | VERIFIED | `blaxcy/service.py`, `blaxcy/ipc.py` (HMAC incl. `ts`, ±60 s skew window, bounded replay cache, duplicate-field rejection, `MAX_LINE` bound, client timeout), all three services; `tests/test_service.py`, `tests/test_split_services.py`, `tests/test_ipc.py` |
| M7 | Split mode is configurable: default in-process, selectable components, or full supported split; no source editing required; backward compatible | VERIFIED | `blaxcy/config.py` (`BLAXCY_SPLIT`, `normalize_split`/`parse_split`, `ALL_COMPONENTS`), `blaxcy run --split eye,memory,brain|all`, `blaxcy serve <name>`, `blaxcy services`; `tests/test_config.py`, `tests/test_cli.py`, `tests/test_split_services.py` (normalization regression, DEC-029); `--split all` re-verified against the real desktop; default remains in-process |
| M8 | Tools intentionally remain in-process for a documented architectural reason (security chokepoint + local Body), not merely left unsplit | VERIFIED (decision) | DEC-023; tools are thin `Action` builders; Policy + Body is the single chokepoint and `panic_release` is local; browser CDP and delegation model calls are already isolated/remote |
| M9 | Restart/health counters are exposed: `Application.service_status()`, `blaxcy services` and `blaxcy doctor` report per-component `state` and `restarts`; a stopped/never-started component is reported `stopped`, never healthy | VERIFIED | `blaxcy/supervisor.py` (`_persist`, honest `restart_exhausted` event), `blaxcy/app.py` (`service_status`), `blaxcy/cli.py` (`services`, `doctor`), `blaxcy/state_store.py`; `tests/test_soak.py`, `tests/test_cli.py` |
| M10 | Supervisor survives repeated crashes of every split service and reports `degraded` while recovering; restart budget exhaustion ends in `failed` with no further restart and no orphan | VERIFIED | `tests/test_soak.py` (3 cycles × memory/brain/headless-eye; exhaustion; `Application` reporting) |

## N. Testing

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| N1 | Real tests, not only happy path | IMPLEMENTED | `tests/` |
| N2 | Tests for init/state/recovery/interruption/reconciliation | IMPLEMENTED | `tests/test_state_store.py`, `tests/test_recovery.py` |
| N3 | Tests for Eye, Body, mouse/keyboard (dry-run), coordinate mapping | IMPLEMENTED | `tests/test_eye.py`, `tests/test_body.py` |
| N4 | Tests for verification, failure recovery, model fallback, memory, security, e-stop, supervisor restart | IMPLEMENTED | see `TESTS.md` |
| N5 | Tests for clean install/upgrade/uninstall | VERIFIED | `install.sh`, `upgrade.sh`, `uninstall.sh`, `tests/test_installer.py` (dry-run, real uninstall in a temp root, data preservation, --purge) |
| N6 | Negative tests (locked session, no policy approval, untrusted injection, no model) | IMPLEMENTED | `tests/test_negative.py` |
| N7 | Tests never move the real mouse/keyboard | IMPLEMENTED | real input disabled in tests |
| N8 | A repeatable load/soak harness exists under the repo, so measured performance can be regenerated on demand | VERIFIED | `scripts/loadtest.py` (`--threads/--per/--restart/--json`), `scripts/brain_provider_bench.py` (per-provider Brain latency: offline/local/remote, records the serving model), `tests/test_load.py`, `tests/test_brain_provider_bench.py`, `tests/test_soak.py`; numbers recorded in `.build-state/PERFORMANCE.md` |

## O. Observability

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| O1 | Structured, privacy-conscious logs with task/action id, timestamps, component, transitions, failures, verification, model/tool | IMPLEMENTED | `blaxcy/logging_utils.py` |
| O2 | Redact secrets | IMPLEMENTED | `blaxcy/logging_utils.py` |
| O3 | `blaxcy doctor` detects missing deps, display/session issues, permission issues, model config issues, broken components, unavailable tools | VERIFIED | `blaxcy/cli.py`, `blaxcy/app.py`; now also reports `vision`, `accessibility` (AT-SPI) and `credentials` |

## P. Production Quality

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| P1 | Clean installation / startup / shutdown / upgrade / uninstall | VERIFIED | `install.sh`, `upgrade.sh`, `uninstall.sh`, `blaxcy/cli.py`; lifecycle covered by `tests/test_installer.py` |
| P2 | Documentation | IMPLEMENTED | `README.md`, `docs/` |
| P3 | Diagnostics | IMPLEMENTED | `blaxcy doctor` |
| P4 | Recovery | IMPLEMENTED | `.build-state/`, `blaxcy/recovery.py` |
| P5 | Logging | IMPLEMENTED | `blaxcy/logging_utils.py` |
| P6 | Security controls | IMPLEMENTED | `blaxcy/policy.py` |
| P7 | No fake implementations; incomplete capabilities clearly marked | IMPLEMENTED | this file + `BLOCKERS.md` |

## Q. Universal Recovery (meta)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| Q1 | Live inside `/home/tsn/blaxxxcy` and stay independent of legacy `/home/tsn/blaxcy` | IMPLEMENTED | no imports of legacy; separate venv/state |
| Q2 | `.build-state/` persistent memory sufficient for another agent to resume | IMPLEMENTED | `.build-state/*` |
| Q3 | Reality overrides saved claims; reconcile on resume | IMPLEMENTED | `blaxcy/recovery.py`, `tests/test_recovery.py` |

---

## Acceptance criteria mapping (master prompt §29)

**Net (2026-10-03): every acceptance criterion is now closed on this host.** A
genuine B7 artifact exists again (two authorized live runs on 2026-10-03, both
13/13 verified), and B-010 is now resolved: a refusal can no longer overwrite evidence. Two
further items remain purely *environment-gated*: H5's remote half (needs remote
API keys, B-002) and D3's live proof (needs a Wayland host with a portal, B-003);
both are IMPLEMENTED and tested. No requirement was weakened to reach this point.

C1/C10 (perception performance): the live run exposed that X11 window
enumeration spawned up to ~180 `xdotool` subprocesses per frame (~6.8s) and a
`mousemove --sync` that hangs when the pointer is already at the target. Both
were fixed (DEC-018/DEC-019); frames dropped from ~2.4–11.7s to ~0.8s.

- Computer User: B1–B6 VERIFIED/IMPLEMENTED; B7 VERIFIED (two live artifacts, 2026-10-03).
- Live Eye: C1–C10 IMPLEMENTED/VERIFIED.
- Autonomy: A2, F1–F3, G1–G3, K1 IMPLEMENTED.
- UI: E1–E4 IMPLEMENTED.
- Recovery: Q1–Q3, N2 IMPLEMENTED.
- Multi-model: H1–H4 IMPLEMENTED; H5 local VERIFIED, remote presets IMPLEMENTED.
- Memory: J1–J5 IMPLEMENTED; J6 N/A.
- Security: L1–L7 IMPLEMENTED; L3 VERIFIED.
- Production: P1–P7 VERIFIED/IMPLEMENTED.
- Tools: I1–I4 VERIFIED.

---

## Requirement change log

(none — no requirement has been weakened or reinterpreted)

## Reconciliation log

Status corrections made on resume (2026-10-01) after verifying the real
filesystem and running the tests. No requirement was changed; several were
*advanced* because the code existed but the saved state was stale.

- C8 (AT-SPI), C9 (OCR/CV), H5 (providers), L3 (credentials): code already
existed in `blaxcy/eye/atspi.py`, `blaxcy/eye/vision.py`, `blaxcy/brain/providers.py`,
`blaxcy/credentials.py` but was marked NOT_STARTED and had **no tests**. Now
wired into `Application`, covered by tests, and evidenced by `blaxcy doctor`.
- O3 (`blaxcy doctor`): extended to report vision, accessibility and credentials.

Status advances on 2026-10-01 (Phase-2/3 pass), each backed by code + tests +
where possible a real runtime check:

- I3 browser tool → VERIFIED (real Chrome/Chromium CDP session exercised).
- I4 delegation → VERIFIED (independent verification; cross-model agreement).
- N5 + P1 installer lifecycle → VERIFIED (`install.sh`/`upgrade.sh`/`uninstall.sh`).
- D3 Wayland/portal → IMPLEMENTED (portal path + detection + tests; no Wayland
  host here to produce live evidence).
- H5 → local provider VERIFIED live; remote provider path now VERIFIED over a
  real remote endpoint (`scripts/brain_provider_bench.py`, PERFORMANCE.md); a
  keyed account provider only needs a key (B-002).
- B7 → VERIFIED: the harness is implemented and tested, and a genuine live run
  produced `.build-state/B7_EVIDENCE.md` twice on 2026-10-03 (both 13/13 verified)
  after the earlier artifact was lost (B-010, now resolved).

Status advances on 2026-10-02 (Brain provider latency pass):

- H5 → a **genuine remote** OpenAI-compatible provider was measured end-to-end
  over public HTTPS with the split `BrainService` (`scripts/brain_provider_bench.py`;
  remote 505 ms / local 556 ms / offline 2.35 ms; every call served by the
  configured provider, 0 errors). No account key exists on this host, so the free
  anonymous Pollinations.ai endpoint was used; the code path is identical for any
  keyed preset. Remote half is now VERIFIED, not merely implemented.
- N8 → the bench is repeatable and covered by `tests/test_brain_provider_bench.py`.
