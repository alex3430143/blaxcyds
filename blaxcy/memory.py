"""Persistent experience memory.

Stores what happened, what worked/failed and why, useful strategies, environment
facts, and user preferences. Every record carries provenance (source), a trust
level, a confidence, a timestamp and optional expiry. Content is redacted before
storage so secrets are not persisted.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .logging_utils import redact
from .models import MemoryRecord, TrustLevel

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id          TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    kind        TEXT NOT NULL,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL,
    trust       TEXT NOT NULL,
    confidence  REAL NOT NULL,
    tags        TEXT NOT NULL DEFAULT '',
    expires_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_records_kind ON records(kind);
CREATE INDEX IF NOT EXISTS idx_records_created ON records(created_at);
"""


class Memory:
    """Thread-safe SQLite experience store.

    The service host (`ServiceServer`) is thread-per-connection, so several
    handlers can call into one `Memory` at once. SQLite connections are not safe
    for concurrent statement execution even with `check_same_thread=False`
    (observed as `bad parameter or other API misuse` under load), so every
    public method serializes on a re-entrant lock. `recent_lessons` -> `query`
    is therefore safe too.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # write -----------------------------------------------------------------
    def add(self, content: str, *, kind: str = "experience", source: str = "blaxcy",
            trust: TrustLevel = TrustLevel.DERIVED, confidence: float = 0.5,
            tags: list[str] | None = None, expires_at: float | None = None) -> MemoryRecord:
        record = MemoryRecord(
            content=redact(content),
            kind=kind,
            source=source,
            trust=trust,
            confidence=max(0.0, min(1.0, float(confidence))),
            tags=list(tags or []),
            expires_at=expires_at,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO records (id, created_at, kind, content, source, trust, confidence, tags, expires_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (record.record_id, record.created_at, record.kind, record.content, record.source,
                 record.trust.value, record.confidence, ",".join(record.tags), record.expires_at),
            )
            self._conn.commit()
        return record

    # read ------------------------------------------------------------------
    def query(self, text: str | None = None, *, kind: str | None = None,
              tag: str | None = None, min_confidence: float = 0.0,
              trusted_only: bool = False, include_expired: bool = False,
              limit: int = 20) -> list[MemoryRecord]:
        clauses: list[str] = []
        params: list[object] = []
        if text:
            clauses.append("content LIKE ?")
            params.append(f"%{text}%")
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if tag:
            clauses.append("(',' || tags || ',') LIKE ?")
            params.append(f"%,{tag},%")
        if min_confidence:
            clauses.append("confidence >= ?")
            params.append(min_confidence)
        if trusted_only:
            clauses.append("trust IN ('trusted','derived')")
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(time.time())
        sql = "SELECT * FROM records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row(r) for r in rows]

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return self._row(row) if row else None

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])

    # maintenance -----------------------------------------------------------
    def forget(self, record_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def forget_expired(self, now: float | None = None) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM records WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now if now is not None else time.time(),))
            self._conn.commit()
            return cur.rowcount

    def recent_lessons(self, limit: int = 5) -> list[MemoryRecord]:
        return self.query(kind="lesson", limit=limit)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            record_id=row["id"],
            created_at=row["created_at"],
            kind=row["kind"],
            content=row["content"],
            source=row["source"],
            trust=TrustLevel(row["trust"]),
            confidence=row["confidence"],
            tags=[t for t in row["tags"].split(",") if t],
            expires_at=row["expires_at"],
        )


# --------------------------------------------------------------------------- #
# service split (Phase-3): the same `Memory`, served over authenticated IPC
# --------------------------------------------------------------------------- #
class MemoryService:
    """The experience store, served over IPC (runs inside `blaxcy serve memory`).

    Only these methods are reachable, and every argument is type/range checked.
    Exactly one process owns the SQLite file, which avoids cross-process write
    races on the database.
    """

    def __init__(self, settings: Any) -> None:
        from .service import ServiceServer, service_socket

        self.settings = settings
        self.memory = Memory(settings.memory_path)
        self.server = ServiceServer(
            "memory", self._handlers(),
            service_socket(settings, "memory"), settings.ipc_secret())

    def _handlers(self) -> dict[str, Any]:
        return {
            "health": self._health,
            "add": self._add,
            "query": self._query,
            "get": self._get,
            "count": self.memory.count,
            "forget": self.memory.forget,
            "forget_expired": self._forget_expired,
            "recent_lessons": self._recent_lessons,
        }

    def _health(self) -> dict[str, Any]:
        return {"ok": True, "pid": os.getpid(), "service": "memory",
                "records": self.memory.count()}

    def _add(self, content: str = "", kind: str = "experience", source: str = "blaxcy",
             trust: str = "derived", confidence: float = 0.5,
             tags: list[str] | None = None, expires_at: float | None = None) -> dict[str, Any]:
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        record = self.memory.add(
            content, kind=str(kind), source=str(source),
            trust=TrustLevel(str(trust)), confidence=float(confidence),
            tags=list(tags or []),
            expires_at=float(expires_at) if expires_at is not None else None)
        return record.to_dict()

    def _query(self, text: str | None = None, kind: str | None = None,
               tag: str | None = None, min_confidence: float = 0.0,
               trusted_only: bool = False, include_expired: bool = False,
               limit: int = 20) -> list[dict[str, Any]]:
        records = self.memory.query(
            text, kind=kind, tag=tag, min_confidence=float(min_confidence),
            trusted_only=bool(trusted_only), include_expired=bool(include_expired),
            limit=max(1, min(int(limit), 10_000)))
        return [r.to_dict() for r in records]

    def _get(self, record_id: str) -> dict[str, Any] | None:
        record = self.memory.get(str(record_id))
        return record.to_dict() if record else None

    def _forget_expired(self, now: float | None = None) -> int:
        return self.memory.forget_expired(now=now)

    def _recent_lessons(self, limit: int = 5) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.memory.recent_lessons(limit=int(limit))]

    def run_forever(self) -> None:
        try:
            self.server.run_forever()
        finally:
            self.memory.close()


class RemoteMemory:
    """Client-side Memory that talks to `MemoryService` over IPC.

    Mirrors the `Memory` API and returns real `MemoryRecord` objects. There is no
    in-process fallback: if the service is down a call raises, so missing data is
    never mistaken for an empty (valid) result. `health()` surfaces the state.
    """

    def __init__(self, settings: Any, client: Any = None) -> None:
        from .service import ServiceClient, service_socket

        if client is not None:
            self._client = client
        else:
            self._client = ServiceClient(service_socket(settings, "memory"),
                                         settings.ipc_secret())
        self.degraded_calls = 0
        self.last_error: str | None = None

    # transport -------------------------------------------------------------
    def _call(self, method: str, **args: Any) -> Any:
        try:
            return self._client.call(method, **args)
        except Exception as exc:  # noqa: BLE001
            self.degraded_calls += 1
            self.last_error = str(exc)
            raise

    @staticmethod
    def _record(raw: Any) -> MemoryRecord:
        return MemoryRecord.from_dict(raw)

    # Memory API ------------------------------------------------------------
    def add(self, content: str, *, kind: str = "experience", source: str = "blaxcy",
            trust: TrustLevel = TrustLevel.DERIVED, confidence: float = 0.5,
            tags: list[str] | None = None, expires_at: float | None = None) -> MemoryRecord:
        return self._record(self._call(
            "add", content=content, kind=kind, source=source, trust=trust.value,
            confidence=confidence, tags=list(tags or []), expires_at=expires_at))

    def query(self, text: str | None = None, *, kind: str | None = None,
              tag: str | None = None, min_confidence: float = 0.0,
              trusted_only: bool = False, include_expired: bool = False,
              limit: int = 20) -> list[MemoryRecord]:
        rows = self._call("query", text=text, kind=kind, tag=tag,
                          min_confidence=min_confidence, trusted_only=trusted_only,
                          include_expired=include_expired, limit=limit)
        return [self._record(r) for r in rows or []]

    def get(self, record_id: str) -> MemoryRecord | None:
        raw = self._call("get", record_id=record_id)
        return self._record(raw) if raw else None

    def count(self) -> int:
        return int(self._call("count"))

    def forget(self, record_id: str) -> bool:
        return bool(self._call("forget", record_id=record_id))

    def forget_expired(self, now: float | None = None) -> int:
        return int(self._call("forget_expired", now=now))

    def recent_lessons(self, limit: int = 5) -> list[MemoryRecord]:
        return [self._record(r) for r in self._call("recent_lessons", limit=limit) or []]

    def close(self) -> None:
        """No-op: the service process owns the database connection."""

    # diagnostics -----------------------------------------------------------
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
