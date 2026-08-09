"""High-level orchestration: turn CLI commands into browser/audio operations.

open_page launches a headless Edge with login state carried over from the
running real Edge via CDP cookie export+inject (physical profile copy is
unreliable on Windows — see plan GOTCHA notes). If the headless page fails to
load (some sites reject headless), it retries once in headed mode.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from omnigate.browser.cdp import free_port
from omnigate.browser.edge import find_edge


def _cleanup_stale_temp_dirs(max_age_hours: float = 24) -> None:
    """Best-effort removal of stale omnigate temp profiles.

    24h window avoids deleting concurrently-running instances. Individual
    failures are skipped (logged to stderr), never fatal. Does not follow
    symlinks.
    """
    tmp = tempfile.gettempdir()
    prefixes = ("omnigate-run-", "omnigate-profile-")
    cutoff = time.time() - max_age_hours * 3600
    try:
        entries = os.listdir(tmp)
    except OSError:
        return
    for name in entries:
        if not name.startswith(prefixes):
            continue
        full = os.path.join(tmp, name)
        if os.path.islink(full):
            continue
        try:
            if os.path.getmtime(full) < cutoff:
                shutil.rmtree(full)
        except OSError:
            continue


def _resolve_output_path(path: str) -> str:
    """Resolve an output path, refusing anything outside the current working directory.

    realpath 同时消除 .. 与符号链接；不同盘符自然不满足前缀条件。
    """
    base = os.path.realpath(os.getcwd())
    target = os.path.realpath(path)
    if target != base and not target.startswith(base + os.sep):
        raise ValueError(f"Output path must be inside the working directory: {path}")
    return target


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


def _navigate_with_login(b, url: str, full_login: bool) -> None:
    """Inject domain-scoped cookies, navigate, top-up on cross-domain landing.

    full_login=True：全量注入（现状行为），无需补注。
    默认：先注入 url 目标域子集再导航；落地 host 带来新增可注入 cookie 时补注并
    reload 一次。无调试端口 Edge 时抛 RuntimeError，由调用方降级为未登录。
    """
    import time as _time
    from omnigate.browser.cookies import (
        cookies_for_url, export_cookies_from_running_edge, inject_cookies,
    )

    cookies = export_cookies_from_running_edge()

    def _inject(target_url: str) -> int:
        subset = cookies if full_login else cookies_for_url(cookies, target_url)
        return inject_cookies(b._require_session(), subset)

    _inject(url)
    b.navigate(url)
    if full_login:
        return
    try:
        resp = b._require_session().send(
            "Runtime.evaluate", {"expression": "location.href", "returnByValue": True}
        )
        landed = resp["result"]["result"].get("value") or ""
    except Exception:
        return  # 读不到落点就不补，保持原行为
    # 只在落地 host 带来「新增可注入 cookie」时才补注 + reload。
    # apex↔www 跳转（bilibili.com → www.bilibili.com）两个子集相同，extra 为空，
    # 跳过补注避免白 reload（主用例每次都多一次页面加载和 2 秒等待）。
    extra = [c for c in cookies_for_url(cookies, landed)
             if c not in cookies_for_url(cookies, url)]
    if extra:
        inject_cookies(b._require_session(), extra)
        b._require_session().send("Page.reload", {})
        _time.sleep(2)


def _launch_and_navigate(edge: str, url: str, user_data_dir: str, port: int,
                         headless: bool, use_login: bool, full_login: bool = False):
    """Start a BrowserSession, inject login, navigate. Returns the session.

    If start/inject/navigate fails, the launched Edge process is stopped
    before re-raising, so no orphan is left behind. A TOCTOU race on the port
    (another process grabbed it after free_port()) retries once on a fresh port.
    """
    from omnigate.browser.actions import BrowserSession

    def _one_try(port_: int):
        b = BrowserSession(edge, port_, user_data_dir, headless=headless)
        try:
            b.start()
            if use_login:
                try:
                    _navigate_with_login(b, url, full_login)
                except RuntimeError:
                    # No debug-port Edge — proceed logged-out rather than fail.
                    b.navigate(url)
            else:
                b.navigate(url)
            return b
        except Exception:
            b.stop()
            raise

    try:
        return _one_try(port)
    except RuntimeError as exc:
        if "is not Edge" in str(exc):
            # Port was grabbed by a non-Edge service; retry once on a new port.
            return _one_try(free_port())
        raise


def _solve_captcha_popup(b, edge: str, url: str, user_data_dir: str,
                         use_login: bool, features: list[str],
                         full_login: bool = False) -> None:
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
    if use_login:
        try:
            _navigate_with_login(b, url, full_login)
        except Exception:
            # No debug-port Edge or inject hiccup — pop the window logged-out
            # rather than fail the whole flow.
            b.navigate(url)
    else:
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


def run_script_page(name_or_steps, *, headless: bool = True, use_login: bool = True):
    """Load a script, launch Edge, replay it. Returns replay result dict.

    The first step must be navigate — it is done by _launch_and_navigate
    (with login injection); remaining steps run through the replay engine.
    """
    from omnigate.browser.run_script import run_script
    from omnigate.script_store import ScriptStore

    if isinstance(name_or_steps, str):
        steps = ScriptStore().load(name_or_steps)
    else:
        steps = name_or_steps
    if not steps or steps[0].get("cmd") != "navigate":
        raise ValueError("Script must start with a navigate step")

    edge = find_edge()
    if edge is None:
        raise RuntimeError("Edge not found. Install Microsoft Edge.")
    _cleanup_stale_temp_dirs()
    temp_dir = tempfile.mkdtemp(prefix="omnigate-run-")
    user_data_dir = os.path.join(temp_dir, "user-data")
    os.makedirs(user_data_dir, exist_ok=True)
    b = None
    try:
        b = _launch_and_navigate(edge, steps[0]["url"], user_data_dir, free_port(),
                                 headless, use_login)
        result = run_script(b, steps[1:])
        if result.get("text") is None:
            result["text"] = b.text()
        b.stop()
        return result
    finally:
        if b is not None:
            try:
                b.stop()
            except Exception:
                pass
        try:
            shutil.rmtree(temp_dir)
        except OSError as exc:
            print(f"[omnigate] warning: temp profile cleanup failed: {temp_dir} ({exc})",
                  file=sys.stderr)


def open_page(url: str, *, headless: bool = True, screenshot: str | None = None,
              get_text: bool = False, scroll_count: int = 0,
              use_login: bool = True, solve_captcha: bool = False,
              full_login: bool = False, get_state: bool = False) -> dict:
    """Open a URL in a headless Edge, carrying login cookies from the real Edge.

    Returns dict with title, text (optional), screenshot path (optional).
    Uses a fresh temp user-data dir; login state comes from CDP cookie
    export+inject. If headless page fails to load, retries once headed.
    full_login=True injects all cookies (for cross-domain SSO sites).
    """
    edge = find_edge()
    if edge is None:
        raise RuntimeError("Edge not found. Install Microsoft Edge.")
    _cleanup_stale_temp_dirs()
    temp_dir = tempfile.mkdtemp(prefix="omnigate-run-")
    user_data_dir = os.path.join(temp_dir, "user-data")
    os.makedirs(user_data_dir, exist_ok=True)
    port = free_port()
    b = None
    try:
        b = _launch_and_navigate(edge, url, user_data_dir, port, headless,
                                 use_login, full_login)

        # Retry once headed if the headless page didn't load (some sites
        # reject headless; a real window is less suspicious).
        if headless and not _page_loaded(b):
            b.stop()
            b = _launch_and_navigate(edge, url, user_data_dir, free_port(),
                                     headless=False, use_login=use_login,
                                     full_login=full_login)

        result: dict = {"url": url, "title": b.title()}

        if get_state:
            result["state"] = b.state()

        # Captcha detection — non-blocking by default. Inform the model via
        # the stdout protocol; only pop a window when solve_captcha is set.
        from omnigate.browser.captcha import detect_captcha_features, captcha_event
        html = _page_html(b)
        features = detect_captcha_features(html) if html is not None else []
        if features:
            print(captcha_event(features, url))
            if solve_captcha:
                _solve_captcha_popup(b, edge, url, user_data_dir, use_login,
                                     features, full_login)

        if scroll_count > 0:
            for _ in range(scroll_count):
                b.scroll("down")
        if get_text:
            result["text"] = b.text()
        if screenshot:
            shot = _resolve_output_path(screenshot)
            os.makedirs(os.path.dirname(shot) or ".", exist_ok=True)
            b.screenshot(shot)
            result["screenshot"] = shot
        b.stop()
        return result
    finally:
        if b is not None:
            try:
                b.stop()
            except Exception:
                pass
        try:
            shutil.rmtree(temp_dir)
        except OSError as exc:
            print(f"[omnigate] warning: temp profile cleanup failed: {temp_dir} ({exc})",
                  file=sys.stderr)
