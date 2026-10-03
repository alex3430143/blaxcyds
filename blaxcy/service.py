"""Component services: run a component in its own supervised process.

BLAXCY's components are decoupled behind typed contracts (`models.py`) and can
speak over the authenticated IPC (`ipc.py`). This module turns that design into a
real process split:

* `ServiceServer` exposes a component over a Unix socket with an **explicit,
  whitelisted** set of methods (never arbitrary `getattr`).
* `ServiceClient` is the matching caller.
* `ProcessComponent` spawns a service subprocess, waits until it answers an
  authenticated ping, reports health, and can be registered with the existing
  `Supervisor` for restart-on-crash and safe input release.

Only the environment/secret are passed between processes; API keys and the
service socket never appear on a command line.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .ipc import IPCClient, IPCError, IPCServer


class ServiceError(Exception):
    pass


# --------------------------------------------------------------------------- #
# paths / secret
# --------------------------------------------------------------------------- #
def services_dir(settings: Settings) -> Path:
    return Path(settings.runtime_dir) / "services"


def service_socket(settings: Settings, name: str) -> Path:
    return services_dir(settings) / f"{name}.sock"


def service_command(name: str) -> list[str]:
    """Command that runs `blaxcy serve <name>` as a child process."""
    return [sys.executable, "-m", "blaxcy", "serve", name]


SUPERVISOR_PID_ENV = "BLAXCY_SUPERVISOR_PID"
PARENT_CHECK_ENV = "BLAXCY_PARENT_CHECK_S"


def watch_parent(server: "ServiceServer", *, poll_s: float | None = None) -> None:
    """Stop `server` if the supervising parent process goes away.

    A service spawned with `start_new_session=True` would otherwise be orphaned
    and keep running forever if its parent crashes without calling `stop()`.
    The supervisor pid is passed via the environment; a manual `blaxcy serve`
    (no pid) keeps running until signalled or told to shut down.
    """
    parent = os.environ.get(SUPERVISOR_PID_ENV)
    if not parent or not parent.isdigit():
        return
    parent_pid = int(parent)
    interval = poll_s if poll_s is not None else float(os.environ.get(PARENT_CHECK_ENV, "1.0"))

    def loop() -> None:
        while True:
            time.sleep(max(0.05, interval))
            if os.getppid() != parent_pid:
                server.request_stop()
                return
            try:
                os.kill(parent_pid, 0)
            except OSError:
                server.request_stop()
                return

    threading.Thread(target=loop, name="blaxcy-parent-watch", daemon=True).start()


# --------------------------------------------------------------------------- #
# server
# --------------------------------------------------------------------------- #
class ServiceServer:
    """Serve a component's methods over authenticated IPC.

    `handlers` maps a method name to a callable. Only those names are reachable,
    which keeps the attack surface small even on the local socket.
    """

    def __init__(self, name: str, handlers: dict[str, Callable[..., Any]],
                 socket_path: str | os.PathLike[str], secret: str) -> None:
        self.name = name
        self.handlers = dict(handlers)
        self._stop_event = threading.Event()
        self._server = IPCServer(socket_path, secret, self._handle)

    def _handle(self, message: Any) -> dict[str, Any]:
        if message.type == "ping":
            return {"pong": True, "service": self.name}
        if message.type == "capabilities":
            return {"methods": sorted(self.handlers), "service": self.name}
        if message.type == "shutdown":
            threading.Thread(target=self._shutdown, name="blaxcy-svc-stop",
                             daemon=True).start()
            return {"stopping": True}
        if message.type != "call":
            raise ServiceError(f"unsupported message type {message.type!r}")
        method = message.payload.get("method")
        args = message.payload.get("args") or {}
        handler = self.handlers.get(method) if isinstance(method, str) else None
        if handler is None:
            raise ServiceError(f"unknown method {method!r}")
        if not isinstance(args, dict):
            raise ServiceError("args must be a JSON object")
        return {"result": handler(**args)}

    def start(self) -> None:
        self._server.start()

    def stop(self) -> None:
        self._server.stop()

    def request_stop(self) -> None:
        """Stop serving and unblock `run_forever` (signal-handler safe)."""
        self.stop()
        self._stop_event.set()

    def _shutdown(self) -> None:
        time.sleep(0.05)  # let the IPC reply flush before we tear the socket down
        self.request_stop()

    def run_forever(self, poll_s: float = 0.5) -> None:
        self.start()
        try:
            while not self._stop_event.wait(poll_s):
                pass
        finally:
            self.stop()


# --------------------------------------------------------------------------- #
# client
# --------------------------------------------------------------------------- #
class ServiceClient:
    """Call a service's methods over the authenticated IPC."""

    def __init__(self, socket_path: str | os.PathLike[str], secret: str,
                 timeout: float = 5.0) -> None:
        self.socket_path = str(socket_path)
        self.secret = secret
        self.timeout = timeout

    def call(self, method: str, **args: Any) -> Any:
        reply = self._request("call", {"method": method, "args": args})
        return reply.payload.get("result")

    def ping(self) -> dict[str, Any]:
        return self._request("ping").payload

    def capabilities(self) -> dict[str, Any]:
        return self._request("capabilities").payload

    def shutdown(self) -> None:
        try:
            self._request("shutdown")
        except IPCError:
            pass

    def _request(self, type_: str, payload: dict[str, Any] | None = None) -> Any:
        try:
            reply = IPCClient(self.socket_path, self.secret, self.timeout).request(
                type_, payload)
        except (OSError, IPCError) as exc:
            raise ServiceError(f"{self.socket_path}: {exc}") from exc
        if reply.type == "error":
            raise ServiceError(reply.payload.get("error", "service error"))
        return reply


# --------------------------------------------------------------------------- #
# supervised subprocess
# --------------------------------------------------------------------------- #
class ProcessComponent:
    """A component that runs as a child process, for use with `Supervisor`."""

    def __init__(self, name: str, command: list[str], *, socket_path: str | os.PathLike[str],
                 secret: str, env: dict[str, str] | None = None,
                 cwd: str | os.PathLike[str] | None = None,
                 startup_timeout: float = 15.0, client_timeout: float = 5.0,
                 log_path: str | os.PathLike[str] | None = None) -> None:
        self.name = name
        self.command = command
        self.socket_path = Path(socket_path)
        self.secret = secret
        self.env = dict(env or {})
        self.cwd = str(cwd) if cwd is not None else None
        self.startup_timeout = startup_timeout
        self.client_timeout = client_timeout
        self.log_path = Path(log_path) if log_path else None
        self._proc: subprocess.Popen | None = None
        self._log_fh = None
        self.starts = 0

    # lifecycle -------------------------------------------------------------
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        """The current child pid, or None if it has not started/exited."""
        return self._proc.pid if self._proc is not None else None

    def client(self) -> ServiceClient:
        return ServiceClient(self.socket_path, self.secret, self.client_timeout)

    def start(self) -> None:
        if self.is_running():
            return
        self._cleanup_socket()
        env = {**os.environ, **self.env}
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = open(self.log_path, "ab")  # noqa: SIM115 - closed on stop
            out, err = self._log_fh, subprocess.STDOUT
        else:
            out = err = subprocess.DEVNULL
        self._proc = subprocess.Popen(  # noqa: S603 - fixed, our own command
            self.command, env={SUPERVISOR_PID_ENV: str(os.getpid()), **env},
            cwd=self.cwd, start_new_session=True, stdout=out, stderr=err,
        )
        self.starts += 1
        self._wait_ready()

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.startup_timeout
        last = "no response"
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(
                    f"service {self.name!r} exited during startup (rc={self._proc.returncode})")
            try:
                self.client().ping()
                return
            except Exception as exc:  # noqa: BLE001 - keep waiting until the deadline
                last = str(exc)
                time.sleep(0.15)
        raise RuntimeError(
            f"service {self.name!r} not ready within {self.startup_timeout}s ({last})")

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    pass
        if self._log_fh is not None:
            try:
                self._log_fh.close()
            except OSError:
                pass
            self._log_fh = None
        self._cleanup_socket()

    def _cleanup_socket(self) -> None:
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass

    # health ----------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        if not self.is_running():
            return {"alive": False, "reason": "process not running"}
        try:
            payload = self.client().call("health")
        except Exception as exc:  # noqa: BLE001
            return {"alive": False, "error": str(exc)}
        if isinstance(payload, dict):
            return {"alive": True, **payload}
        return {"alive": True, "health": payload}
