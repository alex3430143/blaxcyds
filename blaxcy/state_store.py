"""Atomic, interruption-safe state persistence.

All writes go through a temp file + `os.replace` (atomic on POSIX) and a `.bak`
copy is kept. If the primary file is corrupt, the store falls back to the
backup and reports that it did so — saved state that cannot be read is never
silently treated as truth.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_SCHEMA = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class TaskRecord:
    task_id: str
    description: str = ""
    expected_result: str = ""
    files: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    status: str = "running"  # running | success | failure | interrupted | partial
    note: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskRecord":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}  # type: ignore[attr-defined]
        return cls(**known)


class StateStore:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recovered_from_corruption = False

    # low level -------------------------------------------------------------
    def _default(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
            "data": {},
            "tasks": [],
            "checkpoints": [],
        }

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default()
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            self.recovered_from_corruption = True
            bak = self.path.with_suffix(self.path.suffix + ".bak")
            if bak.exists():
                try:
                    data = json.loads(bak.read_text(encoding="utf-8"))
                    data.setdefault("notices", []).append(
                        {"at": utc_now_iso(), "msg": "recovered from backup after corruption"})
                    return data
                except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                    pass
            data = self._default()
            data.setdefault("notices", []).append(
                {"at": utc_now_iso(), "msg": "primary state corrupt; backup unusable; reset"})
            return data

    def save(self, data: dict[str, Any]) -> None:
        data["updated_at"] = utc_now_iso()
        tmp = self.path.with_suffix(self.path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
        payload = json.dumps(data, default=str, indent=2, sort_keys=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if self.path.exists():
            try:
                os.replace(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
            except OSError:
                pass
        os.replace(tmp, self.path)

    # convenience -----------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self.load().get("data", {}).get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self.load()
        data.setdefault("data", {})[key] = value
        self.save(data)

    def update_data(self, values: dict[str, Any]) -> None:
        data = self.load()
        data.setdefault("data", {}).update(values)
        self.save(data)

    # tasks -----------------------------------------------------------------
    def begin_task(self, task_id: str, *, description: str = "", expected_result: str = "",
                   files: list[str] | None = None, dependencies: list[str] | None = None,
                   risks: list[str] | None = None) -> TaskRecord:
        data = self.load()
        record = TaskRecord(
            task_id=task_id,
            description=description,
            expected_result=expected_result,
            files=list(files or []),
            dependencies=list(dependencies or []),
            risks=list(risks or []),
        )
        data.setdefault("tasks", []).append(record.to_dict())
        self.save(data)
        return record

    def finish_task(self, task_id: str, *, status: str = "success", note: str = "") -> bool:
        data = self.load()
        for task in reversed(data.get("tasks", [])):
            if task.get("task_id") == task_id and task.get("status") == "running":
                task["status"] = status
                task["note"] = note
                task["finished_at"] = time.time()
                self.save(data)
                return True
        return False

    def mark_interrupted(self) -> list[str]:
        """Any task still 'running' at load time was interrupted. Returns their ids."""
        data = self.load()
        interrupted: list[str] = []
        for task in data.get("tasks", []):
            if task.get("status") == "running":
                task["status"] = "interrupted"
                task["note"] = (task.get("note") or "") + " [marked interrupted at load]"
                interrupted.append(task.get("task_id", ""))
        if interrupted:
            self.save(data)
        return interrupted

    def pending_tasks(self) -> list[dict[str, Any]]:
        return [t for t in self.load().get("tasks", [])
                if t.get("status") in ("running", "interrupted", "partial")]

    # checkpoints -----------------------------------------------------------
    def checkpoint(self, name: str, *, note: str = "", data: dict[str, Any] | None = None) -> None:
        state = self.load()
        state.setdefault("checkpoints", []).append({
            "name": name, "note": note, "at": utc_now_iso(),
            "data": data or {}, "safe": True,
        })
        if data:
            state.setdefault("data", {}).update(data)
        self.save(state)

    def last_checkpoint(self) -> dict[str, Any] | None:
        cps = self.load().get("checkpoints", [])
        return cps[-1] if cps else None

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.load().get("checkpoints", [])[-limit:]


def write_build_state(build_state_dir: str | os.PathLike[str], name: str, content: str) -> Path:
    """Atomically write a `.build-state/` file (e.g. STATE.md)."""
    directory = Path(build_state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path
