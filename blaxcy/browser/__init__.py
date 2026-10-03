"""Real browser control for BLAXCY.

`blaxcy.browser.cdp` drives an actual Chrome/Chromium over the DevTools Protocol
(WebSocket). It is a *tool*, not BLAXCY's identity: the desktop remains the
first-class computer, and the browser is one more resource the agent can use.
"""

from .cdp import (
    BROWSER_CANDIDATES,
    BrowserBackend,
    CdpError,
    ChromeCdpDriver,
    browser_capabilities,
    find_browser,
)

__all__ = [
    "ChromeCdpDriver", "BrowserBackend", "CdpError",
    "find_browser", "browser_capabilities", "BROWSER_CANDIDATES",
]
