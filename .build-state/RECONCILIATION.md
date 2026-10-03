# BLAXCY — Codebase Reconciliation

Three local BLAXCY trees existed and had diverged. This file records which one is
authoritative, what the others contain, and what to do with each, so that future
work cannot scatter across them again.

Verified against the real filesystem and git on **2026-10-03**.

## The three trees

| Tree | Role | Git remote | Branch | Commits | Last commit | Source LOC* | Tests** |
|---|---|---|---|---|---|---|---|
| `/home/tsn/blaxxxcy` | **CANONICAL** | `alex3430143/blaxcyds` (public) | `main` | 2 + tag `v1.0.0` | 2026-10-03 | ~9.0k | 247 funcs — **247 passing** |
| `/home/tsn/blaxcy` | superseded — legacy (Phase 15) | `tasinxxx/blaxcy` | `master` | 24 | 2026-09-27 | ~34.6k | ~1979 funcs (not re-run) |
| `/home/tsn/blaxxcy` | superseded — prior attempt | `tasinxxx/blaxcy` | `main` | 10 | 2026-10-02 | ~9.5k | ~184 funcs (not re-run) |

\* non-test `.py` lines, excluding `.venv` / `.runtime`.
\*\* test-function count; only the canonical tree's suite is re-run and green
(`python -m pytest -q` → **247 passed**, verified this session).

### Hazard: two trees share one remote

`/home/tsn/blaxcy` and `/home/tsn/blaxxcy` **both** point `origin` at
`github.com/tasinxxx/blaxcy`, yet their histories are unrelated (different commit
sets). Pushing from either can clobber the other and the remote's current `HEAD`.
**Do not push from those trees.** Neither is the source of truth.

## Decision

**Canonical source of truth: `/home/tsn/blaxxxcy` → `github.com/alex3430143/blaxcyds`.**

Why this one:

- Most recent and most tested work (247 green tests plus a genuine B7
  live-acceptance artifact, verified 2026-10-03).
- A complete, installable package: one-line installer, PEP 639 metadata with
  declared extras, CI, LICENSE, and the docs a production repo needs.
- Written from scratch after the two earlier trees, already carrying the
  build-state / requirements / blockers discipline they lacked.
- It is the tree selected for publication and already released as `v1.0.0`.

`/home/tsn/blaxcy` and `/home/tsn/blaxxcy` are **frozen, reference-only**. Do not
import from them, push from them, or start new work in them.

## What the superseded trees uniquely contain

### `/home/tsn/blaxcy` (legacy)

The deepest perception/safety surface, on a much larger codebase:

- `core/visual_grounder.py` — remote-vision grounding, the last perception fallback.
- `core/target_resolver.py` — ranked target resolution, element leases, occlusion.
- `core/speculative_perceiver.py` — perception warm-up inside a sequence.
- `core/calibration.py` — observed desktop↔input-space fit per monitor.
- `core/single_instance.py` — refuse a second Body on one desktop.
- `watchdog/` — run-life and input-ownership journal.
- `relay/` + `bridge/` — GitHub-relay remote task execution (phases 2A/2B).
- `ai/` multi-adapter Brain and a `schemas/` typed contract stack; Python `installer/`.

### `/home/tsn/blaxxcy` (prior attempt)

- `blaxcy/tools/research.py` — network-gated web research with SSRF/private-range guards.
- `blaxcy/eye/semantic.py` — typed, bounded semantic observation assembly.
- `blaxcy/eye/change_regions.py` — native XDamage region subscription.
- `blaxcy/eye/metrics.py`, `blaxcy/eye/rate.py` — perception metrics and rate.
- `blaxcy/brain/planner.py` — conservative deterministic planner (canonical:
  `blaxcy/planning.py`, which additionally validates model output).

## Port-back candidates (backlog — none required for 1.0.0)

Ordered by value to the canonical tree:

1. **Single-instance guard** (`single_instance`) — safety. Two Bodies on one
   desktop can each hold input; the canonical tree has no such guard.
2. **Observed coordinate calibration** (`calibration`) — the canonical tree
   assumes a direct desktop↔input mapping; calibration makes HiDPI and
   multi-monitor correctness provable rather than assumed.
3. **Network-gated research tool** (`tools/research.py`) — the canonical tree has
   no research tool. Any port must keep the SSRF/private-range guards and tag
   results `UNTRUSTED`.
4. **Ranked target resolution + element leases/occlusion** (`target_resolver`) —
   the canonical tree resolves a single fresh confident element; this is a ranked
   cascade.
5. **Remote-vision grounding fallback** (`visual_grounder`) — the canonical tree is
   local OCR/CV only. This adds remote pixel egress, so it needs explicit privacy
   rules and opt-in.
6. **Run watchdog with an input-ownership journal** (`watchdog`) — the canonical
   tree has `watch_parent` plus supervisor safe-release; this is a richer crash
   record.

**Deliberately not ported:** `relay/` and `bridge/` remote task execution. They add
a network *execution* surface the canonical scope does not need; decision B-009
keeps the IPC transport local-only.

## Rules going forward

- New work happens **only** in `/home/tsn/blaxxxcy`, pushed to `alex3430143/blaxcyds`.
- `tasinxxx/blaxcy` is a legacy remote; **do not push to it**.
- To bring back a legacy capability, port it into the canonical package with
  canonical tests. Never merge whole trees, and never resurrect a superseded tree
  to "continue" it.
