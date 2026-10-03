"""The BLAXCY control panel.

A docked panel that occupies ~20% of the screen width; the real desktop stays
~80% visible and is never replaced by a simulated one. It shows the goal,
current action, status, model/tool, progress, verification and errors, and offers
pause / resume / emergency-stop / takeover controls wired to Policy.

The Qt widget is import-guarded: the control *logic* (`PanelController`) is plain
Python and fully testable without a display.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

PANEL_WIDTH_RATIO = 0.2  # ~20% of screen width


@dataclass
class PanelState:
    goal: str = ""
    objective_id: str = ""
    current_action: str = ""
    status: str = "idle"
    tool: str = ""
    model: str = ""
    progress: float = 0.0
    verification: str = ""
    errors: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    paused: bool = False
    stopped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class PanelController:
    """Non-GUI control surface. Drives the panel and talks to Policy."""

    def __init__(self, policy: Any) -> None:
        self.policy = policy
        self.state = PanelState()
        self._listeners: list[Callable[[PanelState], None]] = []

    def subscribe(self, listener: Callable[[PanelState], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener(self.state)
            except Exception:  # noqa: BLE001
                pass

    def update(self, **fields: Any) -> PanelState:
        for key, value in fields.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        self._notify()
        return self.state

    def log(self, message: str, limit: int = 200) -> None:
        self.state.log.append(message)
        if len(self.state.log) > limit:
            self.state.log = self.state.log[-limit:]
        self._notify()

    def error(self, message: str) -> None:
        self.state.errors.append(message)
        self.state.errors = self.state.errors[-50:]
        self._notify()

    # controls --------------------------------------------------------------
    def pause(self) -> None:
        self.policy.pause()
        self.update(paused=True, status="paused")

    def resume(self) -> None:
        self.policy.resume()
        self.update(paused=False, status="running")

    def emergency_stop(self) -> None:
        self.policy.emergency_stop()
        self.update(stopped=True, status="emergency_stopped")

    def clear_emergency_stop(self) -> None:
        self.policy.clear_emergency_stop()
        self.update(stopped=False, status="idle")

    def takeover(self) -> None:
        self.policy.request_takeover()
        self.update(status="user_takeover")

    def release_takeover(self) -> None:
        self.policy.clear_takeover()
        self.update(status="idle")


_PANEL_CSS = """
#blaxcy-panel { background: #16171b; color: #e8e8ea; }
#blaxcy-panel QLabel { color: #e8e8ea; }
#blaxcy-goal { font-size: 15px; font-weight: bold; }
#blaxcy-status { color: #9fe3a0; }
#blaxcy-errors { color: #ff9b9b; }
QPushButton { padding: 6px; }
"""


def build_panel(controller: PanelController):  # pragma: no cover - requires a display
    """Construct the Qt widget. Requires PyQt6 and a display."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import (
        QApplication,
        QLabel,
        QListWidget,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    class BlaxcyPanel(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setObjectName("blaxcy-panel")
            self.setStyleSheet(_PANEL_CSS)
            self.setWindowTitle("BLAXCY")
            # Dock to the right, ~20% of the screen, real desktop stays visible.
            screen = QApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                width = int(geo.width() * PANEL_WIDTH_RATIO)
                self.setGeometry(geo.x() + geo.width() - width, geo.y(), width, geo.height())
            layout = QVBoxLayout(self)

            self.goal = QLabel("Goal: —"); self.goal.setObjectName("blaxcy-goal")
            self.status = QLabel("Status: idle"); self.status.setObjectName("blaxcy-status")
            self.action = QLabel("Action: —")
            self.model = QLabel("Model: —")
            self.tool = QLabel("Tool: —")
            self.verify = QLabel("Verification: —")
            self.progress = QProgressBar(); self.progress.setRange(0, 100)
            self.errors = QLabel(""); self.errors.setObjectName("blaxcy-errors")
            self.errors.setWordWrap(True)
            self.log = QListWidget()

            for w in (self.goal, self.status, self.action, self.model, self.tool,
                      self.verify, self.progress, self.errors, self.log):
                layout.addWidget(w)

            btn_pause = QPushButton("Pause")
            btn_resume = QPushButton("Resume")
            btn_stop = QPushButton("Emergency Stop")
            btn_takeover = QPushButton("User Takeover")
            btn_release = QPushButton("Release Takeover")
            btn_pause.clicked.connect(controller.pause)
            btn_resume.clicked.connect(controller.resume)
            btn_stop.clicked.connect(controller.emergency_stop)
            btn_takeover.clicked.connect(controller.takeover)
            btn_release.clicked.connect(controller.release_takeover)
            for b in (btn_pause, btn_resume, btn_stop, btn_takeover, btn_release):
                layout.addWidget(b)
            layout.addStretch(1)

            controller.subscribe(self._render)
            self._render(controller.state)

        def _render(self, state: PanelState) -> None:
            self.goal.setText(f"Goal: {state.goal or '—'}")
            self.status.setText(f"Status: {state.status}")
            self.action.setText(f"Action: {state.current_action or '—'}")
            self.model.setText(f"Model: {state.model or '—'}")
            self.tool.setText(f"Tool: {state.tool or '—'}")
            self.verify.setText(f"Verification: {state.verification or '—'}")
            self.progress.setValue(int(state.progress * 100))
            self.errors.setText("\n".join(state.errors[-3:]))
            self.log.clear()
            self.log.addItems(state.log[-40:])

    return BlaxcyPanel()


def run_panel(controller: PanelController, argv: list[str] | None = None) -> int:  # pragma: no cover
    """Launch the panel. Requires PyQt6 and a display; returns a process code."""
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError("PyQt6 is required for the control panel") from exc
    import sys

    app = QApplication(argv or sys.argv)
    panel = build_panel(controller)
    panel.show()
    return app.exec()
