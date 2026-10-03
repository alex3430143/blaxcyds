"""Chrome DevTools Protocol browser driver.

This talks to a *real* Chrome/Chromium over the DevTools Protocol:

* launch the browser with `--remote-debugging-port=0` and a private profile,
* read the chosen port from `<profile>/DevToolsActivePort`,
* enumerate targets over HTTP (`/json/list`) and connect to the page target's
  WebSocket,
* send real `Page`/`Runtime` commands and read their results.

Everything is honest: if no browser or `websocket-client` is present the driver
raises `CdpError` and `browser_capabilities()` says so. No result is fabricated.

The design is deliberately synchronous and single-page: BLAXCY runs one browser
session at a time, and the Body serializes actions.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from ..models import Action, ActionKind

BROWSER_CANDIDATES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "chrome", "brave-browser",
)


class CdpError(RuntimeError):
    """Anything that prevents a real DevTools command from completing."""


def find_browser() -> str | None:
    """Return the path to a usable Chromium-family browser, or None."""
    override = os.environ.get("BLAXCY_BROWSER")
    if override and shutil.which(override):
        return shutil.which(override)
    for name in BROWSER_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _have_websocket() -> bool:
    try:
        import websocket  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def browser_capabilities() -> dict[str, Any]:
    """Detect real browser-control capability without launching anything."""
    binary = find_browser()
    has_ws = _have_websocket()
    return {
        "available": bool(binary and has_ws),
        "binary": binary,
        "websocket_client": has_ws,
        "candidates": {name: bool(shutil.which(name)) for name in BROWSER_CANDIDATES},
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class ChromeCdpDriver:
    """A real single-page Chrome/Chromium session over the DevTools Protocol."""

    def __init__(self, *, binary: str | None = None, headless: bool = True,
                 port: int = 0, user_data_dir: str | None = None,
                 timeout: float = 20.0, start_url: str = "about:blank",
                 extra_args: list[str] | None = None) -> None:
        self.binary = binary
        self.headless = headless
        self.port = port
        self.user_data_dir = user_data_dir
        self.timeout = timeout
        self.start_url = start_url
        self.extra_args = list(extra_args or [])
        self._proc: subprocess.Popen | None = None
        self._ws: Any = None
        self._id = 0
        self._port_actual: int | None = None
        self._own_profile = False

    # lifecycle -------------------------------------------------------------
    def start(self) -> "ChromeCdpDriver":
        if self._proc is not None:
            return self
        self.binary = self.binary or find_browser()
        if not self.binary:
            raise CdpError("no Chrome/Chromium binary found (set BLAXCY_BROWSER)")
        if not _have_websocket():
            raise CdpError("websocket-client is required for CDP control")
        if self.user_data_dir is None:
            self.user_data_dir = tempfile.mkdtemp(prefix="blaxcy-cdp-")
            self._own_profile = True
        else:
            Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        args = [
            self.binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-dev-shm-usage",
            *self.extra_args,
        ]
        if self.headless:
            args.append("--headless=new")
        args.append(self.start_url)

        self._proc = subprocess.Popen(  # noqa: S603 - explicit browser binary
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            self._port_actual = self._wait_for_port()
            self._connect_page()
            self._safe_send("Runtime.enable")
            self._safe_send("Page.enable")
        except Exception:
            self.stop()
            raise
        return self

    def _wait_for_port(self) -> int:
        port_file = Path(self.user_data_dir or "") / "DevToolsActivePort"
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise CdpError(f"browser exited early (code {self._proc.returncode})")
            if port_file.exists():
                try:
                    lines = port_file.read_text(encoding="utf-8").splitlines()
                except OSError:
                    lines = []
                if lines:
                    return int(lines[0])
            time.sleep(0.1)
        raise CdpError("timed out waiting for DevToolsActivePort")

    def _page_ws_url(self) -> str:
        base = f"http://127.0.0.1:{self._port_actual}"
        try:
            with urllib.request.urlopen(f"{base}/json/list", timeout=self.timeout) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
        except OSError as exc:
            raise CdpError(f"cannot list CDP targets: {exc}") from exc
        for target in targets:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return str(target["webSocketDebuggerUrl"])
        raise CdpError("no page target available over CDP")

    def _connect_page(self) -> None:
        import websocket

        try:
            self._ws = websocket.create_connection(self._page_ws_url(), timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - surface as CdpError
            raise CdpError(f"CDP websocket connect failed: {exc}") from exc

    def stop(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        if self._own_profile and self.user_data_dir:
            shutil.rmtree(self.user_data_dir, ignore_errors=True)
        self._port_actual = None

    def __enter__(self) -> "ChromeCdpDriver":
        return self.start()

    def __exit__(self, *exc: object) -> bool:
        self.stop()
        return False

    # protocol --------------------------------------------------------------
    def _send(self, method: str, params: dict[str, Any] | None = None,
              timeout: float | None = None) -> dict[str, Any]:
        if self._ws is None:
            raise CdpError("driver is not started")
        self._id += 1
        mid = self._id
        self._ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError(f"{method}: CDP response timeout")
            try:
                self._ws.settimeout(remaining)
                raw = self._ws.recv()
            except Exception as exc:  # noqa: BLE001
                raise CdpError(f"{method}: {type(exc).__name__}: {exc}") from exc
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if msg.get("id") != mid:
                continue  # an event, not our command response
            if "error" in msg:
                raise CdpError(f"{method} failed: {msg['error']}")
            result = msg.get("result", {})
            return result if isinstance(result, dict) else {"value": result}

    def _safe_send(self, method: str, params: dict[str, Any] | None = None) -> None:
        try:
            self._send(method, params)
        except CdpError:
            pass

    # evaluation ------------------------------------------------------------
    def _evaluate(self, expression: str, *, await_promise: bool = False,
                  return_by_value: bool = True) -> Any:
        result = self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": return_by_value,
            "awaitPromise": await_promise,
        })
        if "exceptionDetails" in result:
            detail = result["exceptionDetails"]
            raise CdpError(f"page JS error: {detail.get('exception', {}).get('description') or detail}")
        inner = result.get("result", {})
        return inner.get("value")

    def eval(self, expression: str, *, await_promise: bool = False) -> Any:
        """Run JS in the page and return its value (raises on page errors)."""
        return self._evaluate(expression, await_promise=await_promise)

    # high-level actions ----------------------------------------------------
    def navigate(self, url: str, *, wait: bool = True, timeout: float | None = None) -> dict[str, Any]:
        result = self._send("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise CdpError(f"navigation error: {result['errorText']}")
        if wait:
            self.wait_ready(timeout=timeout)
        return {"url": url, "frame_id": result.get("frameId"),
                "loader_id": result.get("loaderId")}

    def wait_ready(self, *, timeout: float | None = None) -> bool:
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while time.monotonic() < deadline:
            try:
                state = self._evaluate("document.readyState")
            except CdpError:
                state = None
            if state in ("interactive", "complete"):
                return True
            time.sleep(0.05)
        return False

    def title(self) -> str:
        return str(self.eval("document.title") or "")

    def current_url(self) -> str:
        return str(self.eval("location.href") or "")

    def query(self, selector: str) -> dict[str, Any]:
        sel = json.dumps(selector)
        js = (
            "(()=>{const e=document.querySelector(" + sel + ");"
            "if(!e) return {exists:false};"
            "return {exists:true,tag:e.tagName,"
            "text:(e.innerText||e.textContent||''),"
            "value:(e.value!==undefined?e.value:null),"
            "id:e.id||null,name:(e.getAttribute&&e.getAttribute('name'))||null,"
            "href:(e.href!==undefined?e.href:null),"
            "visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)};})()"
        )
        value = self._evaluate(js)
        return value if isinstance(value, dict) else {"exists": False}

    def click(self, selector: str) -> bool:
        sel = json.dumps(selector)
        js = (
            "(()=>{const e=document.querySelector(" + sel + ");"
            "if(!e) return false; e.click(); return true;})()"
        )
        return bool(self._evaluate(js))

    def type_text(self, selector: str, text: str) -> Any:
        sel = json.dumps(selector)
        val = json.dumps(text)
        js = (
            "(()=>{const e=document.querySelector(" + sel + ");"
            "if(!e) return null; const v=" + val + ";"
            "e.focus();"
            "if('value' in e){e.value=v;} else {e.textContent=v;}"
            "e.dispatchEvent(new Event('input',{bubbles:true}));"
            "e.dispatchEvent(new Event('change',{bubbles:true}));"
            "return ('value' in e)?e.value:v;})()"
        )
        return self._evaluate(js)

    def screenshot(self) -> bytes:
        result = self._send("Page.captureScreenshot", {"format": "png"})
        data = result.get("data")
        if not data:
            raise CdpError("screenshot returned no data")
        return base64.b64decode(data)

    def wait_for(self, expression: str, *, timeout: float | None = None,
                 poll: float = 0.1) -> bool:
        """Block until `expression` is truthy in the page (no arbitrary sleeps)."""
        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while time.monotonic() < deadline:
            try:
                if self.eval(expression):
                    return True
            except CdpError:
                pass
            time.sleep(poll)
        return False


# Browser action kinds routed by this backend.
BROWSER_KINDS = {
    ActionKind.BROWSER_NAVIGATE,
    ActionKind.BROWSER_EVAL,
    ActionKind.BROWSER_QUERY,
    ActionKind.BROWSER_CLICK,
    ActionKind.BROWSER_TYPE,
    ActionKind.BROWSER_SCREENSHOT,
    ActionKind.BROWSER_TITLE,
    ActionKind.BROWSER_URL,
}


class BrowserBackend:
    """Body backend that executes browser Actions against a real Chrome session.

    The browser is started lazily on the first browser action and torn down by
    `release_all()` (called on crash/timeout/release), so a failure never leaves
    an orphaned browser process.
    """

    name = "browser"

    def __init__(self, driver_factory: Any = None, *, headless: bool = True) -> None:
        self._driver_factory = driver_factory or (lambda: ChromeCdpDriver(headless=headless))
        self._driver: ChromeCdpDriver | None = None

    def driver(self) -> ChromeCdpDriver:
        if self._driver is None:
            self._driver = self._driver_factory()
            self._driver.start()
        return self._driver

    def perform(self, action: Action) -> dict[str, Any]:
        driver = self.driver()
        kind = action.kind
        params = action.params
        if kind is ActionKind.BROWSER_NAVIGATE:
            return driver.navigate(str(params["url"]))
        if kind is ActionKind.BROWSER_EVAL:
            return {"value": driver.eval(str(params["expression"]))}
        if kind is ActionKind.BROWSER_QUERY:
            return driver.query(str(params["selector"]))
        if kind is ActionKind.BROWSER_CLICK:
            clicked = driver.click(str(params["selector"]))
            if not clicked:
                raise RuntimeError(f"element not found: {params['selector']}")
            return {"clicked": True, "selector": params["selector"]}
        if kind is ActionKind.BROWSER_TYPE:
            value = driver.type_text(str(params["selector"]), str(params["text"]))
            if value is None:
                raise RuntimeError(f"element not found: {params['selector']}")
            return {"selector": params["selector"], "value": value}
        if kind is ActionKind.BROWSER_TITLE:
            return {"title": driver.title()}
        if kind is ActionKind.BROWSER_URL:
            return {"url": driver.current_url()}
        if kind is ActionKind.BROWSER_SCREENSHOT:
            data = driver.screenshot()
            path = params.get("path")
            if path:
                Path(str(path)).write_bytes(data)
            return {"bytes": len(data), "path": path}
        raise NotImplementedError(f"browser backend cannot perform {kind.value}")

    def release_all(self) -> None:
        if self._driver is not None:
            self._driver.stop()
            self._driver = None
