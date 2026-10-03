"""Structured, privacy-conscious logging.

Every record is a single JSON object with a component tag and optional task /
action / correlation ids. A redaction pass scrubs common secret shapes before a
record is written, so credentials never land in logs.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

# Patterns for common secret shapes. Keep this conservative: redact, never log.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"\b(sk-[A-Za-z0-9]{12,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\b(ghp_[A-Za-z0-9]{20,})\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd)\b\s*[:=]\s*(\"[^\"]*\"|'[^']*'|\S+)"),
     r"\1=[REDACTED]"),
    (re.compile(r"(?i)\b(authorization|bearer)\b\s*[:=]?\s*\S+"), "authorization=[REDACTED]"),
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), "[REDACTED_HASH]"),
)

_SENSITIVE_KEYS = {"password", "passwd", "secret", "token", "api_key", "apikey",
                   "authorization", "cookie", "set-cookie", "private_key", "credential"}


def redact(text: str) -> str:
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def redact_value(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: redact_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, key) for v in value]
    if isinstance(value, str):
        if key.lower() in _SENSITIVE_KEYS:
            return "[REDACTED]"
        return redact(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "component": getattr(record, "component", record.name),
            "msg": redact(record.getMessage()),
        }
        for attr in ("task_id", "action_id", "correlation_id", "model", "tool", "event"):
            val = getattr(record, attr, None)
            if val is not None:
                base[attr] = val
        extra = getattr(record, "data", None)
        if extra is not None:
            base["data"] = redact_value(extra)
        if record.exc_info:
            base["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(base, default=str)


def get_logger(component: str, log_path: str | None = None, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(f"blaxcy.{component}")
    if logger.handlers:
        return logger
    logger.setLevel(level)
    logger.propagate = False

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(JsonFormatter())
    logger.addHandler(stream)

    if log_path:
        try:
            from pathlib import Path

            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(JsonFormatter())
            logger.addHandler(fh)
        except OSError:
            pass  # logging must never crash the app
    return logger


def log_event(logger: logging.Logger, msg: str, *, event: str = "event",
              data: dict[str, Any] | None = None, **fields: Any) -> None:
    extra = {"event": event, "component": logger.name.split(".", 1)[-1], "data": data or {}}
    extra.update({k: v for k, v in fields.items() if v is not None})
    logger.info(msg, extra=extra)


def _now() -> float:
    return time.time()
