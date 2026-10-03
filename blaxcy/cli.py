"""BLAXCY command-line interface.

    blaxcy doctor              detect environment/session/permission/model problems
    blaxcy state               show persistent project/task state
    blaxcy resume              run the universal resume/reconcile protocol
    blaxcy models              list configured models and availability
    blaxcy run "<goal>"        run a high-level goal
    blaxcy browser <action>    drive a real Chrome/Chromium (policy-gated)
    blaxcy delegate "<task>"   delegate to another model and verify the result
    blaxcy ui                  launch the ~20% control panel
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__


def _print(obj: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, default=str))
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            print(f"{key}: {value}")
    else:
        print(obj)


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def cmd_doctor(args: argparse.Namespace) -> int:
    from .app import Application

    app = Application()
    report = app.doctor()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"BLAXCY doctor — {'OK' if report['ok'] else 'PROBLEMS FOUND'}")
        for check in report["checks"]:
            mark = "ok " if check["ok"] else ("FAIL" if check["critical"] else "warn")
            flag = " [critical]" if check["critical"] and not check["ok"] else ""
            print(f"  [{mark}] {check['name']}: {check['detail']}{flag}")
        print(f"\nbackend={report['backend']} real_input={report['real_input']} "
              f"split={report.get('split') or 'in-process'} "
              f"planner={report.get('planner', 'rules')}")
    return 0 if report["ok"] else 1


def cmd_state(args: argparse.Namespace) -> int:
    from .app import Application
    from .config import project_root
    from .recovery import BUILD_STATE_FILES

    app = Application()
    root = project_root()
    state = app.state_store.load()
    build_state = {name: (root / ".build-state" / name).exists() for name in BUILD_STATE_FILES}
    # A split Memory service that is not running must not look like empty memory.
    memory_records: int | None = None
    memory_error: str | None = None
    try:
        memory_records = app.memory.count()
    except Exception as exc:  # noqa: BLE001 - report honestly, never fabricate
        memory_error = str(exc)
    summary = {
        "root": str(root),
        "schema": state.get("schema"),
        "updated_at": state.get("updated_at"),
        "last_checkpoint": app.state_store.last_checkpoint(),
        "pending_tasks": app.state_store.pending_tasks(),
        "tasks": len(state.get("tasks", [])),
        "checkpoints": len(state.get("checkpoints", [])),
        "build_state_files": build_state,
        "memory_records": memory_records,
        "memory_error": memory_error,
        "split": list(app.split),
        "real_input": app.settings.real_input_enabled,
        "body_backend": app.backend_name,
    }
    _print(summary, args.json)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    from .config import project_root
    from .recovery import reconcile, read_build_state

    report = reconcile(project_root())
    payload = report.to_dict()
    if not args.json:
        print(f"mode: {report.mode}")
        print(f"root: {report.root}")
        print(f"package_present: {report.package_present}")
        print(f"modules: {len(report.modules)}")
        print(f"tests: {len(report.tests_present)}")
        print(f"last_checkpoint: {report.last_checkpoint}")
        print(f"interrupted_tasks: {report.interrupted_tasks}")
        print(f"discrepancies: {report.discrepancies}")
        print(f"next_action: {report.next_action}")
        if args.full:
            print("\n--- build state ---")
            for name, content in read_build_state(project_root()).items():
                print(f"\n##### {name} #####\n{content}")
    else:
        print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from .brain import default_registry
    from .brain.router import Router

    router = Router(default_registry())
    rows = router.status()
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        for row in rows:
            state = "available" if row["available"] else "UNAVAILABLE"
            print(f"  [{state}] {row['name']} caps={row['capabilities']} "
                  f"local={row['local']} cost={row['cost']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from .app import Application

    # `Application` normalizes `all`/`full`, comma lists and unknown names.
    app = Application(split=getattr(args, "split", None))
    app.start()
    app.eye.snapshot(wait=True, timeout=3.0)  # let the Eye produce a first frame
    app.panel.update(goal=args.goal, status="running", model="router")
    try:
        result = app.orchestrator.run(args.goal)
    finally:
        app.stop()
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"status: {result.status}  verified={result.verified}")
        print(f"steps: {result.steps_succeeded}/{result.steps_attempted}")
        print(f"detail: {result.detail}")
        for esc in result.escalations:
            print(f"escalation: {esc}")
        if not app.settings.real_input_enabled and not result.verified:
            print("note: real input is disabled (dry-run). "
                  "Set BLAXCY_ENABLE_REAL_INPUT=1 to enable live control.")
    return 0 if result.verified else 1


def cmd_accept_live(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .acceptance import XtermTarget, run_live_acceptance
    from .app import Application

    app = Application()
    app.start()
    try:
        evidence = Path(app.settings.build_state_dir) / "B7_EVIDENCE.md"
        result = run_live_acceptance(policy=app.policy, body=app.body, eye=app.eye,
                                     target=XtermTarget(), evidence_path=evidence)
    finally:
        app.stop()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"verified: {result.verified}  ok: {result.ok}  token: {result.token or '-'}")
        for step in result.steps:
            print(f"  [{'ok ' if step['ok'] else 'FAIL'}] {step['step']}: {step['detail']}")
        if result.evidence.get("refused"):
            print(f"refused: {result.evidence['reason']}")
    return 0 if result.verified else (2 if result.evidence.get("refused") else 1)


def cmd_delegate(args: argparse.Namespace) -> int:
    from .brain import Router, default_registry
    from .delegation import DelegationTool
    from .memory import Memory

    verify = tuple(v.strip() for v in (args.verify or "").split(",") if v.strip())
    router = Router(default_registry())
    memory = Memory(":memory:")
    try:
        tool = DelegationTool(router, memory=memory)
        result = tool.delegate(args.task, capability=args.capability,
                               verify=verify, cross_check=args.cross_check)
    finally:
        memory.close()
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"ok: {result.ok}  verified: {result.verified}  model: {result.model or '-'}")
        print(f"trust: {result.trust.value}")
        if result.degraded:
            print("note: answered by the deterministic offline fallback, not a language "
                  "model — configure a real provider for genuine delegation.")
        for verification in result.verifications:
            mark = "PASS" if verification.ok else "FAIL"
            print(f"  [{mark}] {verification.method}: {verification.detail}")
        if result.error:
            print(f"error: {result.error}")
        if result.output:
            print("\n--- output ---")
            print(result.output)
    return 0 if result.ok else 1


def cmd_browser(args: argparse.Namespace) -> int:
    from .body import Body
    from .browser import BrowserBackend, browser_capabilities
    from .config import load_settings
    from .policy import Policy, max_risk_from_str
    from .tools.browser import BrowserTool

    caps = browser_capabilities()
    if args.action == "status":
        print(json.dumps(caps, indent=2, default=str))
        return 0 if caps["available"] else 1
    if not caps["available"]:
        print("browser control unavailable: no Chrome/Chromium or websocket-client",
              file=sys.stderr)
        return 2

    settings = load_settings()
    policy = Policy(max_risk=max_risk_from_str(settings.max_risk),
                    real_input_enabled=settings.real_input_enabled)
    headless = args.headless or not bool(settings.display)
    body = Body(BrowserBackend(headless=headless), policy)
    tool = BrowserTool(body, policy)
    try:
        if args.url and args.action != "open":
            nav = tool.navigate(args.url)
            if not nav.ok:
                print(f"navigate failed: {nav.error}", file=sys.stderr)
                return 1
        if args.action == "open":
            out = tool.navigate(args.value)
        elif args.action == "query":
            out = tool.query(args.value)
        elif args.action == "title":
            out = tool.title()
        elif args.action == "url":
            out = tool.current_url()
        elif args.action == "eval":
            out = tool.evaluate(args.value, allow_high_risk=args.allow_js)
        elif args.action == "click":
            out = tool.click(args.value)
        elif args.action == "type":
            out = tool.type_text(args.value, args.text or "")
        elif args.action == "shot":
            out = tool.screenshot(args.value or None)
        else:  # pragma: no cover - argparse restricts choices
            print(f"unknown browser action: {args.action}", file=sys.stderr)
            return 2
    finally:
        body.panic_release()

    if args.json:
        print(json.dumps(out.to_dict(), indent=2, default=str))
    else:
        print(f"ok: {out.ok}")
        if out.error:
            print(f"error: {out.error}")
        if out.output is not None:
            if isinstance(out.output, (dict, list)):
                print(json.dumps(out.output, indent=2, default=str))
            else:
                print(out.output)
    return 0 if out.ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    """Run a component service in the foreground (spawned by ProcessComponent)."""
    import signal

    from .config import load_settings
    from .service import watch_parent

    settings = load_settings()
    if args.name == "eye":
        from .eye.service import EyeService

        service: Any = EyeService(settings)
    elif args.name == "memory":
        from .memory import MemoryService

        service = MemoryService(settings)
    elif args.name == "brain":
        from .brain.service import BrainService

        service = BrainService(settings)
    else:  # pragma: no cover - argparse restricts choices
        print(f"unknown service {args.name!r}", file=sys.stderr)
        return 2

    def _stop(signum: int, frame: object) -> None:
        service.server.request_stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    watch_parent(service.server)  # exit if the supervisor dies unexpectedly
    service.run_forever()
    return 0


def cmd_services(args: argparse.Namespace) -> int:
    """Report every splittable service honestly.

    A service is `running` only if its socket answers an authenticated ping; if
    the socket exists but the service does not answer it is `degraded`; if there
    is no socket it is `stopped`. A service can be in-process (the default) or
    split (selected by `BLAXCY_SPLIT`/`--split`).
    """
    from pathlib import Path

    from .config import ALL_COMPONENTS, load_settings
    from .service import ServiceClient, service_socket
    from .state_store import StateStore

    settings = load_settings()
    configured = set(settings.split_components)
    # Restart/health counters are written by the running Application's Supervisor;
    # read the last persisted snapshot so a later CLI run can report them.
    persisted = StateStore(Path(settings.state_dir) / "state.json").get("supervisor") or {}
    persisted_components = persisted.get("components", {}) if isinstance(persisted, dict) else {}
    rows = []
    for name in ALL_COMPONENTS:
        sock = service_socket(settings, name)
        saved = persisted_components.get(name) or {}
        row: dict[str, object] = {
            "name": name, "configured": name in configured, "mode":
            "split" if name in configured else "in-process",
            "socket": str(sock), "running": False, "pid": None,
            "health": None, "error": None,
            "last_state": saved.get("state"), "restarts": saved.get("restarts", 0),
            "last_error": saved.get("last_error"),
            "supervisor_updated_at": persisted.get("updated_at") if isinstance(persisted, dict) else None}
        if sock.exists():
            try:
                client = ServiceClient(sock, settings.ipc_secret(), timeout=2.0)
                health = client.call("health")
                row["health"] = health
                row["running"] = True
                if isinstance(health, dict):
                    row["pid"] = health.get("pid")
            except Exception as exc:  # noqa: BLE001 - report, never crash
                row["error"] = str(exc)
        rows.append(row)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        for row in rows:
            if row["running"]:
                state = "running"
            elif row["error"]:
                state = "degraded"
            else:
                state = "stopped"
            pid = f" pid={row['pid']}" if row["pid"] else ""
            print(f"  [{state}] {row['name']} ({row['mode']}){pid} "
                  f"socket={row['socket']}")
            if row["health"]:
                print(f"        health={row['health']}")
            if row["last_state"] is not None:
                print(f"        last supervisor state={row['last_state']} "
                      f"restarts={row['restarts']}"
                      + (f" last_error={row['last_error']}" if row["last_error"] else ""))
            if row["error"]:
                print(f"        error={row['error']}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from .app import Application
    from .ui.panel import run_panel

    app = Application()
    app.start()
    try:
        return run_panel(app.panel, argv=[sys.argv[0]])
    except RuntimeError as exc:
        print(f"UI unavailable: {exc}", file=sys.stderr)
        return 2
    finally:
        app.stop()


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blaxcy",
                                     description="BLAXCY — an AI like a human computer user")
    parser.add_argument("--version", action="version", version=f"blaxcy {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="detect environment/session/model problems")
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.set_defaults(func=cmd_doctor)

    p_state = sub.add_parser("state", help="show persistent project/task state")
    p_state.add_argument("--json", action="store_true")
    p_state.set_defaults(func=cmd_state)

    p_resume = sub.add_parser("resume", help="run the resume/reconcile protocol")
    p_resume.add_argument("--json", action="store_true")
    p_resume.add_argument("--full", action="store_true", help="also dump build-state files")
    p_resume.set_defaults(func=cmd_resume)

    p_models = sub.add_parser("models", help="list configured models and availability")
    p_models.add_argument("--json", action="store_true")
    p_models.set_defaults(func=cmd_models)

    p_run = sub.add_parser("run", help="run a high-level goal")
    p_run.add_argument("goal")
    p_run.add_argument("--json", action="store_true")
    p_run.add_argument("--split", default=None,
                       help="components to run as separate processes: a comma list "
                            "of eye,memory,brain, or 'all' (default: BLAXCY_SPLIT, "
                            "else in-process)")
    p_run.set_defaults(func=cmd_run)

    from .config import ALL_COMPONENTS

    p_serve = sub.add_parser("serve",
                             help="run a component service in the foreground")
    p_serve.add_argument("name", choices=list(ALL_COMPONENTS))
    p_serve.set_defaults(func=cmd_serve)

    p_services = sub.add_parser("services", help="show component service status")
    p_services.add_argument("--json", action="store_true")
    p_services.set_defaults(func=cmd_services)

    p_browser = sub.add_parser("browser", help="drive a real Chrome/Chromium (policy-gated)")
    p_browser.add_argument(
        "action",
        choices=["status", "open", "query", "eval", "click", "type", "title", "url", "shot"])
    p_browser.add_argument("value", nargs="?", default=None,
                           help="URL / selector / JS / output path")
    p_browser.add_argument("text", nargs="?", default=None, help="text for `type`")
    p_browser.add_argument("--url", default=None, help="navigate here first, then run the action")
    p_browser.add_argument("--allow-js", action="store_true",
                           help="explicitly allow arbitrary page JS (HIGH risk)")
    p_browser.add_argument("--headless", action="store_true", help="force headless mode")
    p_browser.add_argument("--json", action="store_true")
    p_browser.set_defaults(func=cmd_browser)

    p_accept = sub.add_parser("accept-live",
                              help="run the supervised reversible live-desktop test (B7)")
    p_accept.add_argument("--json", action="store_true")
    p_accept.set_defaults(func=cmd_accept_live)

    p_delegate = sub.add_parser("delegate", help="delegate a task to another model and verify it")
    p_delegate.add_argument("task")
    p_delegate.add_argument("--capability", default="reasoning")
    p_delegate.add_argument("--verify", default="", help="comma list: code,json")
    p_delegate.add_argument("--cross-check", action="store_true",
                            help="ask a second, different model and require agreement")
    p_delegate.add_argument("--json", action="store_true")
    p_delegate.set_defaults(func=cmd_delegate)

    p_ui = sub.add_parser("ui", help="launch the control panel (about 20 percent of the screen)")
    p_ui.set_defaults(func=cmd_ui)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
