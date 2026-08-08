"""Unit tests for Edge launcher (arg building + profile copy path, no real launch)."""
import os
import unittest
from unittest.mock import patch

from omnigate.browser.edge import build_launch_args, find_edge, find_edge_profile_dir


class TestFindEdge(unittest.TestCase):
    @patch("os.path.exists", return_value=False)
    def test_no_edge_returns_none(self, _):
        self.assertIsNone(find_edge())

    @patch("os.path.exists")
    def test_finds_x86_edge(self, mock_exists):
        mock_exists.side_effect = lambda p: p == r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        self.assertEqual(
            find_edge(),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        )


class TestBuildLaunchArgs(unittest.TestCase):
    def test_includes_required_flags(self):
        args = build_launch_args(port=9222, user_data_dir="C:/tmp/prof")
        joined = " ".join(args)
        self.assertIn("--remote-debugging-port=9222", joined)
        self.assertNotIn("--remote-allow-origins", joined)
        self.assertIn("--user-data-dir=C:/tmp/prof", joined)

    def test_headless_flag(self):
        args = build_launch_args(port=9222, user_data_dir="x", headless=True)
        self.assertIn("--headless=new", args)


class TestProfileDir(unittest.TestCase):
    def test_edge_profile_path(self):
        d = find_edge_profile_dir()
        # Must return a path under LocalAppData Edge User Data
        self.assertTrue("Edge" in d or "edge" in d)


if __name__ == "__main__":
    unittest.main()
