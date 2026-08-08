"""CDP transport primitives: message building, websocket connection, command send."""
from __future__ import annotations

import json
import socket
import urllib.request
from typing import Any

import websocket


def build_message(msg_id: int, method: str, params: dict[str, Any] | None = None) -> str:
    """Build a CDP command as a JSON string."""
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    return json.dumps(payload)


def parse_message(raw: str) -> dict[str, Any]:
    """Parse a CDP response string into a dict."""
    return json.loads(raw)


def http_get_json(url: str, method: str = "GET") -> dict[str, Any]:
    """HTTP GET/PUT to the CDP REST endpoints (/json/version, /json/new)."""
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


class CdpSession:
    """A single CDP websocket session to one page target."""

    def __init__(self, ws_url: str, timeout: float = 15.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self._ws: websocket.WebSocket | None = None
        self._next_id = 0

    def connect(self) -> None:
        # suppress_origin: websocket-client 默认发送派生 Origin 头，会被 Chrome 的
        # Origin 校验拒绝；不带 Origin 的非浏览器客户端连接则被放行。
        self._ws = websocket.create_connection(
            self.ws_url, timeout=self.timeout, suppress_origin=True
        )

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a CDP command and wait for the matching response."""
        if self._ws is None:
            raise RuntimeError("CdpSession not connected")
        self._next_id += 1
        self._ws.send(build_message(self._next_id, method, params))
        while True:
            raw = self._ws.recv()
            msg = parse_message(raw)
            if msg.get("id") == self._next_id:
                if "error" in msg:
                    raise RuntimeError(f"CDP error: {msg['error']}")
                return msg


def free_port() -> int:
    """Pick a free localhost port for the debugging server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
