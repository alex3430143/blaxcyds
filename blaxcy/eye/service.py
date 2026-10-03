"""Run the Eye as a supervised process (Phase-3 process split).

The Eye is the natural first component to isolate: it runs a continuous sampler
that is CPU-heavy, so keeping it out of the orchestrator process is a genuine
win. This module provides:

* `build_eye(settings)` — the exact same Eye the in-process app builds;
* `EyeService` — serves the Eye over the authenticated IPC with an explicit
  whitelist of methods;
* `RemoteEye` — a drop-in client that mirrors the Eye's public API and can fall
  back to a local Eye (recording that it degraded) if the service is down.

Nothing here fakes perception: `RemoteEye` forwards to the real Eye running in
the service, and reconstructs the real `ScreenState` from the wire.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from ..config import Settings
from ..service import ServiceClient, ServiceServer, service_socket
from .atspi import AtspiBackend
from .vision import VisionBackend
from .wayland import select_eye_backend
from .x11 import Eye


def build_eye(settings: Settings) -> Eye:
    """Build an Eye exactly as `Application` does (backend + vision + AT-SPI)."""
    vision = VisionBackend()
    atspi = AtspiBackend()
    backend = select_eye_backend(settings, atspi=atspi)
    return Eye(backend, interval_s=settings.frame_interval_s,
               persist_frames=settings.persist_frames, vision=vision)


def _encode_state(state: Any) -> dict[str, Any] | None:
    return None if state is None else state.to_dict(include_frame=False)


def _region(value: Any) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    return tuple(int(v) for v in value)  # type: ignore[return-value]


class EyeService:
    """The Eye, served over IPC (runs inside `blaxcy serve eye`)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.eye = build_eye(settings)
        self.server = ServiceServer(
            "eye", self._handlers(),
            service_socket(settings, "eye"), settings.ipc_secret())

    def _handlers(self) -> dict[str, Any]:
        eye = self.eye
        return {
            "health": eye.health,
            "start": self._start,
            "stop": eye.stop,
            "current": lambda: _encode_state(eye.current()),
            "snapshot": lambda wait=True, timeout=2.0: _encode_state(
                eye.snapshot(wait=wait, timeout=timeout)),
            "latency": eye.latency,
            "vision_capabilities": eye.vision_capabilities,
            "ocr": lambda region=None: eye.ocr(_region(region)),
            "find_text": lambda needle, region=None, min_conf=40.0: eye.find_text(
                needle, region=_region(region), min_conf=min_conf),
            "contains_text": lambda needle, region=None: eye.contains_text(
                needle, region=_region(region)),
            "ui_regions": lambda region=None: eye.ui_regions(_region(region)),
            "accessibility": eye.accessibility,
            "current_frame": self._current_frame,
        }

    def _start(self) -> dict[str, Any]:
        self.eye.start()
        return {"started": True}

    def _current_frame(self) -> dict[str, Any]:
        frame = self.eye.current_frame()
        return {"frame_b64": base64.b64encode(frame).decode("ascii") if frame else None}

    def run_forever(self) -> None:
        self.eye.start()
        # Warm the first frame *before* accepting requests so callers never see a
        # cold, empty state (the first X11 frame costs ~5s of setup). A locked or
        # headless session still returns a state immediately, so this never hangs.
        self.eye.snapshot(wait=True, timeout=30.0)
        try:
            self.server.run_forever()
        finally:
            self.eye.stop()


class RemoteEye:
    """Client-side Eye that talks to `EyeService` over IPC.

    Mirrors the Eye's public API. If a `fallback` Eye is provided it is used when
    the service is unreachable; the degradation is counted and reported in
    `health()` so it is never silent.
    """

    def __init__(self, settings: Settings, *, client: ServiceClient | None = None,
                 fallback: Any = None) -> None:
        self.socket_path = str(service_socket(settings, "eye"))
        self._client = client or ServiceClient(self.socket_path, settings.ipc_secret())
        self.fallback = fallback
        self.degraded_calls = 0
        self.last_error: str | None = None

    # transport -------------------------------------------------------------
    def _call(self, method: str, **args: Any) -> Any:
        try:
            return self._client.call(method, **args)
        except Exception as exc:  # noqa: BLE001
            if self.fallback is None:
                raise
            self.degraded_calls += 1
            self.last_error = str(exc)
            return getattr(self.fallback, method)(**args)

    def _state(self, raw: Any) -> Any:
        if raw is None:
            return None
        from .screen_state import ScreenState

        return ScreenState.from_dict(raw) if isinstance(raw, dict) else raw

    # Eye API ---------------------------------------------------------------
    def start(self) -> None:
        self._call("start")

    def stop(self) -> None:
        self._call("stop")

    def health(self) -> dict[str, Any]:
        base: dict[str, Any]
        try:
            payload = self._client.call("health")
            base = dict(payload) if isinstance(payload, dict) else {"health": payload}
        except Exception as exc:  # noqa: BLE001
            base = {"service_reachable": False, "error": str(exc)}
        base["remote"] = True
        base["degraded_calls"] = self.degraded_calls
        if self.last_error:
            base["last_error"] = self.last_error
        return base

    def current(self) -> Any:
        return self._state(self._call("current"))

    def snapshot(self, *, wait: bool = True, timeout: float = 2.0) -> Any:
        return self._state(self._call("snapshot", wait=wait, timeout=timeout))

    def wait_for(self, predicate: Any, *, timeout: float = 10.0) -> Any:
        """Block until the service's latest state satisfies `predicate`.

        The predicate runs client-side (it cannot cross the wire); this polls the
        service's current state, so it blocks on state change, not a fixed sleep.
        """
        deadline = time.monotonic() + timeout
        while True:
            state = self.current()
            if predicate(state):
                return state
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)

    def latency(self) -> dict[str, Any]:
        return self._call("latency")

    def vision_capabilities(self) -> dict[str, Any]:
        return self._call("vision_capabilities")

    def ocr(self, region: Any = None) -> str:
        return self._call("ocr", region=list(region) if region else None)

    def find_text(self, needle: str, region: Any = None, min_conf: float = 40.0) -> list:
        return self._call("find_text", needle=needle,
                          region=list(region) if region else None, min_conf=min_conf)

    def contains_text(self, needle: str, region: Any = None) -> bool:
        return bool(self._call("contains_text", needle=needle,
                               region=list(region) if region else None))

    def ui_regions(self, region: Any = None) -> list:
        return self._call("ui_regions", region=list(region) if region else None)

    def accessibility(self) -> dict[str, Any]:
        return self._call("accessibility")

    def current_frame(self) -> bytes | None:
        payload = self._call("current_frame")
        frame = payload.get("frame_b64") if isinstance(payload, dict) else None
        return base64.b64decode(frame) if frame else None

    def subscribe(self, callback: Any) -> None:
        raise NotImplementedError(
            "RemoteEye does not support subscribe(); poll current()/wait_for() "
            "or run the Eye in-process for change callbacks.")
