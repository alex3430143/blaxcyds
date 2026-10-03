"""The Eye — live desktop perception.

Runs a background sampler that continuously produces timestamped `ScreenState`
frames with change detection, and exposes `wait_for(condition, timeout)` so the
rest of BLAXCY blocks on *state change*, never on arbitrary sleeps.
"""

from .atspi import AccessibleNode, AtspiBackend
from .screen_state import MonitorInfo, ScreenState, WindowInfo
from .vision import Region, TextBox, VisionBackend
from .x11 import (
    Eye,
    EyeBackend,
    FakeEyeBackend,
    LatencyStats,
    X11EyeBackend,
    capture_root,
    detect_change,
    detect_session,
    session_is_usable,
)

__all__ = [
    "Eye", "EyeBackend", "FakeEyeBackend", "X11EyeBackend", "LatencyStats",
    "detect_change", "detect_session", "session_is_usable", "capture_root",
    "ScreenState", "WindowInfo", "MonitorInfo",
    "VisionBackend", "TextBox", "Region", "AtspiBackend", "AccessibleNode",
]
