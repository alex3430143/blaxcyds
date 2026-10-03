# BLAXCY — Environment

Captured during first execution on 2026-10-01. Re-verify with `blaxcy doctor`.

## Host

- User: `tsn`
- OS: Linux, XFCE desktop
- Shell: bash

## Directory layout (IMPORTANT — three similarly named folders exist)

| Path | Role | Touched? |
|------|------|----------|
| `/home/tsn/blaxxxcy` | **NEW BLAXCY (this project, 3 x's)** | written |
| `/home/tsn/blaxxcy` | prior agent attempt of the same task (2 x's + cy) | read-only |
| `/home/tsn/blaxcy` | legacy BLAXCY project | read-only |

Do not confuse them. Only `/home/tsn/blaxxxcy` belongs to this build.

> Observation (2026-10-01): a separate agent process (`kirocrew`, via pipx) is
> running on this host and has been writing a `.venv` into `/home/tsn/blaxxcy`.
> That activity is **not** part of this build and this project never touches
> `/home/tsn/blaxxcy`. If you are resuming, be aware another actor may be active
> in the neighbouring directories.

## Runtime

- Python: 3.14.6 at `/usr/bin/python3`
- Display: `DISPLAY=:0.0`, `XDG_SESSION_TYPE=x11`, `XDG_CURRENT_DESKTOP=XFCE`
- Session: local seat0, user session present (loginctl)
- Screen: single monitor `eDP-1` 1366x768 (xrandr)

## Python packages present

Pillow, PyQt6, pyautogui, pynput, pydantic, fastapi, uvicorn, pytest, python-Xlib,
numpy, opencv (`cv2`), `dbus-python`, `pytesseract` + Tesseract 5.5.0, `cryptography`,
`websocket-client` (used for real Chrome DevTools Protocol control). Selenium and
Playwright are also present but are not used.

Missing: `mss` (optional fast capture; a fallback path is used instead) and
`keyring` (credential storage falls back to a `cryptography`-encrypted file).

## CLI tools present

`xdotool`, `xrandr`, `import` (ImageMagick), `git`, `node`, `npm`, `tesseract`,
`xterm`, `google-chrome`/`google-chrome-stable`/`chromium`, `xdg-open`, `gdbus`.

Missing: `wmctrl`, `scrot`, `ffmpeg`, `ydotool`, `secret-tool`, `xdg-desktop-portal`
(so the Wayland portal path cannot be exercised on this host).

Note (2026-10-01 correction): the AT-SPI accessibility bus **is reachable** on
this host via the session bus even though `at-spi-bus-launcher` is not on PATH;
`blaxcy doctor` reports `AT-SPI available windows=2`. An earlier note here claimed
otherwise and has been corrected.

## Capability implications

- X11 capture/input is available (`import`/Xlib capture; XTEST via pyautogui or
  `xdotool`). Real input remains off until explicitly enabled.
- AT-SPI accessibility metadata is available and wired (C8 VERIFIED).
- Local OCR (Tesseract) and CV (OpenCV) are available and wired (C9 VERIFIED for
  the local scope); remote vision-model understanding is not implemented.
- A local Ollama server serves `tinyllama:latest`; the router reaches it end-to-end
  (H5 local half VERIFIED). Remote providers need credentials (B-002).
- Real browser control works through Chrome/Chromium over the DevTools Protocol
  (CDP); verified with a real headless session (I3). No display or mouse/keyboard
  is involved in browser control.
- Wayland/portal (D3) is IMPLEMENTED (`blaxcy/eye/wayland.py`) but not exercisable
  here: this is an X11 session and `xdg-desktop-portal` is absent (B-003).
- Single 1366x768 monitor: multi-monitor transforms are implemented but not
  exercised on real hardware here.

## Virtual environment

The project is designed to run from a project-local virtual environment
(`.venv`) or the system interpreter. Tests run against the system interpreter
here (all deps already present).

## Service architecture (2026-10-02)

- The Eye, Memory and Brain can each run as a supervised subprocess over the
  authenticated local Unix-socket IPC (`BLAXCY_SPLIT` / `blaxcy run --split`).
  The default remains fully in-process; tools stay in-process by design (DEC-023).
- No network transport is used for IPC; the services are local to this host.
- Real measured IPC/service timings are recorded in
  `.build-state/PERFORMANCE.md` (host: this machine, Python 3.14.6).
