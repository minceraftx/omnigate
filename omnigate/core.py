"""High-level orchestration: turn CLI commands into browser/audio operations.

open_page launches a headless Edge with login state carried over from the
running real Edge via CDP cookie export+inject (physical profile copy is
unreliable on Windows — see plan GOTCHA notes).
"""
from __future__ import annotations

import os
import shutil
import tempfile

from omnigate.browser.cdp import free_port
from omnigate.browser.edge import find_edge, prepare_profile


def open_page(url: str, *, headless: bool = True, screenshot: str | None = None,
              get_text: bool = False, scroll_count: int = 0,
              use_login: bool = True) -> dict:
    """Open a URL in a headless Edge, carrying login cookies from the real Edge.

    Returns dict with title, text (optional), screenshot path (optional).
    Uses a fresh temp user-data dir; login state comes from CDP cookie
    export+inject (physical profile copy is unreliable on Windows). If
    use_login but no debug-port Edge is reachable, opens logged-out.
    """
    edge = find_edge()
    if edge is None:
        raise RuntimeError("Edge not found. Install Microsoft Edge.")
    temp_dir = tempfile.mkdtemp(prefix="omnigate-run-")
    user_data_dir = os.path.join(temp_dir, "user-data")
    os.makedirs(user_data_dir, exist_ok=True)
    port = free_port()
    try:
        from omnigate.browser.actions import BrowserSession
        from omnigate.browser.cookies import export_cookies_from_running_edge, inject_cookies

        b = BrowserSession(edge, port, user_data_dir, headless=headless)
        b.start()
        if use_login:
            try:
                cookies = export_cookies_from_running_edge()
                inject_cookies(b._require_session(), cookies)
            except RuntimeError:
                # No debug-port Edge — proceed logged-out rather than fail.
                pass
        b.navigate(url)
        result: dict = {"url": url, "title": b.title()}
        if scroll_count > 0:
            for _ in range(scroll_count):
                b.scroll("down")
        if get_text:
            result["text"] = b.text()
        if screenshot:
            os.makedirs(os.path.dirname(screenshot) or ".", exist_ok=True)
            b.screenshot(screenshot)
            result["screenshot"] = screenshot
        b.stop()
        return result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
