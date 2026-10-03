"""Wayland / XDG-Desktop-Portal perception.

Wayland compositors do not expose a global screen or a global input device to
clients. The supported route is the XDG Desktop Portal:

* **capture** → `org.freedesktop.portal.Screenshot` (returns a PNG via a Request
  handle; the portal may itself be backed by PipeWire / a screencast session);
* **input** → `org.freedesktop.portal.RemoteDesktop` (a compositor-mediated,
  user-consented input session).

This module implements that path honestly. Capability is *detected*; when the
session is not Wayland, or no portal is present, the backend reports itself
unavailable and degrades to an explicit `wayland-unavailable` ScreenState rather
than pretending to see the screen.

Limitations on a Wayland host: window list / active window / cursor position are
not generally available (that needs compositor-specific protocols), so those
fields stay empty with a reduced confidence. That is reported, not hidden.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import time
import urllib.parse
from typing import Any

from ..models import ScreenState
from .x11 import detect_change


def detect_wayland(display: str | None = None) -> dict[str, Any]:
    """Detect the graphical session and portal capabilities without side effects.

    The DBus probe only runs when the session is actually Wayland, so X11 hosts
    pay no cost.
    """
    disp = display if display is not None else os.environ.get("DISPLAY", "")
    session = os.environ.get("XDG_SESSION_TYPE", "")
    wl = os.environ.get("WAYLAND_DISPLAY", "")
    is_wayland = session == "wayland" or bool(wl)

    info: dict[str, Any] = {
        "session_type": session,
        "display": disp,
        "wayland_display": wl,
        "is_wayland": is_wayland,
        "portal": False,
        "remote_desktop": False,
        "pipewire": bool(shutil.which("pipewire")),
        "error": None,
    }
    if not is_wayland:
        return info

    try:
        import dbus

        bus = dbus.SessionBus()
        names = {str(n) for n in bus.list_names()}
        info["portal"] = "org.freedesktop.portal.Desktop" in names
        if info["portal"]:
            obj = bus.get_object("org.freedesktop.portal.Desktop",
                                 "/org/freedesktop/portal/desktop")
            try:
                dbus.Interface(obj, "org.freedesktop.portal.RemoteDesktop")
                info["remote_desktop"] = True
            except Exception:  # noqa: BLE001
                info["remote_desktop"] = False
    except Exception as exc:  # noqa: BLE001 - detection must never raise
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _read_uri(uri: str) -> bytes | None:
    try:
        path = urllib.parse.urlparse(uri).path or uri
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


class DbusPortalScreenshot:
    """Real XDG portal screenshot client (synchronous, best-effort).

    The portal replies asynchronously via the `org.freedesktop.portal.Request`
    `Response` signal, so this subscribes to it and pumps the connection until the
    response arrives or the timeout expires. All failure modes return `None` and
    record `last_error()`; they never fabricate an image.
    """

    PORTAL = "org.freedesktop.portal.Desktop"
    PATH = "/org/freedesktop/portal/desktop"
    SCREENSHOT = "org.freedesktop.portal.Screenshot"
    REQUEST = "org.freedesktop.portal.Request"

    def __init__(self, bus: Any = None, dbus_module: Any = None, timeout: float = 10.0,
                 uri_reader: Any = None) -> None:
        self._bus = bus
        self._dbus_mod = dbus_module
        self.timeout = timeout
        self._uri_reader = uri_reader or _read_uri
        self._error: str | None = None

    def last_error(self) -> str | None:
        return self._error

    def _connect(self) -> Any:
        if self._bus is not None:
            return self._bus
        try:
            import dbus

            self._bus = dbus.SessionBus()
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            self._bus = None
        return self._bus

    @property
    def _dbus_module(self) -> Any:
        if self._dbus_mod is None:
            try:
                import dbus

                self._dbus_mod = dbus
            except Exception as exc:  # noqa: BLE001
                self._error = f"{type(exc).__name__}: {exc}"
                self._dbus_mod = None
        return self._dbus_mod

    def available(self) -> bool:
        bus = self._connect()
        dbus = self._dbus_module
        if bus is None or dbus is None:
            return False
        try:
            obj = bus.get_object(self.PORTAL, self.PATH)
            dbus.Interface(obj, self.SCREENSHOT)
            return True
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            return False

    def grab_png(self, timeout: float | None = None) -> bytes | None:
        bus = self._connect()
        dbus = self._dbus_module
        if bus is None or dbus is None:
            return None
        collected: dict[str, Any] = {}

        def on_response(response: int, results: Any, **_kw: Any) -> None:
            collected["response"] = int(response)
            collected["results"] = results

        match = None
        try:
            match = bus.add_signal_receiver(
                on_response, signal_name="Response", dbus_interface=self.REQUEST)
            obj = bus.get_object(self.PORTAL, self.PATH)
            iface = dbus.Interface(obj, self.SCREENSHOT)
            iface.Screenshot(dbus.Dictionary({"interactive": False}, signature="sv"))
            deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
            while time.monotonic() < deadline and "results" not in collected:
                bus.read_write_dispatch(0.1)
            if collected.get("response") not in (None, 0):
                self._error = f"portal refused the screenshot (response={collected.get('response')})"
                return None
            uri = (collected.get("results") or {}).get("uri")
            if not uri:
                self._error = "portal returned no screenshot uri"
                return None
            return self._uri_reader(str(uri))
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            return None
        finally:
            if match is not None:
                try:
                    bus.remove_signal_receiver(match)
                except Exception:  # noqa: BLE001
                    pass


def _unavailable_state(sequence: int, reason: str | None = None) -> ScreenState:
    return ScreenState(
        timestamp=time.time(), width=0, height=0, sequence=sequence,
        source="wayland-unavailable", confidence=0.0, changed=False,
        changed_ratio=0.0, accessibility={},
    )


class WaylandPortalBackend:
    """Eye backend that captures the desktop through the Wayland portal."""

    name = "wayland-portal"

    def __init__(self, client: Any = None) -> None:
        self.client = client if client is not None else DbusPortalScreenshot()
        self._prev_frame: bytes | None = None
        self._last_error: str | None = None

    def is_available(self) -> bool:
        try:
            return bool(self.client.available())
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            return False

    def last_error(self) -> str | None:
        if self._last_error:
            return self._last_error
        getter = getattr(self.client, "last_error", None)
        return getter() if callable(getter) else None

    def snapshot(self, sequence: int) -> ScreenState:
        if not self.is_available():
            return _unavailable_state(sequence)
        try:
            png = self.client.grab_png()
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            png = None
        if not png:
            return _unavailable_state(sequence)

        width, height = 0, 0
        try:
            from PIL import Image

            width, height = Image.open(io.BytesIO(png)).size
        except Exception:  # noqa: BLE001 - keep going with unknown size
            pass

        changed, ratio = detect_change(self._prev_frame, png)
        self._prev_frame = png
        return ScreenState(
            timestamp=time.time(), width=width, height=height, sequence=sequence,
            frame_hash=hashlib.sha256(png).hexdigest()[:16],
            changed=changed, changed_ratio=ratio,
            source="wayland-portal", confidence=0.6,
            cursor=None, windows=[], active_window_id=None,
            accessibility={}, frame_bytes=png,
        )


def select_eye_backend(settings: Any, *, atspi: Any = None, client: Any = None) -> Any:
    """Pick the best perception backend for the current session.

    Wayland + a working portal wins; otherwise X11 when a display exists; else the
    fake backend. This is the single place that assumes anything about the session.
    """
    from .x11 import FakeEyeBackend, X11EyeBackend

    info = detect_wayland(getattr(settings, "display", ""))
    if info["is_wayland"]:
        backend = WaylandPortalBackend(client=client)
        if backend.is_available():
            return backend
    if getattr(settings, "display", ""):
        return X11EyeBackend(settings.display, atspi=atspi)
    return FakeEyeBackend()
