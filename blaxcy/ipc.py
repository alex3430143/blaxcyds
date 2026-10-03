"""Typed, versioned, authenticated IPC.

A newline-delimited JSON protocol over a Unix domain socket. Each message is an
`IPCMessage` carrying a protocol `version` and an HMAC token derived from a local
shared secret, so a process cannot be driven by a stray client. Components run
in-process today and can be split across processes later without redesign.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import IPC_VERSION, IPCMessage

MAX_LINE = 8 * 1024 * 1024
# A message older/newer than this (clock skew) is rejected, so a captured
# message cannot be replayed indefinitely.
MAX_SKEW_S = 60.0
# Message ids are remembered for at least the skew window; a repeat is a replay.
REPLAY_WINDOW_S = 120.0


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON object hook that refuses duplicate keys (ambiguous/unsafe input)."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate field {key!r}")
        out[key] = value
    return out


def parse_message(raw: str) -> IPCMessage:
    """Parse one wire line, rejecting duplicate JSON fields."""
    try:
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"bad message: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("message must be a JSON object")
    return IPCMessage.from_dict(data)


def sign(secret: str, message: IPCMessage) -> str:
    d = message.to_dict()
    # `ts` is signed too: a tampered timestamp breaks the HMAC rather than
    # silently passing a freshness check.
    body = json.dumps(
        {k: d[k] for k in ("version", "type", "payload", "message_id", "ts")},
        sort_keys=True, separators=(",", ":"), default=str)
    return hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(secret: str, message: IPCMessage) -> bool:
    expected = sign(secret, message)
    return hmac.compare_digest(expected, message.token or "")


class IPCError(Exception):
    pass


class IPCServer:
    """Single-threaded-accept, thread-per-connection line server."""

    def __init__(self, socket_path: str | os.PathLike[str], secret: str,
                 handler: Callable[[IPCMessage], IPCMessage | dict[str, Any]]):
        self.socket_path = Path(socket_path)
        self.secret = secret
        self.handler = handler
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        # message_id -> first-seen time, for replay rejection.
        self._seen: dict[str, float] = {}
        self._seen_lock = threading.Lock()

    def start(self) -> None:
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        self._sock.listen(8)
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, name="blaxcy-ipc", daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            buf = b""
            while self._running:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if len(line) > MAX_LINE:
                        return
                    response = self._dispatch(line)
                    try:
                        conn.sendall(response.to_json().encode("utf-8") + b"\n")
                    except OSError:
                        return

    def _dispatch(self, line: bytes) -> IPCMessage:
        try:
            message = parse_message(line.decode("utf-8"))
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return IPCMessage(type="error", payload={"error": f"bad message: {exc}"})
        # Echo the caller's correlation id when it supplied one, else the message
        # id, so request/response (and action) correlation survives the boundary.
        corr = message.correlation_id or message.message_id
        if message.version != IPC_VERSION:
            return IPCMessage(type="error", correlation_id=corr,
                              payload={"error": f"unsupported version {message.version}"})
        if not verify(self.secret, message):
            return IPCMessage(type="error", correlation_id=corr,
                              payload={"error": "authentication failed"})
        now = time.time()
        if abs(now - message.ts) > MAX_SKEW_S:
            return IPCMessage(type="error", correlation_id=corr,
                              payload={"error": f"stale message (skew {abs(now - message.ts):.1f}s)"})
        if not self._accept_once(message.message_id, now):
            return IPCMessage(type="error", correlation_id=corr,
                              payload={"error": "replay detected"})
        try:
            result = self.handler(message)
        except Exception as exc:  # noqa: BLE001 - IPC must never crash the server
            return IPCMessage(type="error", correlation_id=corr,
                              payload={"error": f"handler error: {exc}"})
        if isinstance(result, IPCMessage):
            result.correlation_id = result.correlation_id or corr
            return result
        return IPCMessage(type="result", correlation_id=corr, payload=result)

    def _accept_once(self, message_id: str, now: float) -> bool:
        """Record a message id; return False if it was already processed."""
        with self._seen_lock:
            if len(self._seen) > 4096:  # bounded memory
                self._seen = {k: v for k, v in self._seen.items()
                              if now - v <= REPLAY_WINDOW_S}
            if message_id in self._seen:
                return False
            self._seen[message_id] = now
            return True

    def stop(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError:
                pass


class IPCClient:
    def __init__(self, socket_path: str | os.PathLike[str], secret: str, timeout: float = 5.0):
        self.socket_path = str(socket_path)
        self.secret = secret
        self.timeout = timeout

    def request(self, type_: str, payload: dict[str, Any] | None = None,
                correlation_id: str = "") -> IPCMessage:
        message = IPCMessage(type=type_, payload=payload or {}, correlation_id=correlation_id)
        message.token = sign(self.secret, message)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
            sock.sendall(message.to_json().encode("utf-8") + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk
        if b"\n" not in buf:
            raise IPCError("no response from server")
        line, _ = buf.split(b"\n", 1)
        return parse_message(line.decode("utf-8"))
