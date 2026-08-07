"""High-level orchestration: turn CLI commands into browser/audio operations.

open_page launches a headless Edge with login state carried over from the
running real Edge via CDP cookie export+inject (physical profile copy is
unreliable on Windows — see plan GOTCHA notes). If the headless page fails to
load (some sites reject headless), it retries once in headed mode.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from omnigate.browser.cdp import free_port
from omnigate.browser.edge import find_edge


def _page_loaded(b) -> bool:
    """A page is 'loaded enough' if it has a non-empty title OR body text."""
    try:
        title = b.title().strip()
        if title:
            return True
        text = b.text().strip()
        return bool(text)
    except Exception:
        return False


def _page_html(b) -> str:
    """Return the page's outerHTML, or None on any error.

    None (not '') lets callers distinguish "page couldn't be read" from
    "page genuinely has no captcha" — a blank read must not be treated as
    "captcha solved".
    """
    try:
        resp = b._require_session().send(
            "Runtime.evaluate",
            {"expression": "document.documentElement.outerHTML", "returnByValue": True},
        )
        return resp["result"]["result"].get("value", None)
    except Exception:
        return None


def _launch_and_navigate(edge: str, url: str, user_data_dir: str, port: int,
                         headless: bool, use_login: bool):
    """Start a BrowserSession, inject login, navigate. Returns the session.

    If start/inject/navigate fails, the launched Edge process is stopped
    before re-raising, so no orphan is left behind.
    """
    from omnigate.browser.actions import BrowserSession
    from omnigate.browser.cookies import export_cookies_from_running_edge, inject_cookies

    b = BrowserSession(edge, port, user_data_dir, headless=headless)
    try:
        b.start()
        if use_login:
            try:
                cookies = export_cookies_from_running_edge()
                inject_cookies(b._require_session(), cookies)
            except RuntimeError:
                # No debug-port Edge — proceed logged-out rather than fail.
                pass
        b.navigate(url)
        return b
    except Exception:
        b.stop()
        raise


def _solve_captcha_popup(b, edge: str, url: str, user_data_dir: str,
                         use_login: bool, features: list[str]) -> None:
    """Relaunch headed, re-inject login, navigate back, and poll until the
    captcha is gone (default 3 min, override with OMNIGATE_CAPTCHA_TIMEOUT).
    Prints protocol lines to stdout."""
    import time as _time
    from omnigate.browser.captcha import detect_captcha_features

    timeout = float(os.environ.get("OMNIGATE_CAPTCHA_TIMEOUT", "180"))

    print("[CAPTCHA] 检测到验证码，正在弹出窗口请人工解决...")
    b.stop()
    b.headless = False
    b.start()
    try:
        b.inject_login()
    except Exception:
        # No debug-port Edge or inject hiccup — pop the window logged-out
        # rather than fail the whole flow.
        pass
    b.navigate(url)
    print("[CAPTCHA] CAPTCHA_WINDOW_OPENED - 请人工解决")

    deadline = _time.time() + timeout
    while _time.time() < deadline:
        _time.sleep(3)
        html = _page_html(b)
        if html is None:
            # Page unreadable right now — keep waiting, do NOT treat as solved.
            continue
        if not detect_captcha_features(html):
            print("[CAPTCHA] CAPTCHA_RESOLVED - 继续")
            return
    print(f"[CAPTCHA] CAPTCHA_TIMEOUT - {int(timeout)}秒未解决")


def open_page(url: str, *, headless: bool = True, screenshot: str | None = None,
              get_text: bool = False, scroll_count: int = 0,
              use_login: bool = True, solve_captcha: bool = False) -> dict:
    """Open a URL in a headless Edge, carrying login cookies from the real Edge.

    Returns dict with title, text (optional), screenshot path (optional).
    Uses a fresh temp user-data dir; login state comes from CDP cookie
    export+inject. If headless page fails to load, retries once headed.
    """
    edge = find_edge()
    if edge is None:
        raise RuntimeError("Edge not found. Install Microsoft Edge.")
    temp_dir = tempfile.mkdtemp(prefix="omnigate-run-")
    user_data_dir = os.path.join(temp_dir, "user-data")
    os.makedirs(user_data_dir, exist_ok=True)
    port = free_port()
    b = None
    try:
        b = _launch_and_navigate(edge, url, user_data_dir, port, headless, use_login)

        # Retry once headed if the headless page didn't load (some sites
        # reject headless; a real window is less suspicious).
        if headless and not _page_loaded(b):
            b.stop()
            b = _launch_and_navigate(edge, url, user_data_dir, free_port(),
                                     headless=False, use_login=use_login)

        result: dict = {"url": url, "title": b.title()}

        # Captcha detection — non-blocking by default. Inform the model via
        # the stdout protocol; only pop a window when solve_captcha is set.
        from omnigate.browser.captcha import detect_captcha_features, captcha_event
        html = _page_html(b)
        features = detect_captcha_features(html) if html is not None else []
        if features:
            print(captcha_event(features, url))
            if solve_captcha:
                _solve_captcha_popup(b, edge, url, user_data_dir, use_login, features)

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
        if b is not None:
            try:
                b.stop()
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)
