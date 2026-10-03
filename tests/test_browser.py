"""Tests for the browser tool (requirement I3).

Unit tests use a fake driver so they never launch a browser. One integration test
opens a real headless Chrome over the DevTools Protocol (it skips honestly when
no browser or `websocket-client` is available).
"""

from __future__ import annotations

import json

import pytest

from blaxcy.body import Body, DryRunBackend
from blaxcy.body.backends import AutoBackend
from blaxcy.browser import BrowserBackend, ChromeCdpDriver, browser_capabilities
from blaxcy.models import Action, ActionKind, RiskClass
from blaxcy.policy import Policy, classify
from blaxcy.tools.browser import BrowserTool

_CAPS = browser_capabilities()
_real_browser = pytest.mark.skipif(not _CAPS["available"],
                                   reason="no Chrome/Chromium or websocket-client")


# --------------------------------------------------------------------------- #
# capability detection
# --------------------------------------------------------------------------- #
def test_browser_capabilities_shape():
    assert set(_CAPS) == {"available", "binary", "websocket_client", "candidates"}
    assert isinstance(_CAPS["available"], bool)


# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #
def test_browser_risk_classification():
    assert classify(Action(kind=ActionKind.BROWSER_QUERY, params={"selector": "#x"})) is RiskClass.LOW
    assert classify(Action(kind=ActionKind.BROWSER_TITLE, params={})) is RiskClass.LOW
    assert classify(Action(kind=ActionKind.BROWSER_URL, params={})) is RiskClass.LOW
    assert classify(Action(kind=ActionKind.BROWSER_NAVIGATE,
                           params={"url": "https://example.com"})) is RiskClass.MEDIUM
    assert classify(Action(kind=ActionKind.BROWSER_EVAL,
                           params={"expression": "1"})) is RiskClass.HIGH


def test_eval_requires_confirmation():
    policy = Policy(max_risk=RiskClass.MEDIUM, real_input_enabled=False)
    decision = policy.check(Action(kind=ActionKind.BROWSER_EVAL, params={"expression": "1"}))
    assert not decision.allowed
    assert decision.requires_confirmation


def test_login_url_is_an_auth_boundary():
    policy = Policy(max_risk=RiskClass.HIGH, real_input_enabled=False)
    decision = policy.check(Action(kind=ActionKind.BROWSER_NAVIGATE,
                                   params={"url": "https://example.com/login"}))
    assert not decision.allowed
    assert decision.escalate_to_user


def test_browser_actions_are_not_mouse_dry_run():
    """Browser control is a tool, not mouse/keyboard input, so it is not marked
    simulated just because real input is disabled."""
    policy = Policy(max_risk=RiskClass.MEDIUM, real_input_enabled=False)
    decision = policy.check(Action(kind=ActionKind.BROWSER_NAVIGATE,
                                   params={"url": "https://example.com"}))
    assert decision.allowed and decision.simulated is False


# --------------------------------------------------------------------------- #
# fake-driver backend routing
# --------------------------------------------------------------------------- #
class FakeDriver:
    def __init__(self) -> None:
        self.calls: list = []

    def start(self):
        self.calls.append("start")
        return self

    def stop(self):
        self.calls.append("stop")

    def navigate(self, url):
        self.calls.append(("navigate", url))
        return {"url": url}

    def eval(self, expression, **kw):
        self.calls.append(("eval", expression))
        return f"EVAL:{expression}"

    def query(self, selector):
        self.calls.append(("query", selector))
        return {"exists": selector != "#404", "text": "hi"}

    def click(self, selector):
        self.calls.append(("click", selector))
        return selector != "#404"

    def type_text(self, selector, text):
        self.calls.append(("type", selector, text))
        return None if selector == "#404" else text

    def screenshot(self):
        self.calls.append("shot")
        return b"\x89PNG"

    def title(self):
        self.calls.append("title")
        return "T"

    def current_url(self):
        self.calls.append("url")
        return "http://x/"


@pytest.fixture
def fake_backend():
    driver = FakeDriver()
    return BrowserBackend(driver_factory=lambda: driver), driver


def test_backend_dispatch_all_kinds(fake_backend):
    backend, driver = fake_backend
    assert backend.perform(Action(kind=ActionKind.BROWSER_NAVIGATE,
                                  params={"url": "https://x"}))["url"] == "https://x"
    assert backend.perform(Action(kind=ActionKind.BROWSER_EVAL,
                                  params={"expression": "2"}) )["value"] == "EVAL:2"
    assert backend.perform(Action(kind=ActionKind.BROWSER_QUERY,
                                  params={"selector": "#x"}))["exists"] is True
    assert backend.perform(Action(kind=ActionKind.BROWSER_CLICK,
                                  params={"selector": "#x"}))["clicked"] is True
    assert backend.perform(Action(kind=ActionKind.BROWSER_TYPE,
                                  params={"selector": "#i", "text": "v"}))["value"] == "v"
    assert backend.perform(Action(kind=ActionKind.BROWSER_TITLE, params={}))["title"] == "T"
    assert backend.perform(Action(kind=ActionKind.BROWSER_URL, params={}))["url"] == "http://x/"
    assert backend.perform(Action(kind=ActionKind.BROWSER_SCREENSHOT, params={}))["bytes"] == 4
    assert "start" in driver.calls


def test_backend_raises_for_missing_element(fake_backend):
    backend, _ = fake_backend
    with pytest.raises(RuntimeError):
        backend.perform(Action(kind=ActionKind.BROWSER_CLICK, params={"selector": "#404"}))
    with pytest.raises(RuntimeError):
        backend.perform(Action(kind=ActionKind.BROWSER_TYPE,
                               params={"selector": "#404", "text": "v"}))


def test_backend_release_all_stops_driver(fake_backend):
    backend, driver = fake_backend
    backend.perform(Action(kind=ActionKind.BROWSER_TITLE, params={}))
    backend.release_all()
    assert "stop" in driver.calls
    assert backend._driver is None


def test_auto_backend_routes_browser_to_injected_backend():
    class FakeBrowser:
        name = "fake-browser"

        def perform(self, action):
            return {"browser_kind": action.kind.value}

        def release_all(self):
            pass

    backend = AutoBackend(display="", browser=FakeBrowser())
    out = backend.perform(Action(kind=ActionKind.BROWSER_QUERY, params={"selector": "#x"}))
    assert out["browser_kind"] == "browser_query"


# --------------------------------------------------------------------------- #
# tool (dry-run body; no real browser)
# --------------------------------------------------------------------------- #
@pytest.fixture
def tool(policy):
    return BrowserTool(Body(DryRunBackend(), policy), policy)


def test_tool_navigate_and_query(tool):
    nav = tool.navigate("https://example.com")
    assert nav.ok and nav.output["simulated"] is True
    assert tool.query("#x").ok
    assert tool.title().ok
    assert tool.current_url().ok


def test_tool_eval_is_refused_then_allowed_with_opt_in(tool):
    blocked = tool.evaluate("1+1")
    assert not blocked.ok
    assert blocked.output["requires_confirmation"] is True
    assert blocked.output["action_id"]

    allowed = tool.evaluate("1+1", allow_high_risk=True)
    assert allowed.ok


def test_cli_browser_status_reports_capability(capsys):
    from blaxcy.cli import main

    code = main(["browser", "status"])
    out = json.loads(capsys.readouterr().out)
    assert set(out) >= {"available", "binary", "websocket_client"}
    assert code in (0, 1)


# --------------------------------------------------------------------------- #
# real browser integration
# --------------------------------------------------------------------------- #
@_real_browser
def test_real_cdp_session_roundtrip():
    html = ("<title>BLAXCY</title><h1 id=x>hello</h1>"
            "<input id=i><button id=b>go</button>")
    driver = ChromeCdpDriver(headless=True, timeout=30.0)
    try:
        driver.start()
        driver.navigate("data:text/html," + html)
        assert driver.title() == "BLAXCY"
        assert driver.current_url().startswith("data:")

        node = driver.query("#x")
        assert node["exists"] and node["text"] == "hello" and node["tag"] == "H1"
        assert driver.query("#nope")["exists"] is False

        assert driver.type_text("#i", "world") == "world"
        assert driver.query("#i")["value"] == "world"

        assert driver.click("#b") is True
        assert driver.click("#nope") is False

        png = driver.screenshot()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert driver.eval("1+1") == 2
        assert driver.wait_for("document.readyState==='complete'", timeout=5) is True
    finally:
        driver.stop()
