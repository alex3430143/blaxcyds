"""Typed action builders.

Thin constructors so callers (planner, tools, tests) never hand-roll dicts. Each
action still carries its expected postcondition, timeout, risk class and a
correlation id set by `Action`'s defaults.
"""

from __future__ import annotations

from typing import Any

from ..models import Action, ActionKind


def mouse_move(x: int, y: int, **kw: Any) -> Action:
    return Action(kind=ActionKind.MOUSE_MOVE, params={"x": x, "y": y}, **kw)


def click(x: int, y: int, button: int = 1, **kw: Any) -> Action:
    return Action(kind=ActionKind.CLICK, params={"x": x, "y": y, "button": button}, **kw)


def double_click(x: int, y: int, button: int = 1, **kw: Any) -> Action:
    return Action(kind=ActionKind.DOUBLE_CLICK, params={"x": x, "y": y, "button": button}, **kw)


def right_click(x: int, y: int, **kw: Any) -> Action:
    return Action(kind=ActionKind.RIGHT_CLICK, params={"x": x, "y": y}, **kw)


def drag(x1: int, y1: int, x2: int, y2: int, **kw: Any) -> Action:
    return Action(kind=ActionKind.DRAG, params={"x1": x1, "y1": y1, "x2": x2, "y2": y2}, **kw)


def scroll(x: int, y: int, amount: int = -3, **kw: Any) -> Action:
    return Action(kind=ActionKind.SCROLL, params={"x": x, "y": y, "amount": amount}, **kw)


def type_text(text: str, **kw: Any) -> Action:
    return Action(kind=ActionKind.TYPE_TEXT, params={"text": text}, **kw)


def key_press(key: str, **kw: Any) -> Action:
    return Action(kind=ActionKind.KEY_PRESS, params={"key": key}, **kw)


def hotkey(keys: list[str] | str, **kw: Any) -> Action:
    combo = keys if isinstance(keys, str) else "+".join(keys)
    return Action(kind=ActionKind.HOTKEY, params={"keys": combo}, **kw)


def window_switch(window_id: str, **kw: Any) -> Action:
    return Action(kind=ActionKind.WINDOW_SWITCH, params={"window_id": window_id}, **kw)


def app_launch(command: str, **kw: Any) -> Action:
    return Action(kind=ActionKind.APP_LAUNCH, params={"command": command}, **kw)


def clipboard_set(text: str, **kw: Any) -> Action:
    return Action(kind=ActionKind.CLIPBOARD_SET, params={"text": text}, **kw)


def clipboard_get(**kw: Any) -> Action:
    return Action(kind=ActionKind.CLIPBOARD_GET, params={}, **kw)


def wait_for(condition: dict[str, Any], **kw: Any) -> Action:
    return Action(kind=ActionKind.WAIT_FOR, params={"condition": condition}, **kw)


def noop(**kw: Any) -> Action:
    return Action(kind=ActionKind.NOOP, params={}, **kw)
