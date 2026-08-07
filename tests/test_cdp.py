"""Unit tests for CDP message building (no real browser needed)."""
import json
import unittest

from omnigate.browser.cdp import build_message, parse_message


class TestBuildMessage(unittest.TestCase):
    def test_increments_ids(self):
        m1 = json.loads(build_message(1, "Page.navigate", {"url": "x"}))
        self.assertEqual(m1["id"], 1)
        self.assertEqual(m1["method"], "Page.navigate")
        self.assertEqual(m1["params"], {"url": "x"})

    def test_parse_ok(self):
        msg = parse_message('{"id":5,"result":{}}')
        self.assertEqual(msg["id"], 5)
        self.assertNotIn("error", msg)

    def test_parse_error(self):
        raw = '{"id":6,"error":{"code":-32000,"message":"boom"}}'
        msg = parse_message(raw)
        self.assertEqual(msg["error"]["code"], -32000)


if __name__ == "__main__":
    unittest.main()
