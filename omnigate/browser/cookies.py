"""Login-state reuse via CDP cookie export + inject.

Physical profile copying is unreliable on Windows (running Edge locks the
cookie DB; even when closed, SQLite buffering + Edge v127+ encryption break
the copy). The reliable path is:

  1. attach the RUNNING real Edge over CDP and export cookies via
     Network.getAllCookies
  2. launch our headless instance with a temp profile
  3. inject cookies via Network.setCookies

The running real Edge must expose a CDP debug port. Check with
`get_edge_debug_port()` / `find_debug_port()`.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from omnigate.browser.cdp import CdpSession, http_get_json

# Ports commonly used by Edge/Chrome remote debugging.
_COMMON_PORTS = (9222, 9223, 9229, 9333)


def find_debug_port() -> int | None:
    """Return the first common debug port that responds, else None."""
    for port in _COMMON_PORTS:
        try:
            http_get_json(f"http://127.0.0.1:{port}/json/version")
            return port
        except Exception:
            continue
    return None


def export_cookies_from_running_edge(port: int | None = None) -> list[dict[str, Any]]:
    """Attach a page target in a running Edge and export all cookies.

    Network.getAllCookies is a page-level method, so we attach to a real page
    target (from /json/list) rather than the browser-level websocket. If no
    page is open, opens a blank one first. Returns cookie dicts ready for
    Network.setCookies.
    """
    if port is None:
        port = find_debug_port()
    if port is None:
        raise RuntimeError(
            "No running Edge with a CDP debug port found. "
            "Launch Edge with --remote-debugging-port=9222 to enable login-state reuse."
        )

    # Prefer an existing page target; else open a blank one.
    try:
        targets = http_get_json(f"http://127.0.0.1:{port}/json/list")
        page = next(
            (t for t in targets if t.get("type") == "page" and not t.get("url", "").startswith("devtools:")),
            None,
        )
    except Exception:
        page = None
    if page is None:
        page = http_get_json(
            f"http://127.0.0.1:{port}/json/new?about:blank", method="PUT"
        )

    session = CdpSession(page["webSocketDebuggerUrl"])
    session.connect()
    try:
        resp = session.send("Network.getAllCookies")
        return resp["result"]["cookies"]
    finally:
        session.close()


def inject_cookies(session: CdpSession, cookies: list[dict[str, Any]]) -> int:
    """Inject cookies into a CDP session. Returns number injected.

    Cookies must be in the format returned by Network.getAllCookies.
    """
    if not cookies:
        return 0
    session.send("Network.setCookies", {"cookies": cookies})
    return len(cookies)


def cookies_for_url(cookies: list[dict[str, Any]], url: str) -> list[dict[str, Any]]:
    """Return the subset of cookies applicable to the URL's host.

    匹配方向：cookie domain == host，或 cookie domain 是 host 的祖先域
    （'.bilibili.com' 覆盖 www/passport/api.bilibili.com）。
    反向不匹配（子域 cookie 不发给父域）；异名域（evilbilibili.com）不匹配。
    """
    host = urlparse(url).hostname or ""
    return [
        c for c in cookies
        if host == (d := str(c.get("domain", "")).lstrip("."))
        or host.endswith("." + d)
    ]
