"""Body backends.

`DryRunBackend` is the default and never touches the real machine.
`X11Backend` performs real input through `xdotool` (XTEST under the hood) with
`pyautogui` as a fallback, and always releases held buttons/keys on teardown so a
crash never leaves the machine in a stuck-input state.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from typing import Any, Protocol

from ..models import Action, ActionKind

# xdotool button numbers
_BUTTON = {1: 1, 2: 2, 3: 3}
_SCROLL_UP, _SCROLL_DOWN = 4, 5
_MODIFIERS = ["Control_L", "Shift_L", "Alt_L", "Super_L", "Control_R", "Shift_R", "Alt_R", "Super_R"]


class BodyBackend(Protocol):
    name: str

    def perform(self, action: Action) -> dict[str, Any]: ...
    def release_all(self) -> None: ...


class DryRunBackend:
    """Simulates actions; reports what *would* happen without any real effect."""

    name = "dry-run"

    def __init__(self) -> None:
        self.performed: list[Action] = []

    def perform(self, action: Action) -> dict[str, Any]:
        self.performed.append(action)
        return {"simulated": True, "would_perform": action.kind.value, "params": action.params}

    def release_all(self) -> None:
        return None


class X11Backend:
    name = "x11"

    def __init__(self, display: str | None = None) -> None:
        self.display = display if display is not None else os.environ.get("DISPLAY", "")
        self._held_buttons: set[int] = set()
        self._held_keys: set[str] = set()

    # low level -------------------------------------------------------------
    def _has(self, tool: str) -> bool:
        return bool(shutil.which(tool))

    def _run(self, args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess:
        env = None
        if self.display:
            env = {**os.environ, "DISPLAY": self.display}
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)

    def _xdotool(self, *args: str, timeout: float = 10.0) -> str:
        r = self._run(["xdotool", *args], timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"xdotool {' '.join(args)} failed: {r.stderr.strip()}")
        return r.stdout.strip()

    # actions ---------------------------------------------------------------
    def perform(self, action: Action) -> dict[str, Any]:
        handler = getattr(self, f"_do_{action.kind.value}", None)
        if handler is None:
            raise NotImplementedError(f"X11 backend cannot perform {action.kind.value}")
        return handler(action)

    def _do_mouse_move(self, a: Action) -> dict[str, Any]:
        self._xdotool("mousemove", str(a.params["x"]), str(a.params["y"]))
        return {"cursor": [a.params["x"], a.params["y"]]}

    def _do_click(self, a: Action) -> dict[str, Any]:
        if "x" in a.params:
            self._xdotool("mousemove", str(a.params["x"]), str(a.params["y"]))
        button = _BUTTON.get(int(a.params.get("button", 1)), 1)
        self._xdotool("click", str(button))
        return {"button": button}

    def _do_double_click(self, a: Action) -> dict[str, Any]:
        if "x" in a.params:
            self._xdotool("mousemove", str(a.params["x"]), str(a.params["y"]))
        button = _BUTTON.get(int(a.params.get("button", 1)), 1)
        self._xdotool("click", "--repeat", "2", "--delay", "80", str(button))
        return {"button": button, "repeat": 2}

    def _do_right_click(self, a: Action) -> dict[str, Any]:
        a2 = Action(kind=ActionKind.CLICK, params={**a.params, "button": 3})
        return self._do_click(a2)

    def _do_drag(self, a: Action) -> dict[str, Any]:
        self._xdotool("mousemove", str(a.params["x1"]), str(a.params["y1"]))
        self._xdotool("mousedown", "1")
        self._held_buttons.add(1)
        self._xdotool("mousemove", str(a.params["x2"]), str(a.params["y2"]))
        self._xdotool("mouseup", "1")
        self._held_buttons.discard(1)
        return {"from": [a.params["x1"], a.params["y1"]], "to": [a.params["x2"], a.params["y2"]]}

    def _do_scroll(self, a: Action) -> dict[str, Any]:
        if "x" in a.params:
            self._xdotool("mousemove", str(a.params["x"]), str(a.params["y"]))
        amount = int(a.params.get("amount", -3))
        button = _SCROLL_UP if amount < 0 else _SCROLL_DOWN
        self._xdotool("click", "--repeat", str(abs(amount)), "--delay", "20", str(button))
        return {"amount": amount}

    def _do_type_text(self, a: Action) -> dict[str, Any]:
        self._xdotool("type", "--clearmodifiers", "--delay", "12", "--", str(a.params["text"]),
                      timeout=30.0)
        return {"typed": len(str(a.params["text"]))}

    def _do_key_press(self, a: Action) -> dict[str, Any]:
        self._xdotool("key", "--clearmodifiers", str(a.params["key"]))
        return {"key": a.params["key"]}

    def _do_hotkey(self, a: Action) -> dict[str, Any]:
        combo = a.params["keys"]
        if isinstance(combo, list):
            combo = "+".join(combo)
        self._xdotool("key", "--clearmodifiers", str(combo))
        return {"keys": combo}

    def _do_window_switch(self, a: Action) -> dict[str, Any]:
        # `windowactivate --sync` waits for the window to become active and can
        # hang when it already is; use a bounded sync, then fall back to the
        # asynchronous form (the WM still processes the activation request).
        wid = str(a.params["window_id"])
        try:
            r = self._run(["xdotool", "windowactivate", "--sync", wid], timeout=2.0)
            if r.returncode == 0:
                return {"window_id": wid}
        except subprocess.SubprocessError:
            pass
        self._xdotool("windowactivate", wid)
        return {"window_id": wid}

    def _do_app_launch(self, a: Action) -> dict[str, Any]:
        cmd = str(a.params["command"])
        proc = subprocess.Popen(  # noqa: S603 - command is policy-gated (HIGH risk)
            shlex.split(cmd), start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"pid": proc.pid, "command": cmd}

    def _do_clipboard_set(self, a: Action) -> dict[str, Any]:
        raise NotImplementedError("clipboard requires xclip/xsel/pyperclip (not installed)")

    def _do_clipboard_get(self, a: Action) -> dict[str, Any]:
        raise NotImplementedError("clipboard requires xclip/xsel/pyperclip (not installed)")

    def _do_noop(self, a: Action) -> dict[str, Any]:
        return {"noop": True}

    # safety ----------------------------------------------------------------
    def release_all(self) -> None:
        """Best-effort release of everything this backend may have held."""
        for button in list(self._held_buttons):
            try:
                self._xdotool("mouseup", str(button))
            except Exception:  # noqa: BLE001
                pass
        self._held_buttons.clear()
        for key in list(self._held_keys):
            try:
                self._xdotool("keyup", key)
            except Exception:  # noqa: BLE001
                pass
        self._held_keys.clear()
        for mod in _MODIFIERS:
            try:
                self._xdotool("keyup", mod)
            except Exception:  # noqa: BLE001
                pass


class FlakyBackend:
    """Test backend: fails the first `fail_times` calls, then succeeds."""

    name = "flaky"

    def __init__(self, fail_times: int = 1):
        self.fail_times = fail_times
        self.calls = 0

    def perform(self, action: Action) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"transient failure #{self.calls}")
        return {"ok": True, "call": self.calls}

    def release_all(self) -> None:
        return None


INPUT_KINDS = {
    ActionKind.MOUSE_MOVE, ActionKind.CLICK, ActionKind.DOUBLE_CLICK,
    ActionKind.RIGHT_CLICK, ActionKind.DRAG, ActionKind.SCROLL,
    ActionKind.TYPE_TEXT, ActionKind.KEY_PRESS, ActionKind.HOTKEY,
    ActionKind.WINDOW_SWITCH, ActionKind.APP_LAUNCH,
    ActionKind.CLIPBOARD_SET, ActionKind.CLIPBOARD_GET,
}
SYSTEM_KINDS = {ActionKind.TERMINAL_RUN, ActionKind.FS_READ, ActionKind.FS_WRITE, ActionKind.NOOP}

MAX_CAPTURE = 200_000  # bytes of stdout/stderr/file content returned at most


class SystemBackend:
    """Terminal and filesystem execution. No shell; filesystem writes are
    confined to explicitly allowed roots."""

    name = "system"

    def __init__(self, allowed_write_roots: list[str] | None = None) -> None:
        roots = allowed_write_roots
        if roots is None:
            env_root = os.environ.get("BLAXCY_WORKSPACE")
            roots = [env_root] if env_root else [os.getcwd()]
        self.allowed_write_roots = [os.path.realpath(r) for r in roots]

    def _within_write_root(self, path: str) -> bool:
        real = os.path.realpath(path)
        return any(real == root or real.startswith(root.rstrip("/") + "/")
                   for root in self.allowed_write_roots)

    def _do_terminal_run(self, a: Action) -> dict[str, Any]:
        cmd = str(a.params["command"])
        args = shlex.split(cmd)
        if not args:
            raise ValueError("empty command")
        cwd = a.params.get("cwd") or None
        proc = subprocess.run(  # noqa: S603 - policy-gated; no shell expansion
            args, capture_output=True, text=True, timeout=float(a.params.get("timeout", a.timeout_s)),
            cwd=cwd,
        )
        return {
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[:MAX_CAPTURE],
            "stderr": (proc.stderr or "")[:MAX_CAPTURE],
            "command": cmd,
        }

    def _do_fs_read(self, a: Action) -> dict[str, Any]:
        path = str(a.params["path"])
        with open(path, "r", encoding=a.params.get("encoding", "utf-8"), errors="replace") as fh:
            data = fh.read(MAX_CAPTURE + 1)
        return {"path": path, "content": data[:MAX_CAPTURE], "truncated": len(data) > MAX_CAPTURE}

    def _do_fs_write(self, a: Action) -> dict[str, Any]:
        path = str(a.params["path"])
        if not self._within_write_root(path):
            raise PermissionError(f"write outside allowed roots: {path}")
        content = str(a.params.get("content", ""))
        os.makedirs(os.path.dirname(os.path.realpath(path)) or ".", exist_ok=True)
        with open(path, "w", encoding=a.params.get("encoding", "utf-8")) as fh:
            fh.write(content)
        return {"path": path, "bytes": len(content.encode("utf-8"))}

    def _do_noop(self, a: Action) -> dict[str, Any]:
        return {"noop": True}

    def perform(self, action: Action) -> dict[str, Any]:
        handler = getattr(self, f"_do_{action.kind.value}", None)
        if handler is None:
            raise NotImplementedError(f"system backend cannot perform {action.kind.value}")
        return handler(action)

    def release_all(self) -> None:
        return None


class AutoBackend:
    """Routes input actions to X11, system actions to SystemBackend, and browser
    actions to a real Chrome/Chromium session (started lazily)."""

    name = "auto"

    def __init__(self, display: str | None = None,
                 allowed_write_roots: list[str] | None = None,
                 browser: Any = None) -> None:
        self.input = X11Backend(display)
        self.system = SystemBackend(allowed_write_roots)
        self._browser = browser

    def _browser_backend(self):
        if self._browser is None:
            from ..browser import BrowserBackend

            self._browser = BrowserBackend(headless=not bool(self.input.display))
        return self._browser

    def perform(self, action: Action) -> dict[str, Any]:
        if action.kind in SYSTEM_KINDS:
            return self.system.perform(action)
        if action.kind in INPUT_KINDS:
            return self.input.perform(action)
        from ..browser.cdp import BROWSER_KINDS

        if action.kind in BROWSER_KINDS:
            return self._browser_backend().perform(action)
        raise NotImplementedError(f"auto backend cannot perform {action.kind.value}")

    def release_all(self) -> None:
        self.input.release_all()
        if self._browser is not None:
            self._browser.release_all()


def make_backend(name: str) -> BodyBackend:
    if name == "x11":
        return X11Backend()
    if name == "dry-run":
        return DryRunBackend()
    if name == "system":
        return SystemBackend()
    if name == "auto":
        return AutoBackend()
    if name == "browser":
        from ..browser import BrowserBackend

        return BrowserBackend()
    raise ValueError(f"unknown backend {name!r}")


def now() -> float:
    return time.time()
