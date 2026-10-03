"""X11 desktop perception.

Real, not simulated: frames are captured from the live X server via ImageMagick
`import` (or Pillow as a fallback), window/cursor metadata comes from `xdotool`,
and monitor geometry comes from `xrandr`. Change detection compares successive
frames. A background sampler maintains the freshest `ScreenState`.

Locked/blanked/suspended sessions are detected and reported; BLAXCY never tries
to bypass a lock screen.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import statistics
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import MonitorInfo, ScreenState, WindowInfo

# Fraction of downscaled pixels that must differ before a frame is "changed".
CHANGE_THRESHOLD = 0.02


# --------------------------------------------------------------------------- #
# Session detection
# --------------------------------------------------------------------------- #
def detect_session(display: str | None = None) -> dict[str, object]:
    disp = display if display is not None else os.environ.get("DISPLAY", "")
    return {
        "display": disp,
        "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
        "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
        "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
        "has_display": bool(disp or os.environ.get("WAYLAND_DISPLAY")),
        "tools": {t: bool(shutil.which(t)) for t in ("xdotool", "xrandr", "import", "scrot")},
        "capture_backend": _pick_capture_backend(),
    }


def _pick_capture_backend() -> str:
    if shutil.which("import") and os.environ.get("DISPLAY"):
        return "import"
    try:
        import PIL  # noqa: F401
        import pyautogui  # noqa: F401

        return "pyautogui"
    except Exception:  # noqa: BLE001
        return "none"


def session_is_usable(display: str | None = None) -> tuple[bool, str]:
    disp = display if display is not None else os.environ.get("DISPLAY", "")
    if not disp:
        return False, "no DISPLAY (session may be locked, blanked, or headless)"
    if not shutil.which("xdotool"):
        return False, "xdotool not available"
    try:
        r = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, timeout=3)
        if r.returncode != 0:
            return False, "X server not reachable (locked or suspended?)"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"X server probe failed: {exc}"
    return True, "ok"


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #
def _capture_import() -> bytes | None:
    try:
        r = subprocess.run(["import", "-window", "root", "-silent", "png:-"],
                           capture_output=True, timeout=10)
        return r.stdout if r.returncode == 0 and r.stdout else None
    except (OSError, subprocess.SubprocessError):
        return None


def _capture_pyautogui() -> bytes | None:
    try:
        import io as _io

        import pyautogui

        img = pyautogui.screenshot()
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


def capture_root(backend: str = "") -> tuple[bytes | None, str]:
    backend = backend or _pick_capture_backend()
    if backend == "import":
        data = _capture_import()
        if data:
            return data, "import"
        data = _capture_pyautogui()
        return (data, "pyautogui") if data else (None, "none")
    if backend == "pyautogui":
        data = _capture_pyautogui()
        return (data, "pyautogui") if data else (None, "none")
    return None, "none"


# --------------------------------------------------------------------------- #
# Change detection
# --------------------------------------------------------------------------- #
def _thumb(data: bytes, size: tuple[int, int] = (64, 36)):
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("L").resize(size)


def detect_change(prev: bytes | None, cur: bytes, *, threshold: int = 16,
                  size: tuple[int, int] = (64, 36)) -> tuple[bool, float]:
    """Return (changed, ratio) by comparing downscaled grayscale frames."""
    if prev is None:
        return True, 1.0
    try:
        from PIL import ImageChops

        a = _thumb(prev, size)
        b = _thumb(cur, size)
        diff = ImageChops.difference(a, b)
        total = size[0] * size[1]
        changed = sum(diff.histogram()[threshold:])
        ratio = changed / total
        return ratio >= CHANGE_THRESHOLD, ratio
    except Exception:  # noqa: BLE001
        return True, 1.0


@dataclass
class LatencyStats:
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=120))

    def add(self, seconds: float) -> None:
        self.samples.append(seconds)

    def percentile(self, p: float) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        idx = min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1))))
        return ordered[idx]

    def summary(self) -> dict[str, float]:
        if not self.samples:
            return {"p50": 0.0, "p95": 0.0, "n": 0.0, "mean": 0.0}
        return {
            "p50": self.percentile(50),
            "p95": self.percentile(95),
            "mean": statistics.fmean(self.samples),
            "n": float(len(self.samples)),
        }


class EyeBackend(Protocol):
    name: str

    def snapshot(self, sequence: int) -> ScreenState: ...


# --------------------------------------------------------------------------- #
# Fake backend (tests / no display)
# --------------------------------------------------------------------------- #
class FakeEyeBackend:
    """Deterministic backend for tests. Never touches a real display."""

    name = "fake"

    def __init__(self, states: list[ScreenState] | None = None,
                 factory: Callable[[int], ScreenState] | None = None):
        self._states = states or []
        self._factory = factory
        self._i = 0

    def snapshot(self, sequence: int) -> ScreenState:
        if self._factory is not None:
            state = self._factory(sequence)
        elif self._states:
            state = self._states[min(self._i, len(self._states) - 1)]
            self._i += 1
        else:
            state = ScreenState(timestamp=time.time(), width=100, height=100, source="fake")
        state.sequence = sequence
        state.source = state.source or "fake"
        return state


# --------------------------------------------------------------------------- #
# Real X11 backend
# --------------------------------------------------------------------------- #
class X11EyeBackend:
    name = "x11"

    def __init__(self, display: str | None = None, detect_damage: bool = True,
                 atspi: Any = None, atspi_every: int = 5):
        self.display = display if display is not None else os.environ.get("DISPLAY", "")
        self.detect_damage = detect_damage
        self._prev_frame: bytes | None = None
        self._capture_backend = _pick_capture_backend()
        self.atspi = atspi
        self.atspi_every = max(1, atspi_every)
        self._atspi_summary: dict[str, Any] = {}
        # In-process X connection for cheap metadata queries; monitor geometry
        # changes rarely and is cached briefly (querying xrandr every frame adds
        # ~0.3s per sample for no benefit).
        self._xlib_disp: Any = None
        self._xlib_failed = False
        self._monitor_cache: list[MonitorInfo] = []
        self._monitor_cache_at = 0.0
        self._monitor_ttl = 5.0

    def _refresh_accessibility(self) -> dict[str, Any]:
        if self.atspi is None:
            return {}
        try:
            if self.atspi.is_available():
                return self.atspi.summary()
        except Exception:  # noqa: BLE001
            pass
        return {}

    @staticmethod
    def _annotate_with_accessibility(windows: list[WindowInfo],
                                     summary: dict[str, Any]) -> None:
        """Fill WindowInfo.app by matching AT-SPI window titles to X11 windows."""
        atspi_windows = summary.get("windows") or []
        if not atspi_windows:
            return
        for win in windows:
            title = (win.title or "").lower()
            if not title:
                continue
            for aw in atspi_windows:
                aname = (aw.get("name") or "").lower()
                if aname and (aname in title or title in aname):
                    win.app = aw.get("app", "") or win.app
                    break

    # fast window enumeration (in-process) ---------------------------------
    def _xlib(self) -> Any:
        if self._xlib_failed:
            return None
        if self._xlib_disp is None:
            try:
                from Xlib import display as _display

                self._xlib_disp = (_display.Display(self.display) if self.display
                                   else _display.Display())
            except Exception:  # noqa: BLE001 - fall back to xdotool
                self._xlib_failed = True
                return None
        return self._xlib_disp

    def _xlib_windows(self, active_id: str | None) -> list[WindowInfo] | None:
        """Enumerate managed client windows in-process.

        The xdotool path spawns three subprocesses per window (up to ~180 per
        frame), which can take seconds and starve the X server under load;
        querying the X server directly through python-Xlib keeps a frame cheap.
        Returns None when Xlib is unavailable so the caller can fall back.
        """
        try:
            from Xlib import X
        except Exception:  # noqa: BLE001
            return None
        disp = self._xlib()
        if disp is None:
            return None
        try:
            root = disp.screen().root
            prop = root.get_full_property(disp.intern_atom("_NET_CLIENT_LIST"),
                                          X.AnyPropertyType)
            if prop is None:
                return None
            ids = list(prop.value)
        except Exception:  # noqa: BLE001
            return None
        pid_atom = disp.intern_atom("_NET_WM_PID")
        windows: list[WindowInfo] = []
        for wid in ids[:120]:
            try:
                w = disp.create_resource_object("window", wid)
                title = w.get_wm_name()
                if isinstance(title, bytes):
                    title = title.decode("utf-8", "replace")
                geom = w.get_geometry()
                coords = w.translate_coords(root, 0, 0)
                pid = 0
                p = w.get_full_property(pid_atom, X.AnyPropertyType)
                if p is not None and p.value:
                    pid = int(p.value[0])
                windows.append(WindowInfo(
                    window_id=str(int(wid)), title=title or "", app="",
                    x=int(coords.x), y=int(coords.y),
                    width=int(geom.width), height=int(geom.height),
                    pid=pid, focused=(str(int(wid)) == str(active_id)),
                ))
            except Exception:  # noqa: BLE001 - skip windows that vanish mid-query
                continue
        return windows

    # metadata helpers ------------------------------------------------------
    def monitors(self) -> list[MonitorInfo]:
        now = time.time()
        if self._monitor_cache and (now - self._monitor_cache_at) < self._monitor_ttl:
            return self._monitor_cache
        result = self._query_monitors()
        self._monitor_cache = result
        self._monitor_cache_at = now
        return result

    def _query_monitors(self) -> list[MonitorInfo]:
        if not shutil.which("xrandr"):
            return []
        try:
            r = subprocess.run(["xrandr", "--query"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return []
        monitors: list[MonitorInfo] = []
        for line in r.stdout.splitlines():
            if " connected" not in line:
                continue
            parts = line.split()
            name = parts[0]
            geom = next((p for p in parts if "x" in p and "+" in p and p[0].isdigit()), None)
            if not geom:
                continue
            try:
                size, xoff, yoff = geom.split("+")
                w, h = size.split("x")
                monitors.append(MonitorInfo(name=name, x=int(xoff), y=int(yoff),
                                            width=int(w), height=int(h)))
            except (ValueError, IndexError):
                continue
        return monitors

    def _run(self, args: list[str]) -> str:
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    def active_window_id(self) -> str | None:
        out = self._run(["xdotool", "getactivewindow"])
        return out or None

    def windows(self, active_id: str | None = None) -> list[WindowInfo]:
        active_id = active_id or self.active_window_id()
        fast = self._xlib_windows(active_id)
        if fast is not None:
            return fast
        found = self._run(["xdotool", "search", "--onlyvisible", "--name", ""]).splitlines()
        # Always enumerate the focused window first. A busy desktop can expose far
        # more visible windows than the cap below, and the active window's id is
        # not necessarily near the start of xdotool's output -- without this the
        # cap could drop it and `ScreenState.active_window()` would spuriously
        # return None (which silently broke live focus verification).
        if active_id:
            ids = [active_id, *(wid for wid in found if wid != active_id)]
        else:
            ids = found
        windows: list[WindowInfo] = []
        for wid in ids[:60]:
            title = self._run(["xdotool", "getwindowname", wid])
            geom = self._run(["xdotool", "getwindowgeometry", "--shell", wid])
            pid_s = self._run(["xdotool", "getwindowpid", wid])
            info = {"X": 0, "Y": 0, "WIDTH": 0, "HEIGHT": 0}
            for line in geom.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    if k in info:
                        try:
                            info[k] = int(v)
                        except ValueError:
                            pass
            windows.append(WindowInfo(
                window_id=wid, title=title, app="",
                x=info["X"], y=info["Y"], width=info["WIDTH"], height=info["HEIGHT"],
                pid=int(pid_s) if pid_s.isdigit() else 0,
                focused=(wid == active_id),
            ))
        return windows

    def cursor(self) -> tuple[int, int] | None:
        out = self._run(["xdotool", "getmouselocation", "--shell"])
        if not out:
            return None
        x = y = None
        for line in out.splitlines():
            if line.startswith("X="):
                x = int(line[2:]) if line[2:].isdigit() else None
            elif line.startswith("Y="):
                y = int(line[2:]) if line[2:].isdigit() else None
        return (x, y) if x is not None and y is not None else None

    def snapshot(self, sequence: int) -> ScreenState:
        usable, reason = session_is_usable(self.display)
        if not usable:
            return ScreenState(
                timestamp=time.time(), width=0, height=0, sequence=sequence,
                source="x11-unavailable", confidence=0.0,
                changed=True, changed_ratio=0.0,
            )
        data, backend = capture_root(self._capture_backend)
        changed, ratio = (True, 1.0)
        fhash = ""
        width = height = 0
        if data:
            fhash = hashlib.sha256(data).hexdigest()[:16]
            if self.detect_damage:
                changed, ratio = detect_change(self._prev_frame, data)
            self._prev_frame = data
            try:
                from PIL import Image

                with Image.open(io.BytesIO(data)) as im:
                    width, height = im.size
            except Exception:  # noqa: BLE001
                pass
        monitors = self.monitors()
        if not width and monitors:
            width = max((m.x + m.width) for m in monitors)
            height = max((m.y + m.height) for m in monitors)
        active = self.active_window_id()
        windows = self.windows(active)
        if self.atspi is not None and (sequence % self.atspi_every == 0 or not self._atspi_summary):
            self._atspi_summary = self._refresh_accessibility()
        if self._atspi_summary:
            self._annotate_with_accessibility(windows, self._atspi_summary)
        return ScreenState(
            timestamp=time.time(), width=width, height=height, sequence=sequence,
            monitors=monitors, windows=windows, active_window_id=active,
            cursor=self.cursor(), frame_hash=fhash, changed=changed, changed_ratio=ratio,
            source=f"x11:{backend}", confidence=1.0 if data else 0.3,
            accessibility=self._atspi_summary,
            frame_bytes=data,
        )


# --------------------------------------------------------------------------- #
# The Eye
# --------------------------------------------------------------------------- #
class Eye:
    """Near-continuous perception with condition-based waiting."""

    def __init__(self, backend: EyeBackend, *, interval_s: float = 0.4,
                 persist_frames: bool = False, vision: Any = None):
        self.backend = backend
        self.interval_s = interval_s
        self.persist_frames = persist_frames  # disk persistence is opt-in
        self.vision = vision  # optional VisionBackend for on-demand OCR/CV
        self._state: ScreenState | None = None
        self._last_frame: bytes | None = None
        self._sequence = 0
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._running = False
        self._subscribers: list[Callable[[ScreenState], None]] = []
        self._latency = LatencyStats()
        self._errors = 0

    # lifecycle -------------------------------------------------------------
    def start(self) -> None:
        with self._cond:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(target=self._loop, name="blaxcy-eye", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while True:
            with self._cond:
                if not self._running:
                    return
            started = time.monotonic()
            try:
                state = self.backend.snapshot(self._sequence)
            except Exception:  # noqa: BLE001 - a bad frame must not kill perception
                with self._cond:
                    self._errors += 1
                    self._sequence += 1
                time.sleep(self.interval_s)
                continue
            self._latency.add(time.monotonic() - started)
            # Keep the latest frame in memory for on-demand OCR/CV; never on disk
            # unless persist_frames is explicitly enabled.
            self._last_frame = state.frame_bytes
            if not self.persist_frames:
                state.frame_bytes = None
            with self._cond:
                self._sequence += 1
                self._state = state
                self._cond.notify_all()
            for sub in list(self._subscribers):
                try:
                    sub(state)
                except Exception:  # noqa: BLE001
                    self._errors += 1
            time.sleep(self.interval_s)

    # access ----------------------------------------------------------------
    def current(self) -> ScreenState | None:
        with self._cond:
            return self._state

    def snapshot(self, *, wait: bool = True, timeout: float = 2.0) -> ScreenState | None:
        with self._cond:
            if self._state is None and wait:
                self._cond.wait_for(lambda: self._state is not None or not self._running, timeout)
            return self._state

    def wait_for(self, predicate: Callable[[ScreenState | None], bool], *,
                 timeout: float = 10.0) -> ScreenState | None:
        """Block until `predicate(state)` is true. No arbitrary sleeps."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while True:
                if predicate(self._state):
                    return self._state
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._running:
                    return None
                self._cond.wait(timeout=min(remaining, 0.25))

    def subscribe(self, callback: Callable[[ScreenState], None]) -> None:
        with self._cond:
            self._subscribers.append(callback)

    def latency(self) -> dict[str, float]:
        return self._latency.summary()

    # on-demand vision (targeted, not per-frame) ----------------------------
    def current_frame(self) -> bytes | None:
        with self._cond:
            return self._last_frame

    def vision_capabilities(self) -> dict[str, Any]:
        if self.vision is None:
            return {"ocr": False, "cv": False, "available": False}
        caps = self.vision.capabilities()
        caps["available"] = self.vision.is_available()
        return caps

    def ocr(self, region: tuple[int, int, int, int] | None = None) -> str:
        frame = self.current_frame()
        if frame is None or self.vision is None:
            return ""
        return self.vision.ocr(frame, region)

    def find_text(self, needle: str, region: tuple[int, int, int, int] | None = None,
                  min_conf: float = 40.0) -> list:
        frame = self.current_frame()
        if frame is None or self.vision is None:
            return []
        return self.vision.find_text(frame, needle, region=region, min_conf=min_conf)

    def contains_text(self, needle: str, region: tuple[int, int, int, int] | None = None) -> bool:
        return bool(self.find_text(needle, region))

    def ui_regions(self, region: tuple[int, int, int, int] | None = None) -> list:
        frame = self.current_frame()
        if frame is None or self.vision is None:
            return []
        return self.vision.detect_ui_regions(frame, region)

    def accessibility(self) -> dict[str, Any]:
        state = self.current()
        return state.accessibility if state else {}

    def health(self) -> dict[str, object]:
        with self._cond:
            state = self._state
        return {
            "running": self._running,
            "sequence": self._sequence,
            "errors": self._errors,
            "has_state": state is not None,
            "state_age_s": round(state.age(), 3) if state else None,
            "latency": self.latency(),
        }
