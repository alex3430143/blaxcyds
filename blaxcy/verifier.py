"""Verification — completion is based on an observed postcondition.

"Action sent" is never treated as "task completed". This module turns a declared
postcondition or a human-readable success criterion into a check against the
live `ScreenState`. Because OCR/vision are not yet implemented, checks use the
signals that are genuinely available: screen change, window existence, window
title, and cursor position. Criteria that need unavailable capabilities return
`ok=False` with an explanatory detail rather than a false success.
"""

from __future__ import annotations

import re
from typing import Any

from .models import Action, ScreenState, VerificationResult


class Verifier:
    def __init__(self, eye: Any) -> None:  # eye exposes .snapshot()/.current()
        self.eye = eye

    # helpers ---------------------------------------------------------------
    def _state(self) -> ScreenState | None:
        current = getattr(self.eye, "current", None)
        if callable(current):
            state = current()
            if state is not None:
                return state
        snap = getattr(self.eye, "snapshot", None)
        if callable(snap):
            try:
                return snap()
            except TypeError:
                return snap(wait=False)
        return None

    # postcondition ---------------------------------------------------------
    def verify_postcondition(self, action: Action, result: Any = None,
                             before: ScreenState | None = None) -> VerificationResult:
        cond = action.expected_postcondition
        if not cond:
            return VerificationResult(ok=True, criterion="none declared",
                                      detail="no postcondition declared")
        after = self._state()
        if after is None:
            return VerificationResult(ok=False, criterion=str(cond),
                                      detail="no screen state available to verify against")
        return self._check_dict(cond, before, after)

    def _check_dict(self, cond: dict[str, Any], before: ScreenState | None,
                    after: ScreenState) -> VerificationResult:
        checks: list[tuple[str, bool, str]] = []

        if "frame_hash_changed" in cond:
            ok = bool(before and before.frame_hash and before.frame_hash != after.frame_hash)
            checks.append(("frame_hash_changed", ok,
                           f"{before.frame_hash if before else None} -> {after.frame_hash}"))
        if "screen_changed" in cond:
            checks.append(("screen_changed", bool(after.changed),
                           f"changed={after.changed} ratio={after.changed_ratio:.3f}"))
        if "window_exists" in cond:
            needle = str(cond["window_exists"]).lower()
            found = any(needle in (w.title or "").lower() or needle in (w.app or "").lower()
                        for w in after.windows)
            checks.append(("window_exists", found, f"windows={len(after.windows)}"))
        if "window_title_contains" in cond:
            needle = str(cond["window_title_contains"]).lower()
            win = after.active_window()
            ok = bool(win and needle in (win.title or "").lower())
            checks.append(("window_title_contains", ok,
                           f"active={(win.title if win else None)!r}"))
        if "active_window_id" in cond:
            checks.append(("active_window_id", after.active_window_id == str(cond["active_window_id"]),
                           f"active={after.active_window_id}"))
        if "cursor_at" in cond:
            want = tuple(cond["cursor_at"])  # type: ignore[arg-type]
            cur = after.cursor
            ok = bool(cur and abs(cur[0] - want[0]) <= 4 and abs(cur[1] - want[1]) <= 4)
            checks.append(("cursor_at", ok, f"cursor={cur}"))
        if "text_contains" in cond:
            checks.append(("text_contains", False,
                           "OCR/accessibility text extraction not implemented"))

        if not checks:
            return VerificationResult(ok=False, criterion=str(cond),
                                      detail="unknown postcondition keys", observed=cond)
        ok = all(c[1] for c in checks)
        return VerificationResult(
            ok=ok, criterion=str(cond),
            detail="; ".join(f"{n}={'ok' if o else 'FAIL'} ({d})" for n, o, d in checks),
            observed={"checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks]},
        )

    # human criterion -------------------------------------------------------
    def verify_criterion(self, criterion: str, before: ScreenState | None = None,
                         timeout: float = 0.0) -> VerificationResult:
        text = criterion.strip()
        low = text.lower()

        def _now() -> ScreenState | None:
            return self._state()

        if "screen changes" in low or "screen change" in low:
            after = _now()
            ok = bool(before and after and before.frame_hash != after.frame_hash)
            return VerificationResult(ok=ok, criterion=text,
                                      detail=f"frame {before.frame_hash if before else None} -> "
                                             f"{after.frame_hash if after else None}")
        m = re.search(r"window title contains ['\"]?(.+?)['\"]?$", low)
        if m:
            needle = m.group(1).strip()
            after = _now()
            win = after.active_window() if after else None
            ok = bool(win and needle in (win.title or "").lower())
            return VerificationResult(ok=ok, criterion=text,
                                      detail=f"active title={win.title if win else None!r}")
        m = re.search(r"window (?:exists|for|titled) ['\"]?(.+?)['\"]?$", low)
        if m:
            needle = m.group(1).strip()
            after = _now()
            ok = bool(after and any(needle in (w.title or "").lower()
                                    or needle in (w.app or "").lower() for w in after.windows))
            return VerificationResult(ok=ok, criterion=text,
                                      detail=f"{len(after.windows) if after else 0} windows")
        if "desktop observed" in low or "observe" in low:
            after = _now()
            return VerificationResult(ok=after is not None and after.confidence > 0,
                                      criterion=text,
                                      detail=f"confidence={after.confidence if after else 0}")
        after = _now()
        return VerificationResult(
            ok=False, criterion=text,
            detail="criterion not machine-verifiable with available capabilities; "
                   "escalate to user or add OCR/accessibility support",
            observed={"has_state": after is not None},
        )
