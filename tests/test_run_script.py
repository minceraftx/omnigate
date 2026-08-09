"""Unit tests for the script replay engine (mock browser, no real Edge)."""
import unittest
from unittest.mock import MagicMock

from omnigate.browser.run_script import run_script


class TestRunScript(unittest.TestCase):
    def _make_browser(self):
        b = MagicMock()
        b.wait_for.return_value = True
        b.element_exists.return_value = True
        b.click.return_value = True
        b.input.return_value = True
        b.title.return_value = "T"
        b.text.return_value = "page text"
        return b

    def test_navigate_step(self):
        b = self._make_browser()
        run_script(b, [{"cmd": "navigate", "url": "https://example.com"}])
        b.navigate.assert_called_once_with("https://example.com")

    def test_wait_click_input(self):
        b = self._make_browser()
        steps = [
            {"cmd": "wait", "selector": "#q"},
            {"cmd": "input", "selector": "#q", "text": "hi", "enter": True},
            {"cmd": "click", "selector": "#go"},
        ]
        result = run_script(b, steps)
        b.wait_for.assert_called_once_with("#q", timeout=10.0)
        b.input.assert_called_once_with("#q", "hi", enter=True)
        b.click.assert_called_once_with("#go")
        self.assertFalse(result.get("stale"))

    def test_missing_element_marks_stale(self):
        b = self._make_browser()
        b.wait_for.return_value = False  # element never appears
        result = run_script(b, [{"cmd": "wait", "selector": "#gone"}])
        self.assertTrue(result.get("stale"))

    def test_unknown_cmd_marks_failed(self):
        b = self._make_browser()
        result = run_script(b, [{"cmd": "navigate", "url": "x"}, {"cmd": "do-something"}])
        self.assertTrue(result.get("failed"))
        self.assertIn("Unknown", result.get("error", ""))

    def test_extract_returns_text(self):
        b = self._make_browser()
        result = run_script(b, [{"cmd": "extract"}])
        self.assertEqual(result.get("text"), "page text")


if __name__ == "__main__":
    unittest.main()
