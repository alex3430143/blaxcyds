# BLAXCY Architecture

## Identity and Direction Lock

BLAXCY is **an AI like a human computer user**. It perceives a real Linux
desktop, decides, physically acts, observes, verifies, recovers, and learns.

The project must never drift into being: a normal chatbot, a simple coding
agent, a browser-only automation tool, a headless automation framework, a
screenshot macro tool, a glorified terminal wrapper, or a model wrapper with no
real computer control. Browsers, terminals, files and models are **tools BLAXCY
uses**, not what BLAXCY is.

## Component map

```
USER → GUI (~20% panel) → ORCHESTRATOR
                             ├── BRAIN      blaxcy/brain/      registry + router
                             ├── EYE        blaxcy/eye/        live perception
                             ├── MEMORY     blaxcy/memory.py   SQLite experience
                             └── TOOLS      blaxcy/tools/       terminal, filesystem
                                    ↓
                                 POLICY     blaxcy/policy.py    risk chokepoint
                                    ↓
                                  BODY      blaxcy/body/        real input + system
                                    ↓
                            REAL LINUX DESKTOP
                                    ↓
                    OBSERVATION → VERIFICATION (blaxcy/verifier.py) → LEARNING
                                    └──────────────────────────────► ORCHESTRATOR
```

Supporting: `app.py` (wiring/lifecycle), `supervisor.py` (health/restart),
`service.py` (supervised process split), `state_store.py` (atomic persistence),
`recovery.py` (failure + resume), `ipc.py` (authenticated transport),
`logging_utils.py` (redacted logs), `cli.py`.

## Data flow

1. `Orchestrator.run(goal)` builds an `Objective` (constraints, success criteria,
   budget, stopping conditions).
2. A planner (`RulePlanner`, replaceable) produces a `Plan` of `PlanStep`s, each
   with typed `Action`s and an optional `verify` postcondition.
3. Each action goes to `Body.execute`, which calls `Policy.check`. Blocked
   actions return `ActionResult(status=BLOCKED)` and never reach a backend.
4. The chosen backend performs the action: `DryRunBackend` (default) or the real
   `AutoBackend` (X11 input + system terminal/filesystem).
5. `Verifier` checks the declared postcondition against live `ScreenState`.
   Failure triggers `RecoveryManager` (retry → alt method/tool/model → replan →
   escalate) without endlessly repeating the same action.
6. Outcomes are written to `Memory` and `.build-state/`; the loop continues until
   criteria are verified or the budget/escalation stopping conditions hit.

## Contracts

All cross-component messages are dataclasses in `blaxcy/models.py` and are
JSON-serializable (`IPC_VERSION`). This is what lets components run in-process
or in supervised processes with no redesign.

## Process split (supervised services)

Components can run **in their own process** behind the authenticated IPC. The
runtime lives in `blaxcy/service.py`:

- `ServiceServer` serves a component's methods over a Unix socket with an
  **explicit method whitelist** (never arbitrary `getattr`).
- `ServiceClient` is the matching caller; it signs every message with the local
  shared secret (`Settings.ipc_secret()`, mode 0600).
- `ProcessComponent` spawns `python -m blaxcy serve <name>`, waits until the
  service answers an authenticated `ping`, reports health, and is registered with
the existing `Supervisor` — so a crashed service is restarted and the Body is
forced to release any held input first. If the supervisor dies unexpectedly the
child exits on its own (`watch_parent`), so services are never orphaned.

Three components can run split: the **Eye** (`blaxcy/eye/service.py`),
**Memory** (`blaxcy/memory.py`: `MemoryService`/`RemoteMemory`) and **Brain**
(`blaxcy/brain/service.py`: `BrainService`/`RemoteBrain`). Each `Remote*` mirrors
its in-process API, and one process owns the SQLite file so there are no
cross-process write races. `RemoteMemory`/`RemoteBrain` have **no silent
fallback**: a down service raises and is reported as degraded, so missing data is
never mistaken for an empty (valid) result. Enable a subset with
`blaxcy run --split eye,memory,brain "..."` (or `--split all`, or the
`BLAXCY_SPLIT` env var); `blaxcy services` shows each component's mode/pid/health
and `blaxcy serve <name>` runs one in the foreground. The default remains
fully in-process.

**Tools remain in-process by design** (DEC-023): they are thin `Action` builders,
and Policy + Body is the single security chokepoint whose `panic_release` is bound
to the local session. Isolating them would let arbitrary `Action`s be built
outside Policy's view with no performance win; the expensive/remote parts
(browser CDP, delegation model calls) are already separate.

### IPC security

The IPC layer (`blaxcy/ipc.py`) is authenticated and strict: an HMAC over
`version/type/payload/message_id/ts`, a ±60 s freshness window, a bounded replay
cache, duplicate-JSON-field rejection, a line-size bound and a client timeout.
The secret file and socket are mode 0600 and the secret is passed to children via
the environment, never a command line.

### Model → action boundary

A model only ever returns text. `blaxcy/planning.py` (`validate_model_plan`)
parses it into a typed `Plan` through a closed action-kind + parameter whitelist
with BLAXCY-assigned risk classes; anything invalid is rejected and the
deterministic `RulePlanner` takes over. Accepted actions still pass Policy, so a
malformed or malicious model response can never authorize Body actions.

### Supervision, counters and the load harness

The `Supervisor` restarts a crashed service with a new pid and releases held
input first. It reports `degraded` while a component is running but recently
unhealthy, and `failed` once its restart budget is exhausted — emitting
`restart_exhausted`, never a false `restarted`. Counters (`state`, `restarts`,
`last_error`) are persisted and surfaced by `blaxcy services` and
`blaxcy doctor`. `scripts/loadtest.py` spawns the real services and reproduces
the concurrency and restart-under-load numbers recorded in
`.build-state/PERFORMANCE.md`; `tests/test_soak.py` crashes every split service
repeatedly and asserts the full contract. `scripts/brain_provider_bench.py`
measures Brain latency per provider profile (offline / local / remote), spawning
the real service for each and recording which model actually served every call,
so a fallback to a different provider cannot be mistaken for the configured one.

## Extension points (keep it upgradeable)

- **Models**: register a `ModelSpec` + provider in `brain/registry.py`; the
  router picks by capability. Better models replace older ones without redesign.
- **Perception**: alternate `EyeBackend`s (X11 today; Wayland/portal, XDamage,
  AT-SPI, OCR/CV later) satisfy the same `snapshot()` protocol.
- **Control**: alternate `BodyBackend`s (X11 today; uinput, Wayland virtual
  input later) satisfy `perform()` / `release_all()`.
- **Planners**: replace `RulePlanner` with a model-backed planner.

## Honesty rule

A capability that is not actually working is marked `NOT_STARTED` or `BLOCKED`
in `.build-state/REQUIREMENTS.md` — never faked. See also `docs/SECURITY.md`.
