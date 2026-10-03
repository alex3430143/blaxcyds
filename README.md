# BLAXCY

**An AI like a human computer user.**

[![CI](https://github.com/alex3430143/blaxcyds/actions/workflows/ci.yml/badge.svg)](https://github.com/alex3430143/blaxcyds/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-246%20passing-brightgreen.svg)](#development)

BLAXCY owns a high-level goal, observes the **real** Linux desktop, decides what
to do, physically acts on the machine, observes the result, verifies success,
recovers from failure, learns from experience, and keeps working until the
goal's success criteria are genuinely met.

It is **not** a chatbot, a terminal wrapper, a browser bot, a screenshot macro,
or a thin wrapper around a language model. Those are tools BLAXCY *uses*.

```text
USER GOAL
   ↓
UNDERSTAND → PLAN → OBSERVE REAL DESKTOP → POLICY CHECK → REAL ACTION
   ↓                                                          ↓
   └────────────── VERIFY SUCCESS ← OBSERVE RESULT ←──────────┘
          │
          └── on failure → DIAGNOSE → ADAPT → SAFE RETRY / ALTERNATIVE → VERIFY
```

---

## Install

One line — downloads the source, builds an isolated environment, installs the
`blaxcy` command, and creates a launcher on your `PATH`:

```bash
curl -fsSL https://raw.githubusercontent.com/alex3430143/blaxcyds/main/install.sh | bash
```

Prefer to read before you run? Download it, review it, then execute:

```bash
curl -fsSL https://raw.githubusercontent.com/alex3430143/blaxcyds/main/install.sh -o install.sh
less install.sh          # read it
bash install.sh
```

The installer is **user-level and least-privilege**: it never uses root, never
writes outside `~/.local/share/blaxcy` and `~/.local/bin`, and touches no other
directory. Then:

```bash
blaxcy doctor            # detect environment / session / capability problems
blaxcy ui                # the ~20% control panel (real desktop stays ~80% visible)
```

### Install options

```text
./install.sh --root DIR     install from DIR instead of this script's directory
./install.sh --prefix DIR   where a remote install downloads the source
./install.sh --minimal      install only the core package
./install.sh --dev          also install the development extras
./install.sh --dry-run      print exactly what would happen; change nothing
```

Uninstall and upgrade are equally clean; user data is preserved unless you ask:

```bash
./upgrade.sh                 # re-install in place, keeping .runtime/ and .build-state/
./uninstall.sh --yes         # remove the install, keep your data
./uninstall.sh --yes --purge # remove everything, including data
```

---

## What BLAXCY actually does

| Capability | Implementation | Status |
|---|---|---|
| **Real computer control** | X11 XTEST via `python-Xlib` / `PyAutoGUI` / `xdotool`: move, click, double/right-click, drag, scroll, type, hotkeys, window switch, app launch | Verified live |
| **Live Eye** | Near-continuous desktop sampler: frames, change/damage detection, active window, cursor, AT-SPI accessibility, Tesseract OCR + OpenCV CV, latency p50/p95 | Verified live |
| **Policy chokepoint** | Every action risk-classified; auth boundaries (sudo, keyring, 2FA, CAPTCHA, lock screen) never auto-performed | Verified |
| **Verification** | Postconditions checked against the live `ScreenState`; "action sent" ≠ "task done" | Verified |
| **Failure recovery** | Idempotent re-check → retry → alternative method/tool/model → replan → escalate, with an attempt ledger that never repeats a dead action forever | Verified |
| **Multi-model Brain** | Extensible registry + capability router (OpenAI, Groq, OpenRouter, Together, Anthropic, local Ollama, offline deterministic), retry/cooldown, honest availability | Local + remote verified |
| **Model → action boundary** | A model only ever returns text; output is validated against a closed action/param whitelist, then still passes Policy | Verified |
| **Tools** | Policy-gated terminal, filesystem (sandboxed writes), and a real browser over Chrome DevTools Protocol | Verified live |
| **Memory** | Persistent SQLite experience with provenance, confidence, decay, and secret redaction | Verified |
| **Supervisor** | Health, restart with safe input release, orphan prevention, crash recovery | Verified |
| **IPC** | HMAC-authenticated Unix socket: freshness window, replay cache, size bounds, explicit method whitelist | Verified |
| **GUI** | PyQt6 control panel (~20% width): goal, action, status, model/tool, verification, errors, pause/stop/takeover | Verified (offscreen CI) |

The full, itemised requirements lock — with evidence for every line — lives in
[`.build-state/REQUIREMENTS.md`](.build-state/REQUIREMENTS.md). Nothing is
claimed complete that was not observed.

---

## Architecture

```text
USER → GUI (~20% panel) → ORCHESTRATOR
                             ├── BRAIN      blaxcy/brain/       registry + router
                             ├── EYE        blaxcy/eye/         live perception
                             ├── MEMORY     blaxcy/memory.py    SQLite experience
                             └── TOOLS      blaxcy/tools/        terminal, fs, browser
                                    ↓
                                 POLICY     blaxcy/policy.py     single risk chokepoint
                                    ↓
                                  BODY      blaxcy/body/         real input + system
                                    ↓
                            REAL LINUX DESKTOP
                                    ↓
                    OBSERVATION → VERIFICATION → LEARNING
                                    └──────────────────────────► ORCHESTRATOR
```

Supporting modules: `app.py` (wiring/lifecycle), `supervisor.py` (health/restart),
`service.py` (supervised process split), `state_store.py` (atomic persistence),
`recovery.py` (failure + resume), `ipc.py` (authenticated transport),
`logging_utils.py` (redacted logs), `cli.py`.

Components can run **in-process (default)** or as **supervised subprocesses**
behind the authenticated IPC — `--split eye,memory,brain` (or `--split all`).
Eye, Memory and Brain are individually splittable; Tools stay in-process by
design because Policy + Body is the single security chokepoint. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Usage

```bash
blaxcy doctor                     # environment / session / capability report
blaxcy state                      # persistent project and task state
blaxcy resume                     # resume / reconcile protocol after an interruption
blaxcy models                     # configured models and honest availability
blaxcy tools                      # available tools
blaxcy run "open a text editor and type hello"
blaxcy run --split all "..."      # run with Eye + Memory + Brain as supervised processes
blaxcy services                   # component mode / pid / health / restart counters
blaxcy serve eye                  # run one component in the foreground
blaxcy browser status             # real Chrome/Chromium over CDP (policy-gated)
blaxcy delegate "summarise this"  # delegate to another model and verify the result
blaxcy accept-live                # supervised, reversible live-desktop acceptance test
blaxcy ui                         # control panel
```

### Safety model

- **Dry-run by default.** The Body only touches the real mouse/keyboard when
  `BLAXCY_ENABLE_REAL_INPUT=1` **and** Policy approves the specific action.
  A dry-run preview is never reported as a completed goal.
- **Emergency stop, pause, user takeover** are first-class controls.
- **Auth boundaries are never bypassed** — lock screens, sudo/polkit, keyrings,
  2FA and CAPTCHA are handed to you.
- **No screen frames are persisted by default**; logs and memory are redacted.
- **No telemetry.** No network call happens unless you configure a model
  provider and use it.

Read the full posture in [`docs/SECURITY.md`](docs/SECURITY.md) and
[`SECURITY.md`](SECURITY.md).

---

## Requirements

- Linux with **Python 3.11+**.
- A desktop session: **X11** is fully supported today. **Wayland** capture/input
  go through the XDG portals (ScreenCast / RemoteDesktop + PipeWire) where the
  session advertises them.
- Optional system packages for the richest perception:
  `tesseract-ocr`, `tesseract-ocr-eng`, `xdotool`, `xclip`, `wmctrl`, and the
  AT-SPI stack (`python3-gi`, `gir1.2-atspi-2.0`, `at-spi2-core`).
- Optional: `git` (for the one-line installer) and a Chrome/Chromium binary for
  browser control.

BLAXCY reports what the machine *can* do, honestly, and refuses to claim
anything it has not probed.

---

## Configuration

Settings are read from environment variables, with safe defaults; a project
`.env` may hold secrets (it is git-ignored). Real environment variables always
win.

| Variable | Purpose | Default |
|---|---|---|
| `BLAXCY_ENABLE_REAL_INPUT` | Master gate for live mouse/keyboard control | unset (dry-run) |
| `BLAXCY_MAX_RISK` | Highest action risk Policy will permit | `medium` |
| `BLAXCY_SPLIT` | Components to run as supervised processes | empty (in-process) |
| `BLAXCY_PLANNER` | `rules` (deterministic) or `model` (validated) | `rules` |
| `BLAXCY_HOME` | Install/data directory | `~/.local/share/blaxcy` |
| `BLAXCY_ROOT` | Override the project root for runtime data | the checkout |

**Model providers** are configured per provider; the API key is resolved from the
OS credential store first and an environment fallback second. Each provider has
`BLAXCY_<PROVIDER>_API_KEY`, `..._BASE_URL`, and `..._MODEL`
(`OPENAI`, `GROQ`, `OPENROUTER`, `TOGETHER`, `ANTHROPIC`), plus `BLAXCY_LOCAL_BASE_URL`
for a local Ollama-compatible endpoint. See
[`.env.example`](.env.example) and [`blaxcy models`](#usage).

---

## Development

```bash
git clone https://github.com/alex3430143/blaxcyds.git
cd blaxcyds
./install.sh --dev
source .venv/bin/activate

python -m pytest -q          # 246 tests; never move the real mouse or keyboard
python -m compileall -q blaxcy tests
blaxcy doctor --json
```

Tests use fake Eye/Body adapters and are structurally prevented from injecting
real input. The suite runs under Xvfb in CI on Python 3.11, 3.12 and 3.13. See
[`CONTRIBUTING.md`](CONTRIBUTING.md) and [`.build-state/TESTS.md`](.build-state/TESTS.md).

---

## Status

`1.0.0` — a tested, documented Linux computer-use agent. On this project's
reference host (X11): **246 tests pass**, `blaxcy doctor` is clean, the live
desktop acceptance test (B7) is verified, and per-provider Brain latency is
measured and recorded in [`.build-state/PERFORMANCE.md`](.build-state/PERFORMANCE.md).

Two evidence items remain **environment-gated rather than code-incomplete**, and
are stated plainly rather than faked:

- **Wayland live proof** needs a Wayland host with an XDG portal. The portal
  path is implemented and unit-tested against a fake portal bus.
- **A specific keyed account provider** needs a real API key.

See [`.build-state/BLOCKERS.md`](.build-state/BLOCKERS.md) for the complete,
honest list.

---

## License

[MIT](LICENSE) © BLAXCY contributors.
