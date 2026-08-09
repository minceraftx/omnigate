"""High-level browser actions built on CdpSession."""
from __future__ import annotations

import base64
import time
from typing import Any

from omnigate.browser.cdp import CdpSession, http_get_json


class BrowserSession:
    """Owns an Edge process + CDP session, provides high-level actions."""

    def __init__(self, edge_path: str, port: int, user_data_dir: str, headless: bool = True):
        self.edge_path = edge_path
        self.port = port
        self.user_data_dir = user_data_dir
        self.headless = headless
        self._proc = None
        self._tab = None
        self._session: CdpSession | None = None

    def start(self) -> None:
        from omnigate.browser.edge import launch_edge
        self._proc = launch_edge(self.edge_path, self.port, self.user_data_dir, self.headless)
        try:
            # Wait for CDP endpoint
            deadline = time.time() + 30
            version = None
            while time.time() < deadline:
                try:
                    version = http_get_json(f"http://127.0.0.1:{self.port}/json/version")
                    break
                except Exception:
                    time.sleep(0.5)
            if version is None:
                raise RuntimeError("Edge did not start CDP endpoint in 30s")
            # Identity check: free_port() may have been grabbed by another
            # process between bind and Edge actually listening (TOCTOU).
            # Edge reports itself as "Edg/151.0..." in the Browser field.
            browser = (version or {}).get("Browser", "")
            if not (browser.startswith("Edg/") or browser.startswith("Edge")):
                raise RuntimeError(
                    f"Port {self.port} answered but is not Edge (Browser={browser!r})"
                )
            # Open a fresh tab
            tab = http_get_json(
                f"http://127.0.0.1:{self.port}/json/new?about:blank",
                method="PUT",
            )
            self._tab = tab
            self._session = CdpSession(tab["webSocketDebuggerUrl"])
            self._session.connect()
        except Exception:
            # Do not leak the Edge process if startup fails mid-way
            self.stop()
            raise

    def stop(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
            self._proc = None

    def navigate(self, url: str) -> None:
        self._require_session().send("Page.navigate", {"url": url})
        time.sleep(2)

    def screenshot(self, path: str) -> None:
        resp = self._require_session().send("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as f:
            f.write(base64.b64decode(resp["result"]["data"]))

    def title(self) -> str:
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": "document.title", "returnByValue": True}
        )
        return resp["result"]["result"].get("value", "")

    def text(self) -> str:
        """Extract visible text from the page body."""
        expr = "document.body ? document.body.innerText : ''"
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        return resp["result"]["result"].get("value", "")

    def scroll(self, direction: str = "down", amount: int = 800) -> None:
        sign = 1 if direction == "down" else -1
        expr = f"window.scrollBy(0, {sign * amount}); 'ok'"
        self._require_session().send("Runtime.evaluate", {"expression": expr})

    def element_exists(self, selector: str) -> bool:
        """Whether at least one element matches the CSS selector."""
        expr = f"!!document.querySelector({selector!r})"
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        return bool(resp["result"]["result"].get("value"))

    def wait_for(self, selector: str, timeout: float = 10.0) -> bool:
        """Wait until an element matching selector appears. Returns True if found."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.element_exists(selector):
                return True
            time.sleep(0.5)
        return False

    def state(self, limit: int = 30) -> list[dict]:
        """List interactive elements (button/input/a/link) with index + tag + text.

        Model reads this to write precise CSS selectors for click/input.
        """
        expr = """
        (() => {
          const els = [...document.querySelectorAll('button, input, a, select, [role=button], [onclick]')];
          const out = [];
          for (const [i, el] of els.entries()) {
            if (i >= %d) break;
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) continue; // hidden
            out.push({
              i: i,
              tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 60),
              id: el.id || '',
              cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 40) : ''
            });
          }
          return out;
        })()
        """ % limit
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        value = resp["result"]["result"].get("value")
        return value if isinstance(value, list) else []

    def click(self, selector: str) -> bool:
        """Click the first element matching selector. Returns True if clicked."""
        expr = """
        (() => {
          const el = document.querySelector(%r);
          if (!el) return false;
          el.scrollIntoView({block: 'center'});
          el.click();
          return true;
        })()
        """ % selector
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        return bool(resp["result"]["result"].get("value"))

    def input(self, selector: str, text: str, enter: bool = False) -> bool:
        """Set an input's value and dispatch input event. Returns True if set."""
        expr = """
        (() => {
          const el = document.querySelector(%r);
          if (!el) return false;
          el.scrollIntoView({block: 'center'});
          el.focus();
          el.value = %r;
          el.dispatchEvent(new Event('input', {bubbles: true}));
          el.dispatchEvent(new Event('change', {bubbles: true}));
          return true;
        })()
        """ % (selector, text)
        resp = self._require_session().send(
            "Runtime.evaluate", {"expression": expr, "returnByValue": True}
        )
        ok = bool(resp["result"]["result"].get("value"))
        if ok and enter:
            self._require_session().send(
                "Runtime.evaluate",
                {"expression": "(function(){const el=document.querySelector(%r); if(!el)return false; el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:13,which:13,bubbles:true})); return true;})()" % selector},
            )
        return ok

    def _require_session(self) -> CdpSession:
        if self._session is None:
            raise RuntimeError("BrowserSession not started")
        return self._session
