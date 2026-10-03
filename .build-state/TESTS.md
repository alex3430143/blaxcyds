# BLAXCY — Test Log

A resuming agent MUST re-run the tests rather than trusting these entries.

## Test inventory (31 files, 247 tests)

| Test file | Covers | Requirement IDs |
|-----------|--------|-----------------|
| `tests/test_models.py` (6) | typed contracts, serialization, IPC version | B2, DEC-004 |
| `tests/test_state_store.py` (6) | atomic state, checkpoints, corruption | Q2, G3 |
| `tests/test_policy.py` (8) | risk classification, e-stop, pause, takeover, approval, auth boundary | B4, B5, D6, L7 |
| `tests/test_memory.py` (6) | persistence, provenance, redaction, expiry | J1–J4 |
| `tests/test_ipc.py` (9) | versioned messages, HMAC auth accept/reject, stale/`ts`-tamper rejection, replay rejection, duplicate-field rejection, correlation-id echo | DEC-004, L8, DEC-025 |
| `tests/test_eye.py` (9) | ScreenState, change detection, wait_for, freshness, latency, active-window-not-dropped-by-cap | C1–C6, C10 |
| `tests/test_body.py` (8) | typed actions, dry-run, timeout, failure, heartbeat, safe release, no hanging `--sync` | B1–B3, B5, B6 |
| `tests/test_brain.py` (6) | registry, capability routing, fallback, failure classes | H1, H3, H4 |
| `tests/test_verifier.py` (7) | postcondition verification, action-sent != done | F2, F3 |
| `tests/test_recovery.py` (8) | strategy chain, attempt ledger, resume/reconcile | G1, G2, Q3 |
| `tests/test_supervisor.py` (4) | heartbeat, restart, safe release, exhaustion | M1–M3 |
| `tests/test_orchestrator.py` (9) | goal→objective→plan→execute→verify→learn | A2, F1, J5, K1 |
| `tests/test_tools.py` (7) | policy-gated terminal/filesystem, write confinement | I1, I2 |
| `tests/test_cli.py` (7) | doctor / state / models / resume, `services` lists every component, doctor reports the split | O3, M4, M7 |
| `tests/test_negative.py` (8) | locked session, no approval, injection, no model | N6 |
| `tests/test_vision.py` (7) | OCR/CV on synthetic images, Eye vision hooks, degradation | C9 |
| `tests/test_atspi.py` (6) | AT-SPI nodes, cache/TTL, unavailable bus, summary | C8 |
| `tests/test_credentials.py` (6) | encrypted-file roundtrip, 0600 perms, no plaintext | L3 |
| `tests/test_providers.py` (15) | presets, retry/cooldown, adapter parse, live Ollama, router | H5 |
| `tests/test_browser.py` (13) | policy, backend dispatch, tool, real headless-Chrome CDP round-trip | I3 |
| `tests/test_delegation.py` (11) | verification helpers, delegation, cross-check, provenance | I4 |
| `tests/test_installer.py` (10) | install/upgrade/uninstall dry-run + real temp-root uninstall | N5, P1 |
| `tests/test_wayland.py` (10) | portal detection, portal protocol (fake bus), backend, selection | D3 |
| `tests/test_acceptance.py` (7) | B7 auth gate, verification, cursor restore, cleanup; a refusal records to `B7_EVIDENCE.refused.md` and never overwrites real evidence | B7, B-010 |
| `tests/test_config.py` (7) | `.env` parse, env precedence, dotenv→registry integration, `parse_split`, `BLAXCY_SPLIT`/`BLAXCY_ROOT` settings | H5, M7, DEC-020 |
| `tests/test_service.py` (10) | IPC service round-trip/auth/unknown-method, real subprocess spawn + stop, startup failure, crash→restart with safe release, parent watchdog, RemoteEye degradation | M5, M6, DEC-021 |
| `tests/test_split_services.py` (11) | real `blaxcy serve` subprocesses for Memory + Brain: authenticated ping, real API call, crash→detection→restart with a new pid, parent watchdog, down-service raises (never empty), ScreenState freshness/provenance over the wire, concurrent-caller integrity (DEC-026), `--split all` normalization (DEC-029), Application run with memory+brain split | M5, M6, M7, DEC-022, DEC-026, DEC-029 |
| `tests/test_planning.py` (17) | closed action/param whitelist, dangerous/unknown kinds rejected, BLAXCY-assigned risk, bounded sizes, model-plan fallback on invalid/unparseable/failed output | H6, DEC-024 |
| `tests/test_soak.py` (6) | supervisor soak: repeatedly crash **each** split service (memory/brain/headless-eye, 3 cycles) asserting heartbeat loss, safe release, new pid, `degraded` reporting and serving again; restart exhaustion → `failed`; `Application.service_status` reports state/restarts; persisted counters readable by `blaxcy services` | M1–M3, M9, DEC-027 |
| `tests/test_load.py` (1) | smoke test for the repeatable load harness `scripts/loadtest.py` (runs it at tiny scale, asserts zero errors and preserved integrity) | N8, DEC-028 |
| `tests/test_brain_provider_bench.py` (2) | smoke test for the per-provider Brain latency bench `scripts/brain_provider_bench.py`: runs the offline profile end-to-end at tiny scale (preferred provider served every call, zero errors, startup measured) and asserts the remote profile is skipped without credentials rather than faked | H5, N8, DEC-030 |

## Last run

- Command: `python3 -m pytest`
- Result: **247 passed**
  (183 → 185 live-run regressions → 189 `.env` → 199 process-split (Eye) →
  236 Memory+Brain split, planning validation, IPC security, config/CLI,
  concurrent-caller regression → 243 supervisor soak, load harness smoke →
  244 split-alias normalization regression → 246 Brain provider bench →
  247 acceptance-refusal evidence regression, B-010)
- Note (B-010, RESOLVED): the B7 evidence artifact had been overwritten by an
  unauthorized `accept-live` run. `blaxcy/acceptance.py` now writes refusals to
  `B7_EVIDENCE.refused.md`, the CLI test is isolated with `BLAXCY_ROOT`, and a
  regression test asserts a refusal never overwrites real evidence.
- 2026-10-03 (live acceptance, 08:03Z): **B7 VERIFIED (13/13 steps)** via
  `BLAXCY_ENABLE_REAL_INPUT=1 blaxcy accept-live` — real move/click/type, token
  `blaxcy-ef473f8a` confirmed in the target file, independent Eye confirmation,
  cursor restored. Artifact: `.build-state/B7_EVIDENCE.md`. The suite above
  remains 247 passing and still never moves the real mouse/keyboard.
- Environment: Python 3.14.6, X11, XFCE.
- Safety: no test moves the real mouse/keyboard. Perception uses fakes; control
  uses `DryRunBackend`; the B7 tests use a fake target/body/eye. The browser test
  launches a real *headless* Chrome (no display, no input). The Ollama test skips
  honestly when no local model is present. Service tests spawn real child
  processes in an isolated `BLAXCY_ROOT` temp dir; they never touch the real
  desktop and never use real input.

## Doctor run

- Command: `python -m blaxcy doctor`
- Result: OK. Adds `wayland`, `vision`, `accessibility`, `credentials`, `browser`.
  `real_input=disabled (dry-run)`.

## History

- 2026-10-01: initial suite, 99 passed.
- 2026-10-01: recovery pass — wired + tested vision/AT-SPI/credentials/providers
  (99 → 128).
- 2026-10-01: Phase-2/3 pass — I3 browser (13), I4 delegation (11), N5 installer
  (10), D3 Wayland (10), H5 provider presets/retry (5), B7 acceptance (6);
  128 → 183.
- 2026-10-01 (re-verification, 12:05Z): `python3 -m pytest` → **183 passed in
  26.62s**; `blaxcy doctor` OK; `blaxcy resume` no discrepancies. Saved claims
  matched reality. Also smoke-tested `blaxcy run` (dry-run, no real input).
- 2026-10-01 (live-acceptance, 12:35Z): **B7 VERIFIED (4/4 runs)** via
  `BLAXCY_ENABLE_REAL_INPUT=1 blaxcy accept-live`. Fixed two real defects (DEC-018
  pointer `--sync` hang; DEC-019 in-process Xlib window enumeration) and added a
  regression test for each; 183 → 185. `blaxcy doctor` OK; `resume` clean.
- 2026-10-01 (process split): added `blaxcy/service.py` + Eye service + RemoteEye
  (M5, DEC-021) with 10 tests that spawn real subprocesses; 189 → 199. Verified
  end-to-end: `Application(split=("eye",))` serves real `ScreenState` over IPC,
  and killing the service triggers `safe_release` + restart with a new pid.
- 2026-10-02 (multi-process pass): added `MemoryService`/`RemoteMemory` and
  `BrainService`/`RemoteBrain` (M5/M6, DEC-022), `blaxcy/planning.py` (H6,
  DEC-024), IPC freshness/replay/duplicate hardening (L8, DEC-025) and split
  config + CLI (M7). New tests: `tests/test_split_services.py` (8),
  `tests/test_planning.py` (17), +4 IPC, +3 config, +2 CLI, +2 state/IPC;
  199 → **235 passed**. Load testing then found a real concurrency defect
  (DEC-026: shared SQLite connection) and added a regression test → **236 passed**.
- 2026-10-02 (soak + tooling pass): added `tests/test_soak.py` (6) — a
  supervisor soak that crashes every split service repeatedly — and
  `tests/test_load.py` (1) for the new repeatable harness `scripts/loadtest.py`.
  Also made `check_once()` report `restart_exhausted` truthfully (DEC-027) and
  persisted the supervisor counters so `blaxcy services` can show them.
  236 → **243 passed**. Then inspecting the persisted supervisor counters exposed
  that `blaxcy run --split all` was a silent no-op (DEC-029); fixed and
  re-verified, +1 regression → **244 passed**.
  Verified end-to-end: `blaxcy run --split all` (real X11 Eye + Memory + Brain
  over IPC) completed with no orphan processes; `blaxcy services` reports
  `stopped` / `degraded` / `running` honestly.
- 2026-10-02 (Brain provider latency pass): added `scripts/brain_provider_bench.py`
  (spawns the real Brain service per provider profile; records wall + provider
  duration and the model that actually served each call) and
  `tests/test_brain_provider_bench.py` (2). Measured a **genuinely remote**
  OpenAI-compatible provider over public HTTPS (Pollinations.ai free tier, no
  account key on this host — B-002): remote 505 ms vs local Ollama 556 ms vs
  offline 2.35 ms sequential median, and under 4x4 concurrency local serialized
  (1848 ms) while remote stayed flat (511 ms); 0 errors, every call served by the
  configured provider. 244 → **246 passed**. `blaxcy doctor` OK; `resume` clean.
