"""AT-SPI accessibility perception.

Provides structured, high-confidence desktop information — applications, windows,
roles, names and geometry — from the assistive-technology bus. It is an
*additional* perception source alongside visual capture, never a replacement.

This build of at-spi2 does **not** expose `GetDesktop` on the registry, so we
enumerate the accessibility bus directly: each application serves its root
accessible at `/org/a11y/atspi/accessible/root` under its own unique bus name.
Calls use low-level `call_blocking` with a short timeout and the results are
cached, so unresponsive peers (e.g. a hung app sending `NoReply`) cannot stall
perception.

Availability is detected honestly; an unreachable bus degrades to "unavailable".
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

ROOT_PATH = "/org/a11y/atspi/accessible/root"
ACCESSIBLE = "org.a11y.atspi.Accessible"
COMPONENT = "org.a11y.atspi.Component"


@dataclass
class AccessibleNode:
    name: str = ""
    role: str = ""
    app: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    bus: str = ""
    path: str = ""
    children: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class AtspiBackend:
    name = "atspi"

    def __init__(self, timeout: float = 0.4, cache_ttl: float = 5.0) -> None:
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self._conn = None
        self._error: str | None = None
        self._lock = threading.RLock()
        self._cache: tuple[float, list[AccessibleNode]] | None = None
        self._last_scan_s: float = 0.0

    # connection ------------------------------------------------------------
    def _connect(self):
        if self._conn is not None:
            return self._conn
        try:
            import dbus
            from dbus.bus import BusConnection

            bus = dbus.SessionBus()
            obj = bus.get_object("org.a11y.Bus", "/org/a11y/bus")
            addr = obj.GetAddress(dbus_interface="org.a11y.Bus")
            self._conn = BusConnection(addr)
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            self._conn = None
        return self._conn

    def is_available(self) -> bool:
        return self._connect() is not None

    def last_error(self) -> str | None:
        return self._error

    # low-level calls -------------------------------------------------------
    def _call(self, dest: str, path: str, iface: str, method: str,
              signature: str = "", args: tuple = ()):
        import dbus

        conn = self._connect()
        if conn is None:
            return None
        try:
            return conn.call_blocking(dest, path, iface, method, signature, args,
                                      timeout=self.timeout)
        except dbus.exceptions.DBusException:
            return None
        except Exception:  # noqa: BLE001
            return None

    def _name(self, dest: str, path: str = ROOT_PATH) -> str:
        val = self._call(dest, path, ACCESSIBLE, "GetName")
        return str(val) if val is not None else ""

    def _role(self, dest: str, path: str = ROOT_PATH) -> str:
        val = self._call(dest, path, ACCESSIBLE, "GetRoleName")
        return str(val) if val is not None else ""

    def _children(self, dest: str, path: str = ROOT_PATH, limit: int = 200) -> list:
        val = self._call(dest, path, ACCESSIBLE, "GetChildren")
        return list(val)[:limit] if val else []

    def _extents(self, dest: str, path: str) -> tuple[int, int, int, int]:
        val = self._call(dest, path, COMPONENT, "GetExtents", "u", (0,))
        if not val:
            return (0, 0, 0, 0)
        try:
            x, y, w, h = (int(v) for v in val)
            return (x, y, w, h)
        except (TypeError, ValueError):
            return (0, 0, 0, 0)

    # enumeration -----------------------------------------------------------
    def _bus_names(self) -> list[str]:
        conn = self._connect()
        if conn is None:
            return []
        try:
            return [str(n) for n in conn.list_names() if str(n).startswith(":")]
        except Exception:  # noqa: BLE001
            return []

    def _scan(self) -> list[AccessibleNode]:
        started = time.monotonic()
        nodes: list[AccessibleNode] = []
        for dest in self._bus_names():
            name = self._name(dest)
            if not name:
                continue  # not an accessible application
            role = self._role(dest)
            kids = self._children(dest, ROOT_PATH, 40)
            if not kids:
                nodes.append(AccessibleNode(name=name, role=role, app=name, bus=dest,
                                            path=ROOT_PATH, children=0))
                continue
            for ref in kids:
                try:
                    child_dest, child_path = str(ref[0]), str(ref[1])
                except (TypeError, IndexError):
                    continue
                win_name = self._name(child_dest, child_path)
                win_role = self._role(child_dest, child_path)
                x, y, w, h = self._extents(child_dest, child_path)
                nodes.append(AccessibleNode(
                    name=win_name, role=win_role, app=name, x=x, y=y, width=w, height=h,
                    bus=child_dest, path=child_path,
                    children=len(self._children(child_dest, child_path, 50))))
        self._last_scan_s = time.monotonic() - started
        return nodes

    def nodes(self, force: bool = False) -> list[AccessibleNode]:
        with self._lock:
            now = time.monotonic()
            if not force and self._cache and (now - self._cache[0]) < self.cache_ttl:
                return self._cache[1]
            if self._conn is None:
                self._connect()
            result = self._scan()
            self._cache = (now, result)
            return result

    # read API --------------------------------------------------------------
    def apps(self) -> list[AccessibleNode]:
        return [n for n in self.nodes() if n.path == ROOT_PATH or n.role == "application"]

    def windows(self, max_windows: int = 60) -> list[AccessibleNode]:
        out = [n for n in self.nodes() if n.width > 0 and n.height > 0]
        return out[:max_windows]

    def summary(self) -> dict[str, Any]:
        if not self.is_available():
            return {"available": False, "error": self._error, "windows": []}
        nodes = self.nodes()
        windows = [n for n in nodes if n.width > 0 and n.height > 0]
        return {
            "available": True,
            "applications": sorted({n.app for n in nodes}),
            "windows": [w.to_dict() for w in windows],
            "window_count": len(windows),
            "scan_seconds": round(self._last_scan_s, 3),
            "captured_at": time.time(),
        }


def probe() -> dict[str, Any]:
    return AtspiBackend().summary()
