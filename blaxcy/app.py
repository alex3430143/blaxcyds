"""Application wiring.

Builds the components and their lifecycle so the CLI, the panel and tests all
compose the same stack. Backend selection is safety-first: unless real input is
explicitly enabled *and* a display exists, the Body runs in dry-run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .body import Body, make_backend
from .brain import Router, default_registry
from .config import Settings, load_settings, normalize_split, project_root
from .credentials import CredentialStore
from .delegation import DelegationTool
from .eye import (
    AtspiBackend,
    Eye,
    VisionBackend,
    detect_session,
    session_is_usable,
)
from .logging_utils import get_logger
from .memory import Memory
from .orchestrator import Orchestrator, RulePlanner
from .policy import Policy, max_risk_from_str
from .recovery import RecoveryManager
from .service import ProcessComponent, service_command, service_socket
from .state_store import StateStore
from .supervisor import Supervisor
from .tools.browser import BrowserTool
from .ui.panel import PanelController
from .verifier import Verifier


class Application:
    def __init__(self, settings: Settings | None = None, *, eye_backend: Any = None,
                 body_backend: str | None = None, planner: Any = None,
                 split: str | tuple[str, ...] | list[str] | None = None) -> None:
        self.settings = settings or load_settings()
        self.settings.ensure_dirs()
        self.logger = get_logger("app", str(self.settings.log_path))

        self.policy = Policy(
            max_risk=max_risk_from_str(self.settings.max_risk),
            real_input_enabled=self.settings.real_input_enabled,
        )
        self.state_store = StateStore(Path(self.settings.state_dir) / "state.json")

        # Optional process split. The default stays fully in-process (backward
        # compatible); `BLAXCY_SPLIT`/`--split` selects components to isolate.
        # Normalize `all`/`full`, comma strings, and unknown names in one place.
        self.split = (normalize_split(split) if split is not None
                      else tuple(self.settings.split_components))
        self.processes: dict[str, ProcessComponent] = {}

        # Memory: one process owns the SQLite file when split, so there are no
        # cross-process write races. In-process by default.
        if "memory" in self.split:
            from .memory import RemoteMemory

            self.processes["memory"] = self._make_service_process("memory")
            self.memory: Any = RemoteMemory(self.settings)
        else:
            self.memory = Memory(self.settings.memory_path)

        # Brain: model calls can be slow/remote, so isolating them protects
        # perception and control. Provider routing/fallback are unchanged.
        if "brain" in self.split:
            from .brain.service import RemoteBrain

            self.processes["brain"] = self._make_service_process("brain")
            self.registry = None
            self.router: Any = RemoteBrain(self.settings)
        else:
            self.registry = default_registry()
            self.router = Router(self.registry)

        # Advanced perception/credential layers. Vision is injected so the Eye can
        # OCR/CV a frame on demand; AT-SPI is attached to the X11 backend so
        # window metadata carries real application identity when available.
        self.vision = VisionBackend()
        self.atspi = AtspiBackend()
        self.credentials = CredentialStore()
        from .eye.wayland import detect_wayland, select_eye_backend

        self.wayland = detect_wayland(self.settings.display)

        # Eye: run it in its own supervised process and talk over authenticated
        # IPC. Default stays in-process.
        self.eye_process: ProcessComponent | None = None
        if "eye" in self.split and eye_backend is None:
            from .eye.service import RemoteEye

            self.eye_process = self._make_service_process("eye")
            self.processes["eye"] = self.eye_process
            self.eye = RemoteEye(self.settings)
        else:
            if eye_backend is None:
                eye_backend = select_eye_backend(self.settings, atspi=self.atspi)
            self.eye = Eye(eye_backend, interval_s=self.settings.frame_interval_s,
                           persist_frames=self.settings.persist_frames, vision=self.vision)

        if body_backend is not None:
            backend_name = body_backend
        elif self.settings.real_input_enabled and self.settings.display:
            backend_name = "auto"
        else:
            backend_name = "dry-run"
        self.backend_name = backend_name
        self.body = Body(make_backend(backend_name), self.policy)

        if planner is None:
            if getattr(self.settings, "planner", "rules") == "model":
                from .planning import ModelPlanner

                planner = ModelPlanner(self.router, RulePlanner(self.router))
            else:
                planner = RulePlanner(self.router)

        self.verifier = Verifier(self.eye)
        self.orchestrator = Orchestrator(
            settings=self.settings, policy=self.policy, eye=self.eye, body=self.body,
            router=self.router, memory=self.memory, logger=self.logger,
            state_store=self.state_store, verifier=self.verifier,
            recovery=RecoveryManager(), planner=planner)

        self.browser = BrowserTool(self.body, self.policy)
        self.delegator = DelegationTool(self.router, memory=self.memory, policy=self.policy)

        self.supervisor = Supervisor(body=self.body, state_store=self.state_store)
        for process in self.processes.values():
            self.supervisor.register_process(process)
        if "eye" not in self.processes:
            self.supervisor.register("eye", self.eye.start, self.eye.stop,
                                     health=self.eye.health)
        self.panel = PanelController(self.policy)

    # service helpers -------------------------------------------------------
    def _make_service_process(self, name: str) -> ProcessComponent:
        # The child must resolve the same runtime root (and therefore the same
        # socket paths and IPC secret) as this process, even when Settings.root
        # is overridden (e.g. in tests). `cwd` stays at the package root so
        # `python -m blaxcy` is importable regardless of the runtime root.
        return ProcessComponent(
            name, service_command(name),
            socket_path=service_socket(self.settings, name),
            secret=self.settings.ipc_secret(),
            env={"BLAXCY_ROOT": str(self.settings.root)},
            cwd=str(project_root()),
            log_path=Path(self.settings.runtime_dir) / "logs" / f"{name}-service.log")

    def service_status(self) -> list[dict[str, Any]]:
        """Honest per-service status: split vs in-process, running, pid, health.

        Never reports a service as healthy unless its process answers; a socket
        that does not exist is reported `stopped`, and a failing health probe
        carries the real error.
        """
        sup_health = self.supervisor.health()
        statuses: list[dict[str, Any]] = []

        def supervisor_fields(name: str) -> dict[str, Any]:
            info = sup_health.get(name, {}) or {}
            return {"state": info.get("state"), "restarts": info.get("restarts", 0),
                    "last_error": info.get("last_error")}

        for name, process in self.processes.items():
            process_health: dict[str, Any] | None = None
            error: str | None = None
            running = process.is_running()
            if running:
                try:
                    process_health = process.health()
                    running = bool(process_health.get("alive"))
                except Exception as exc:  # noqa: BLE001 - report, never crash
                    error = str(exc)
            statuses.append({"name": name, "split": True, "running": running,
                             "pid": getattr(process, "pid", None), "health": process_health,
                             "error": error, **supervisor_fields(name)})
        for name in ("eye",) if "eye" not in self.processes else ():
            fields = supervisor_fields(name)
            statuses.append({"name": name, "split": False,
                             "running": fields["state"] == "running",
                             "pid": None, "health": None, "error": None, **fields})
        return statuses

    # lifecycle -------------------------------------------------------------
    def start(self) -> None:
        self.supervisor.start_all()
        self.supervisor.start_monitor()

    def stop(self) -> None:
        self.supervisor.stop_monitor()
        self.supervisor.stop_all()
        self.memory.close()

    def signal_heartbeat(self) -> None:
        self.body.touch()

    # diagnostics -----------------------------------------------------------
    def doctor(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str, critical: bool = False) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail, "critical": critical})

        py_ok = sys.version_info >= (3, 11)
        add("python", py_ok, f"{sys.version.split()[0]} (need >=3.11)", critical=True)

        session = detect_session(self.settings.display)
        add("display", bool(session["has_display"]),
            f"DISPLAY={session['display'] or '<none>'} type={session['session_type']} "
            f"desktop={session['desktop']}")
        add("wayland", True,
            f"session={self.wayland['session_type'] or 'unknown'} "
            f"wayland_ok={self.wayland['is_wayland']} portal={self.wayland['portal']} "
            f"remote_desktop={self.wayland['remote_desktop']} pipewire={self.wayland['pipewire']}")
        usable, reason = session_is_usable(self.settings.display)
        add("x11_usability", usable, reason, critical=False)

        tools = session["tools"]  # type: ignore[index]
        missing = [t for t, present in tools.items() if not present]  # type: ignore[union-attr]
        add("tools", bool(tools.get("xdotool")) if isinstance(tools, dict) else False,
            f"present={[t for t, p in tools.items() if p]} missing={missing}"  # type: ignore[union-attr]
            if isinstance(tools, dict) else "unknown")

        modules = sorted(p.name for p in (self.settings.root / "blaxcy").glob("*.py"))
        add("components", len(modules) > 5, f"{len(modules)} modules: {', '.join(modules)}")

        # Service split: report exactly which components are split and whether
        # they are actually answering. A stopped split service is reported as
        # stopped — never as healthy.
        statuses = self.service_status()
        split_statuses = [s for s in statuses if s["split"]]
        if not split_statuses:
            add("services", True, "in-process (default)")
        else:
            def _describe(s: dict[str, Any]) -> str:
                if not s["split"]:
                    return f"{s['name']}=in-process"
                text = f"{s['name']}={'running' if s['running'] else 'stopped'}"
                if s.get("state"):
                    text += f" state={s['state']}"
                if s.get("restarts"):
                    text += f" restarts={s['restarts']}"
                if s.get("pid"):
                    text += f" pid={s['pid']}"
                if s.get("error"):
                    text += f" ({s['error']})"
                return text

            add("services", all(s["running"] for s in split_statuses),
                f"split={[s['name'] for s in split_statuses]}: "
                + ", ".join(_describe(s) for s in statuses)
                + " (started by `blaxcy run`/`blaxcy ui`)")

        try:
            model_rows = self.router.status()
            available = [r["name"] for r in model_rows if r.get("available")]
            add("models", bool(available),
                f"available={available or ['none']} "
                f"configured={[r['name'] for r in model_rows]}")
        except Exception as exc:  # noqa: BLE001 - a split brain not started yet
            add("models", False,
                f"brain unavailable ({exc}); split components start on `blaxcy run`")

        add("real_input", True,
            "ENABLED (live control)" if self.settings.real_input_enabled
            else "disabled (dry-run) — set BLAXCY_ENABLE_REAL_INPUT=1 to enable",
            critical=False)

        try:
            import time as _time

            self.state_store.set("doctor_last_run", _time.time())
            state_ok, state_detail = True, str(Path(self.settings.state_dir) / "state.json")
        except Exception as exc:  # noqa: BLE001
            state_ok, state_detail = False, f"state store unwritable: {exc}"
        add("state_store", state_ok, state_detail, critical=True)

        try:
            test_path = Path(self.settings.runtime_dir) / ".write_test"
            test_path.write_text("ok", encoding="utf-8")
            test_path.unlink()
            add("runtime_writable", True, str(self.settings.runtime_dir), critical=True)
        except OSError as exc:
            add("runtime_writable", False, f"not writable: {exc}", critical=True)

        add("body_backend", True, self.backend_name)
        add("policy", True,
            f"max_risk={self.policy.max_risk.value} emergency_stop={self.policy.emergency_stopped}")

        try:
            caps = self.eye.vision_capabilities()
            add("vision", bool(caps.get("available")),
                f"ocr={bool(caps.get('ocr'))} cv={bool(caps.get('cv'))} "
                f"({'available' if caps.get('available') else 'unavailable'})")
        except Exception as exc:  # noqa: BLE001 - a split eye not started yet
            add("vision", False, f"eye vision unavailable: {exc}")

        try:
            atspi_available = self.atspi.is_available()
            if atspi_available:
                summary = self.atspi.summary()
                detail = f"available windows={summary.get('window_count', 0)}"
            else:
                detail = "unavailable"
            add("accessibility", atspi_available, f"AT-SPI {detail}")
        except Exception as exc:  # noqa: BLE001 - a probe must never break doctor
            add("accessibility", False, f"AT-SPI probe failed: {exc}")

        cred = self.credentials.status()
        add("credentials", True, f"backend={cred['backend']} encrypted={cred['encrypted']}")

        from .browser.cdp import browser_capabilities

        bcaps = browser_capabilities()
        add("browser", bool(bcaps["available"]),
            f"binary={bcaps['binary'] or 'none'} websocket_client={bcaps['websocket_client']}")

        healthy = all(c["ok"] for c in checks if c["critical"])
        return {"ok": healthy, "checks": checks, "backend": self.backend_name,
                "real_input": self.settings.real_input_enabled,
                "split": list(self.split), "planner": getattr(self.settings, "planner", "rules")}
