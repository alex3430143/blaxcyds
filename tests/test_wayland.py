"""Tests for Wayland/portal perception (requirement D3).

This host is X11, so the real portal cannot be exercised end-to-end. Instead the
portal protocol logic and the backend contract are tested with injected fakes,
and the X11-host degradation path is tested for real.
"""

from __future__ import annotations

import io

from PIL import Image

from blaxcy.eye.wayland import (
    DbusPortalScreenshot,
    WaylandPortalBackend,
    detect_wayland,
    select_eye_backend,
)


def _png(color=(10, 20, 30), size=(40, 24)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# detection
# --------------------------------------------------------------------------- #
def test_detect_wayland_reports_x11_session_without_raising(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    info = detect_wayland(":0")
    assert info["is_wayland"] is False
    assert info["session_type"] == "x11"


def test_detect_wayland_on_wayland_session_is_side_effect_free(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    info = detect_wayland()
    assert info["is_wayland"] is True
    assert "portal" in info and "remote_desktop" in info and "pipewire" in info


# --------------------------------------------------------------------------- #
# portal client protocol
# --------------------------------------------------------------------------- #
class _FakeIface:
    def __init__(self, bus) -> None:
        self.bus = bus

    def Screenshot(self, options):  # noqa: N802 - portal method name
        self.bus.requested = True
        return "/org/freedesktop/portal/desktop/request/1"


class _FakeDbus:
    class Dictionary(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

    def __init__(self, bus) -> None:
        self.bus = bus

    def Interface(self, obj, name):  # noqa: N802 - dbus API
        return _FakeIface(self.bus)


class _FakeBus:
    def __init__(self, uri=None, deliver=True) -> None:
        self.uri = uri
        self.deliver = deliver
        self.receiver = None
        self.requested = False

    def get_object(self, *_args):
        return object()

    def add_signal_receiver(self, callback, **_kwargs):
        self.receiver = callback
        return "match-1"

    def remove_signal_receiver(self, _match):
        self.receiver = None

    def read_write_dispatch(self, _timeout):
        if self.deliver and self.receiver is not None and self.requested:
            self.receiver(0, {"uri": self.uri})


def test_portal_client_reads_uri_and_returns_bytes():
    png = _png()
    bus = _FakeBus(uri="file:///tmp/shot.png")
    client = DbusPortalScreenshot(bus=bus, dbus_module=_FakeDbus(bus), timeout=2.0,
                                  uri_reader=lambda uri: png)
    assert client.grab_png() == png


def test_portal_client_times_out_without_response():
    bus = _FakeBus(uri="file:///tmp/shot.png", deliver=False)
    client = DbusPortalScreenshot(bus=bus, dbus_module=_FakeDbus(bus), timeout=0.2,
                                  uri_reader=lambda uri: b"never")
    assert client.grab_png() is None
    assert client.last_error()


# --------------------------------------------------------------------------- #
# backend
# --------------------------------------------------------------------------- #
class _FakeClient:
    def __init__(self, frames, available=True):
        self.frames = list(frames)
        self._available = available
        self.calls = 0

    def available(self):
        return self._available

    def grab_png(self, timeout=None):
        self.calls += 1
        return self.frames.pop(0) if self.frames else None


def test_backend_degrades_when_portal_unavailable():
    backend = WaylandPortalBackend(client=_FakeClient([], available=False))
    state = backend.snapshot(0)
    assert state.source == "wayland-unavailable"
    assert state.confidence == 0.0
    assert state.frame_bytes is None


def test_backend_degrades_when_screenshot_fails():
    backend = WaylandPortalBackend(client=_FakeClient([None], available=True))
    assert backend.snapshot(0).source == "wayland-unavailable"


def test_backend_produces_screen_state_from_portal_png():
    first = _png((0, 0, 0))
    second = _png((255, 255, 255))
    backend = WaylandPortalBackend(client=_FakeClient([first, second]))
    state1 = backend.snapshot(0)
    assert state1.source == "wayland-portal" and state1.confidence == 0.6
    assert (state1.width, state1.height) == (40, 24)
    assert state1.changed is True           # first frame counts as changed
    assert state1.frame_bytes == first
    state2 = backend.snapshot(1)
    assert state2.changed is True           # black -> white
    assert state2.changed_ratio > 0.5


# --------------------------------------------------------------------------- #
# backend selection
# --------------------------------------------------------------------------- #
class _Settings:
    def __init__(self, display):
        self.display = display


def test_select_eye_backend_prefers_x11_when_not_wayland(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    from blaxcy.eye import X11EyeBackend

    assert isinstance(select_eye_backend(_Settings(":0")), X11EyeBackend)


def test_select_eye_backend_uses_fake_without_display(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    from blaxcy.eye import FakeEyeBackend

    assert isinstance(select_eye_backend(_Settings("")), FakeEyeBackend)


def test_select_eye_backend_falls_back_when_portal_unavailable(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    from blaxcy.eye import X11EyeBackend

    backend = select_eye_backend(_Settings(":0"), client=_FakeClient([], available=False))
    assert isinstance(backend, X11EyeBackend)
