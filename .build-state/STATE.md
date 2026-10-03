# BLAXCY — Build State

## Project identity

BLAXCY is a new, independent Linux desktop computer-use application built from
zero in `/home/tsn/blaxxxcy`. It is "an AI like a human computer user": it sees
the real desktop, decides, physically acts, observes, verifies, recovers and
learns. `/home/tsn/blaxcy` (legacy) and `/home/tsn/blaxxcy` (prior attempt) are
reference-only and are never modified or imported.

## Current status

- Lifecycle: EXISTING PROJECT — multi-process architecture pass (2026-10-02).
- Phase: Phase 1 complete; Phase 2 complete; Phase 3 multi-process work complete
  for the components that benefit from isolation.
- Active task: none in progress. All on-host acceptance criteria are met.
- Verified (2026-10-02, from the real filesystem): `python3 -m pytest` →
  discrepancies; **B7 live acceptance → VERIFIED 2026-10-03 (13/13 steps, two
  consecutive authorized runs)** → `.build-state/B7_EVIDENCE.md`;
  **Eye, Memory and Brain all run as supervised subprocesses serving real data
  over authenticated IPC, restarting on crash** (DEC-021, DEC-022); full split
  `blaxcy run --split all` verified end-to-end against the real X11 desktop;
  model output can never authorize Body actions (DEC-024); IPC hardened for
  freshness/replay/duplicate fields (DEC-025).
- Last safe checkpoint: see `CHECKPOINT.md`
- Overall: **B7 is VERIFIED (artifact 2026-10-03) and the multi-process
  architecture is implemented and verified for Eye/Memory/Brain.** Tools intentionally remain in-process with a
  documented rationale (DEC-023). A **genuine remote provider** was measured for
  the Brain service over public HTTPS (remote 505 ms / local 556 ms / offline
  2.35 ms; `scripts/brain_provider_bench.py`, PERFORMANCE.md, DEC-030). One
  evidence item remains purely environment-gated — D3's live proof (needs a
  Wayland host, B-003), still implemented and tested.

## Reality verification (re-verify on every resume)

- Target `/home/tsn/blaxxxcy` exists and contains this project (no git repo here).
- Legacy `/home/tsn/blaxcy` and prior attempt `/home/tsn/blaxxcy` were only read.
- Runtime: Python 3.14.6, X11 `DISPLAY=:0.0`, XFCE, 1366x768.
- Live capabilities on this host: AT-SPI (2 windows), Tesseract 5.5.0 + OpenCV,
  local Ollama (`tinyllama:latest`) round-trip, `encrypted-file` credentials,
  Chrome/Chromium + `websocket-client` for real browser control (verified live),
  `xterm`/`xdotool` for the B7 harness. `xdg-desktop-portal` is absent (X11).
- See `ENVIRONMENT.md`.

## What is implemented and verified

- **Identity/autonomy**: orchestrator goal→objective→plan→execute→verify→learn.
- **Eye**: X11 continuous sampler (in-process Xlib metadata; ~0.8s frames);
  AT-SPI; local OCR/CV; Wayland portal path.
- **Body**: typed actions, dry-run default, X11 real input, safe release.
- **Policy**: single risk chokepoint; e-stop/pause/takeover; auth boundaries.
- **Tools**: terminal, filesystem, **real browser (CDP)**, **delegation**.
- **Brain**: registry/router, capability routing, retry + cooldown, real
  providers (OpenAI/Groq/OpenRouter/Together/Anthropic/local), honest availability;
  project-local `.env` key loading (DEC-020), so `blaxcy models` picks up a key;
  genuine remote provider measured end-to-end over public HTTPS (DEC-030).
- **Memory/learning**, **supervisor**, **IPC**, **logging/redaction**, **doctor**.
- **Process split**: generic `ServiceServer`/`ServiceClient`/`ProcessComponent`
  + `watch_parent` (`blaxcy/service.py`); split components are the **Eye**
  (`blaxcy/eye/service.py`, `RemoteEye`), **Memory** (`blaxcy/memory.py`,
  `MemoryService`/`RemoteMemory`) and **Brain** (`blaxcy/brain/service.py`,
  `BrainService`/`RemoteBrain`). Configurable via `BLAXCY_SPLIT`/`--split
  eye,memory,brain|all`; default remains fully in-process. Supervised with
  restart + safe input release + parent watchdog (M5, M6, M7, DEC-021/022).
- **Planning boundary**: `blaxcy/planning.py` validates any model plan against a
  closed action/param whitelist with BLAXCY-assigned risk; invalid output falls
  back to the deterministic planner (H6, DEC-024).
- **IPC hardening**: HMAC over timestamp, ±60 s freshness window, bounded replay
  cache, duplicate-field rejection, `IPC_VERSION=2` (L8, DEC-025).
- **Production**: install/upgrade/uninstall lifecycle with tests.

## Safety posture

- Real input is dry-run by default; requires `BLAXCY_ENABLE_REAL_INPUT=1` AND
  Policy approval. Browser control is a tool (no mouse/keyboard) and is risk-gated
  per action (arbitrary page JS is HIGH and needs explicit opt-in).
- B7's live test refuses to run without the real-input flag, and is reversible.
- Screen frames are not persisted to disk by default.
- Secrets are redacted; credentials use the keyring chain (encrypted-file here).

## Remaining (all environment-gated, not code defects)

1. H5 remote live call — the remote path is now VERIFIED via a free remote
   endpoint (`scripts/brain_provider_bench.py`); a specific *account* provider
   still needs a key (B-002).
2. D3 live evidence — needs a Wayland host with a portal (B-003). Implemented
   and tested against a fake portal bus; cannot be exercised on this X11 host.
3. B7 is **verified** — its artifact was regenerated on 2026-10-03 (B-010
   resolved); re-run `BLAXCY_ENABLE_REAL_INPUT=1 blaxcy accept-live` to refresh it.

## Public release (2026-10-03)

- Packaged for public distribution as `alex3430143/blaxcyds`; version bumped to
  `1.0.0`.
- `pyproject.toml` now has full PEP 639 metadata and optional-dependency extras
  (`control`, `ui`, `vision`, `security`, `browser`, `all`, `dev`) that declare
  every third-party import in the source, so a clean install no longer depends on
  undeclared packages. Build metadata uses setuptools>=77.
- Added a one-line remote installer (`install.sh` bootstrap via `curl | bash`)
  with a `~/.local/bin/blaxcy` launcher, `LICENSE` (MIT), `CHANGELOG.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, CI
  (`.github/workflows/ci.yml`), issue/PR templates, `.editorconfig`,
  `.gitattributes`, and `.env.example`.
- Fixed a real defect found by Ruff: `Any` was used in annotations in
  `blaxcy/eye/x11.py` without being imported (masked at runtime only by
  `from __future__ import annotations`).
- Corrected stale `docs/SECURITY.md` "not implemented" gaps that were already
  implemented (credentials L3, AT-SPI C8, OCR/CV C9); the section now lists the
  genuinely remaining gaps.
- Post-packaging verification: 247 tests pass in the project `.venv`; a real
  `./install.sh --dev` succeeds; `ruff check --select E9,F63,F7,F82` is clean;
  `compileall` and `bash -n` on all scripts are clean.
- Declared the **single canonical source of truth** (DEC-031): `/home/tsn/blaxxxcy`
  → `github.com/alex3430143/blaxcyds`. The two earlier trees (`/home/tsn/blaxcy`
  legacy, `/home/tsn/blaxxcy` prior attempt) are frozen and reference-only; two of
  them shared the `tasinxxx/blaxcy` remote with unrelated histories, so do not push
  from them. Inventory and port-back backlog: `RECONCILIATION.md`.
- Evidence integrity (B-010, now RESOLVED): fixed the bug where an unauthorized
  `accept-live` run overwrote the real B7 artifact, then **regenerated genuine B7
  evidence** — two authorized live runs with real input on 2026-10-03 (08:03:14Z
  and 08:11:51Z), each 13/13 steps, `verified: True` →
  `.build-state/B7_EVIDENCE.md` holds the latest. The suite is now 247 tests.

## How to resume

1. Read every file in `.build-state/`.
2. Inspect the real filesystem and git state.
3. Read `TESTS.md`, then run `python -m pytest -q` and `python -m blaxcy doctor`.
4. Reconcile saved claims against reality; update these files if they disagree.
5. Continue from `CHECKPOINT.md` → "Safe resume action", using `PLAN.md`.
