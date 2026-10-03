"""Supervised, reversible live-desktop acceptance test (requirement B7).

This is the one place BLAXCY deliberately touches the *real* mouse and keyboard.
It is built to be safe and reversible:

* it refuses to run unless real input has been explicitly authorized
  (`BLAXCY_ENABLE_REAL_INPUT=1`, surfaced as `Policy.real_input_enabled`);
* it only acts on a throwaway `xterm` that the *harness itself* creates, whose
  input is redirected to a temp file — so typing has a real, checkable effect
  with no risk to the user's windows;
* it records the cursor position first and restores it afterwards;
* it closes the window and deletes the temp file, whatever happens.

Verification is real: BLAXCY moves the real pointer, clicks, types a unique token
through the Body, and the token is then read back out of the file the terminal
wrote — plus the Eye must independently observe the cursor move and the focused
window. The result is written to `.build-state/B7_EVIDENCE.md`.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Action, ActionKind

DEFAULT_EVIDENCE = ".build-state/B7_EVIDENCE.md"


# --------------------------------------------------------------------------- #
# reversible target
# --------------------------------------------------------------------------- #
class XtermTarget:
    """A throwaway xterm whose stdin is redirected to a temp file.

    `cat > FILE` means everything BLAXCY types lands in FILE, where it can be
    verified and then deleted. The harness owns this window, not the user.
    """

    def __init__(self, title: str = "BLAXCY_ACCEPT") -> None:
        self.title = title
        self._file: str | None = None
        self._proc: subprocess.Popen | None = None
        self._window_id: str | None = None

    def open(self) -> dict[str, Any]:
        fd, path = tempfile.mkstemp(prefix="blaxcy-accept-", suffix=".txt")
        os.close(fd)
        self._file = path
        cmd = ["xterm", "-T", self.title, "-geometry", "64x12",
               "-e", "sh", "-c", f"cat > {path}"]
        self._proc = subprocess.Popen(cmd, start_new_session=True,  # noqa: S603
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"file": path, "pid": self._proc.pid}

    def wait_window(self, timeout: float = 8.0) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = subprocess.run(["xdotool", "search", "--name", self.title],  # noqa: S603
                                    capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                self._window_id = result.stdout.strip().splitlines()[-1]
                return self._window_id
            time.sleep(0.15)
        return None

    def geometry(self) -> tuple[int, int, int, int] | None:
        if not self._window_id:
            return None
        result = subprocess.run(  # noqa: S603
            ["xdotool", "getwindowgeometry", "--shell", self._window_id],
            capture_output=True, text=True)
        if result.returncode != 0:
            return None
        data = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        try:
            return (int(data["X"]), int(data["Y"]), int(data["WIDTH"]), int(data["HEIGHT"]))
        except (KeyError, ValueError):
            return None

    def read(self) -> str:
        if not self._file:
            return ""
        try:
            return Path(self._file).read_text(errors="replace")
        except OSError:
            return ""

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None
        if self._file:
            try:
                os.unlink(self._file)
            except OSError:
                pass
            self._file = None


# --------------------------------------------------------------------------- #
# cursor helpers
# --------------------------------------------------------------------------- #
def xdotool_cursor_get() -> tuple[int, int] | None:
    result = subprocess.run(["xdotool", "getmouselocation", "--shell"],  # noqa: S603
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    data = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    try:
        return (int(data["X"]), int(data["Y"]))
    except (KeyError, ValueError):
        return None


def xdotool_cursor_set(x: int, y: int) -> bool:
    return subprocess.run(  # noqa: S603
        ["xdotool", "mousemove", str(x), str(y)],
        capture_output=True).returncode == 0


# --------------------------------------------------------------------------- #
# result
# --------------------------------------------------------------------------- #
@dataclass
class LiveAcceptanceResult:
    ok: bool
    verified: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    token: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "verified": self.verified, "token": self.token,
                "steps": self.steps, "evidence": self.evidence}


def _write_evidence(path: str | Path, result: LiveAcceptanceResult) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# BLAXCY — B7 Live Acceptance Evidence",
        "",
        f"- timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        f"- token: `{result.token or '-'}`",
        f"- real input authorized: yes",
        f"- display: `{os.environ.get('DISPLAY', '')}` "
        f"session=`{os.environ.get('XDG_SESSION_TYPE', '')}`",
        f"- **verified: {result.verified}**",
        f"- ok: {result.ok}",
        "",
        "| step | ok | detail |",
        "|------|----|--------|",
    ]
    for step in result.steps:
        lines.append(f"| {step['step']} | {'yes' if step['ok'] else 'NO'} | {step['detail']} |")
    lines += ["", "```json", json.dumps(result.evidence, indent=2, default=str), "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# the acceptance run
# --------------------------------------------------------------------------- #
def run_live_acceptance(*, policy: Any, body: Any, eye: Any, target: Any,
                        token: str | None = None,
                        evidence_path: str | Path | None = None,
                        get_cursor: Any = None, set_cursor: Any = None
                        ) -> LiveAcceptanceResult:
    """Run the reversible live test. Returns a result; never touches user windows."""
    get_cursor = get_cursor or xdotool_cursor_get
    set_cursor = set_cursor or xdotool_cursor_set
    token = token or f"blaxcy-{uuid.uuid4().hex[:8]}"
    steps: list[dict[str, Any]] = []

    def step(name: str, ok: bool, detail: str = "") -> bool:
        steps.append({"step": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    # 1. authorization gate -------------------------------------------------
    if not getattr(policy, "real_input_enabled", False):
        result = LiveAcceptanceResult(
            ok=False, verified=False, steps=steps, token=token,
            evidence={"refused": True,
                      "reason": "real input not authorized; set BLAXCY_ENABLE_REAL_INPUT=1"})
        if evidence_path:
            _write_evidence(evidence_path, result)
        return result

    original_cursor = None
    try:
        original_cursor = get_cursor()
        step("save cursor", original_cursor is not None, str(original_cursor))

        opened = target.open()
        step("open target", bool(opened), str(opened.get("file") if opened else ""))

        window_id = target.wait_window()
        step("target window appears", bool(window_id), str(window_id))
        if not window_id:
            raise RuntimeError("target window did not appear")

        focus = body.execute(Action(kind=ActionKind.WINDOW_SWITCH,
                                    params={"window_id": window_id}, target=target.title))
        step("focus target", focus.ok, focus.detail or str(focus.error))

        geometry = target.geometry()
        step("read geometry", geometry is not None, str(geometry))
        if not geometry:
            raise RuntimeError("could not read target geometry")
        gx, gy, gw, gh = geometry
        cx, cy = gx + gw // 2, gy + gh // 2

        move = body.execute(Action(kind=ActionKind.MOUSE_MOVE, params={"x": cx, "y": cy}))
        step("move real mouse", move.ok, f"to ({cx},{cy})")

        click = body.execute(Action(kind=ActionKind.CLICK, params={"x": cx, "y": cy}))
        step("real click", click.ok, click.detail or str(click.error))

        typed = body.execute(Action(kind=ActionKind.TYPE_TEXT, params={"text": token}))
        step("real typing", typed.ok, typed.detail or str(typed.error))

        enter = body.execute(Action(kind=ActionKind.KEY_PRESS, params={"key": "Return"}))
        step("real key press", enter.ok, enter.detail or str(enter.error))

        # 2. verify via the real effect ------------------------------------
        deadline = time.monotonic() + 5.0
        content = ""
        while time.monotonic() < deadline:
            content = target.read()
            if token in content:
                break
            time.sleep(0.2)
        step("typed text reached the terminal", token in content, repr(content[:80]))

        # 3. verify via independent perception -- BEFORE closing the window -
        # The throwaway terminal must still exist for the Eye to see it focused,
        # so EOF (which makes `cat` exit and closes xterm) is sent last. Wait on
        # the Eye's condition variable rather than reading a possibly-stale frame.
        def _await(predicate: Any) -> Any:
            waiter = getattr(eye, "wait_for", None)
            if callable(waiter):
                return waiter(predicate, timeout=3.0)
            current = getattr(eye, "current", None)
            return current() if callable(current) else None

        def _cursor_at_target(st: Any) -> bool:
            return bool(st and st.cursor and
                        abs(st.cursor[0] - cx) <= 3 and abs(st.cursor[1] - cy) <= 3)

        s1 = _await(_cursor_at_target)
        cursor_ok = bool(s1 and s1.cursor and
                         abs(s1.cursor[0] - cx) <= 3 and abs(s1.cursor[1] - cy) <= 3)
        step("Eye observed the cursor move", cursor_ok,
             f"eye_cursor={s1.cursor if s1 else None} expected=({cx},{cy})")

        def _target_focused(st: Any) -> bool:
            if not st:
                return False
            win = st.active_window()
            return bool(win and target.title.lower() in (win.title or "").lower())

        s2 = _await(_target_focused)
        active_title = ""
        if s2:
            win = s2.active_window()
            active_title = win.title if win else ""
        step("Eye sees target focused", target.title.lower() in active_title.lower(),
             f"active_window={active_title!r}")

        # 4. send EOF last -- this closes the throwaway terminal -------------
        eof = body.execute(Action(kind=ActionKind.HOTKEY, params={"keys": ["ctrl", "d"]}))
        step("send EOF", eof.ok, eof.detail or str(eof.error))

        verified = all(s["ok"] for s in steps)
        result = LiveAcceptanceResult(
            ok=True, verified=verified, steps=steps, token=token,
            evidence={"cursor": [cx, cy], "geometry": [gx, gy, gw, gh],
                      "terminal_output": content[:200],
                      "eye_cursor": list(s1.cursor) if s1 and s1.cursor else None,
                      "active_window": active_title})
        return result

    except Exception as exc:  # noqa: BLE001 - always record, never crash the caller
        result = LiveAcceptanceResult(ok=False, verified=False, steps=steps, token=token,
                                      evidence={"error": f"{type(exc).__name__}: {exc}"})
        return result
    finally:
        try:
            target.close()
        except Exception:  # noqa: BLE001
            pass
        if original_cursor is not None:
            try:
                set_cursor(*original_cursor)
            except Exception:  # noqa: BLE001
                pass
        if evidence_path:
            _write_evidence(evidence_path, result)
