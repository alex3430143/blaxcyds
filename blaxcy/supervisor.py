"""Supervisor — keeps components alive and the machine in a safe state.

Starts services, monitors health, detects heartbeat loss, and restarts crashed
components. Critically, before any restart it forces the Body to release all
held buttons/keys, so a crashed component can never leave the desktop with a
stuck input. Restarts are bounded; a component that keeps crashing is marked
DEGRADED/FAILED rather than restarted forever.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .models import ComponentState
from .state_store import StateStore


@dataclass
class Component:
    name: str
    start: Callable[[], None]
    stop: Callable[[], None]
    health: Callable[[], dict[str, Any]] | None = None
    state: ComponentState = ComponentState.STOPPED
    restarts: int = 0
    last_error: str | None = None
    last_checked: float = 0.0

    def probe(self) -> dict[str, Any]:
        self.last_checked = time.time()
        if self.health is None:
            return {"alive": self.state is ComponentState.RUNNING}
        try:
            return self.health()
        except Exception as exc:  # noqa: BLE001
            return {"alive": False, "error": str(exc)}


class Supervisor:
    def __init__(self, *, max_restarts: int = 3, body: Any = None,
                 state_store: StateStore | None = None) -> None:
        self.max_restarts = max_restarts
        self.body = body  # anything exposing panic_release()
        self.state_store = state_store
        self._components: dict[str, Component] = {}
        self._events: list[dict[str, Any]] = []
        self._thread: threading.Thread | None = None
        self._running = False

    # registration ----------------------------------------------------------
    def register(self, name: str, start: Callable[[], None], stop: Callable[[], None],
                 health: Callable[[], dict[str, Any]] | None = None) -> Component:
        comp = Component(name=name, start=start, stop=stop, health=health)
        self._components[name] = comp
        return comp

    def register_process(self, component: Any) -> Component:
        """Register a `ProcessComponent` (or any object exposing name/start/stop/health)."""
        return self.register(component.name, component.start, component.stop,
                             health=component.health)

    def start_all(self) -> None:
        for comp in self._components.values():
            self._safe_start(comp)
        self._persist()

    def stop_all(self) -> None:
        for comp in self._components.values():
            self._safe_stop(comp)
            comp.state = ComponentState.STOPPED
        self._persist()

    def _safe_start(self, comp: Component) -> None:
        try:
            comp.start()
            comp.state = ComponentState.RUNNING
        except Exception as exc:  # noqa: BLE001
            comp.state = ComponentState.FAILED
            comp.last_error = str(exc)
            self._event("start_failed", comp.name, error=str(exc))

    def _safe_stop(self, comp: Component) -> None:
        try:
            comp.stop()
        except Exception as exc:  # noqa: BLE001
            self._event("stop_failed", comp.name, error=str(exc))

    def _safe_release_inputs(self) -> None:
        if self.body is not None:
            try:
                self.body.panic_release()
                self._event("safe_release", "body")
            except Exception as exc:  # noqa: BLE001
                self._event("safe_release_failed", "body", error=str(exc))

    # monitoring ------------------------------------------------------------
    def check_once(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for comp in list(self._components.values()):
            if comp.state not in (ComponentState.RUNNING, ComponentState.DEGRADED):
                continue
            probe = comp.probe()
            if probe.get("alive", True):
                continue
            # heartbeat loss detected
            self._event("heartbeat_lost", comp.name)
            events.append({"component": comp.name, "event": "heartbeat_lost"})
            before_restarts = comp.restarts
            self._restart(comp)
            # Report truthfully: a component that exhausted its restart budget
            # was NOT restarted.
            if comp.restarts == before_restarts and comp.state is ComponentState.FAILED:
                events.append({"component": comp.name, "event": "restart_exhausted",
                               "restarts": comp.restarts, "state": comp.state.value})
            else:
                events.append({"component": comp.name, "event": "restarted",
                               "restarts": comp.restarts, "state": comp.state.value})
        return events

    def _restart(self, comp: Component) -> None:
        # A crashed component must not leave the machine with stuck input.
        self._safe_release_inputs()
        self._safe_stop(comp)
        if comp.restarts >= self.max_restarts:
            comp.state = ComponentState.FAILED
            comp.last_error = "max restarts exceeded"
            self._event("restart_exhausted", comp.name, restarts=comp.restarts)
            self._preserve_checkpoint(comp)
            return
        comp.restarts += 1
        self._safe_start(comp)
        if comp.state is ComponentState.RUNNING:
            comp.state = ComponentState.DEGRADED  # running but recently unhealthy
        self._preserve_checkpoint(comp)

    def _preserve_checkpoint(self, comp: Component) -> None:
        if self.state_store is not None:
            self.state_store.checkpoint(
                f"supervisor:{comp.name}",
                note=f"restart #{comp.restarts} state={comp.state.value}",
                data={"supervisor": {"component": comp.name, "state": comp.state.value,
                                     "restarts": comp.restarts}},
            )

    def _event(self, kind: str, component: str, **data: Any) -> None:
        self._events.append({"at": time.time(), "kind": kind, "component": component, **data})
        self._persist()

    def _persist(self) -> None:
        """Persist restart/health counters so a later CLI run can report them.

        Supervision must never be broken by a persistence failure, so this is
        best-effort.
        """
        if self.state_store is None:
            return
        try:
            self.state_store.set("supervisor", {
                "updated_at": time.time(),
                "components": self.health(),
            })
        except Exception:  # noqa: BLE001 - diagnostics must not break supervision
            pass

    # monitor loop ----------------------------------------------------------
    def start_monitor(self, interval_s: float = 2.0) -> None:
        if self._running:
            return
        self._running = True

        def loop() -> None:
            while self._running:
                self.check_once()
                time.sleep(interval_s)

        self._thread = threading.Thread(target=loop, name="blaxcy-supervisor", daemon=True)
        self._thread.start()

    def stop_monitor(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # reporting -------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return {
            name: {"state": c.state.value, "restarts": c.restarts,
                   "last_error": c.last_error, "last_checked": c.last_checked}
            for name, c in self._components.items()
        }

    def diagnostics(self) -> list[dict[str, Any]]:
        return list(self._events)

    def all_healthy(self) -> bool:
        return all(c.state in (ComponentState.RUNNING, ComponentState.DEGRADED)
                   for c in self._components.values())
