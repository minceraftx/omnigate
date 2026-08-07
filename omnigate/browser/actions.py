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
        # Open a fresh tab
        tab = http_get_json(
            f"http://127.0.0.1:{self.port}/json/new?about:blank",
            method="PUT",
        )
        self._tab = tab
        self._session = CdpSession(tab["webSocketDebuggerUrl"])
        self._session.connect()

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

    def _require_session(self) -> CdpSession:
        if self._session is None:
            raise RuntimeError("BrowserSession not started")
        return self._session
