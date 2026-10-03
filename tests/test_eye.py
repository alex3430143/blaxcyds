import io
import time

from PIL import Image

from blaxcy.eye import (
    Eye,
    FakeEyeBackend,
    X11EyeBackend,
    detect_change,
    session_is_usable,
)
from blaxcy.eye.screen_state import ScreenState


def _png(color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 36), color).save(buf, format="PNG")
    return buf.getvalue()


def test_detect_change_identical_and_different():
    black = _png((0, 0, 0))
    white = _png((255, 255, 255))
    changed_same, ratio_same = detect_change(black, black)
    changed_diff, ratio_diff = detect_change(black, white)
    assert (changed_same, ratio_same) == (False, 0.0)
    assert changed_diff and ratio_diff > 0.5


def test_detect_change_first_frame_is_changed():
    changed, ratio = detect_change(None, _png((0, 0, 0)))
    assert changed and ratio == 1.0


def test_fake_eye_lifecycle_and_wait_for():
    states = [ScreenState(timestamp=time.time(), width=1, height=1, changed=False),
              ScreenState(timestamp=time.time(), width=1, height=1, changed=True)]
    eye = Eye(FakeEyeBackend(states=states), interval_s=0.005)
    eye.start()
    try:
        assert eye.snapshot(timeout=1.0) is not None
        seen = eye.wait_for(lambda s: s is not None and s.changed, timeout=1.0)
        assert seen is not None
        assert eye.health()["running"]
    finally:
        eye.stop()
    assert not eye.health()["running"]


def test_wait_for_times_out_without_change():
    eye = Eye(FakeEyeBackend(states=[ScreenState(timestamp=time.time(), width=1, height=1,
                                                 changed=False)]), interval_s=0.005)
    eye.start()
    try:
        eye.snapshot(timeout=0.5)
        assert eye.wait_for(lambda s: s is not None and s.changed, timeout=0.1) is None
    finally:
        eye.stop()


def test_frames_not_persisted_by_default():
    def factory(seq):
        return ScreenState(timestamp=time.time(), width=1, height=1, frame_bytes=b"frame")

    eye = Eye(FakeEyeBackend(factory=factory), interval_s=0.005, persist_frames=False)
    eye.start()
    try:
        state = eye.snapshot(timeout=1.0)
        assert state is not None and state.frame_bytes is None
    finally:
        eye.stop()


def test_latency_summary_shape():
    eye = Eye(FakeEyeBackend(factory=lambda seq: ScreenState(timestamp=time.time(), width=1, height=1)))
    eye.start()
    try:
        eye.wait_for(lambda s: s is not None and s.sequence >= 2, timeout=1.0)
        summary = eye.latency()
        assert set(summary) == {"p50", "p95", "mean", "n"}
        assert summary["n"] >= 1
    finally:
        eye.stop()


def test_session_is_usable_without_display():
    usable, reason = session_is_usable("")
    assert not usable
    assert "DISPLAY" in reason


def test_x11_backend_degrades_gracefully_without_display():
    backend = X11EyeBackend(display="")
    state = backend.snapshot(0)
    assert state.confidence == 0.0
    assert state.source == "x11-unavailable"


def test_x11_windows_includes_active_window_beyond_the_cap():
    """Regression: the xdotool fallback capped the window list, so a busy
    desktop could drop the focused window and `active_window()` returned None.
    """
    backend = X11EyeBackend(display="")
    backend._xlib_windows = lambda active_id: None  # force the xdotool fallback
    many = [str(1000 + i) for i in range(70)]  # more windows than the cap

    def fake_run(args):
        cmd = args[1] if len(args) > 1 else ""
        if cmd == "search":
            return "\n".join(many)
        if cmd == "getwindowname":
            return "Some Window"
        if cmd == "getwindowgeometry":
            return "WINDOW=1\nX=1\nY=2\nWIDTH=3\nHEIGHT=4\nSCREEN=0"
        if cmd == "getwindowpid":
            return "42"
        return ""

    backend._run = fake_run
    active = "99999"  # deliberately absent from `many`
    wins = backend.windows(active_id=active)
    assert any(w.window_id == active and w.focused for w in wins)

