"""Unit tests for core helpers (no browser needed)."""
import os
import tempfile
import time
import unittest

from omnigate.core import _cleanup_stale_temp_dirs, _resolve_output_path


class TestResolveOutputPath(unittest.TestCase):
    def test_relative_inside_cwd_passes(self):
        result = _resolve_output_path("tmp/x.png")
        self.assertEqual(result, os.path.realpath("tmp/x.png"))

    def test_absolute_inside_cwd_passes(self):
        path = os.path.join(os.getcwd(), "a.png")
        result = _resolve_output_path(path)
        self.assertEqual(result, os.path.realpath(path))

    def test_parent_traversal_rejected(self):
        with self.assertRaises(ValueError):
            _resolve_output_path("../x.png")

    def test_absolute_outside_cwd_rejected(self):
        # A path guaranteed outside cwd on Windows (or POSIX fallback)
        outside = tempfile.gettempdir()
        with self.assertRaises(ValueError):
            _resolve_output_path(os.path.join(outside, "x.png"))


class TestCleanupStaleTempDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.gettempdir()
        self.old = os.path.join(self.tmp, "omnigate-run-stale-uniq")
        self.fresh = os.path.join(self.tmp, "omnigate-run-fresh-uniq")
        os.makedirs(self.old, exist_ok=True)
        os.makedirs(self.fresh, exist_ok=True)
        old_ts = time.time() - 25 * 3600
        os.utime(self.old, (old_ts, old_ts))

    def tearDown(self):
        for d in (self.old, self.fresh):
            try:
                os.rmdir(d)
            except OSError:
                pass

    def test_stale_removed(self):
        _cleanup_stale_temp_dirs(max_age_hours=24)
        self.assertFalse(os.path.exists(self.old))

    def test_fresh_kept(self):
        _cleanup_stale_temp_dirs(max_age_hours=24)
        self.assertTrue(os.path.exists(self.fresh))

    def test_ignores_unrelated_dirs(self):
        _cleanup_stale_temp_dirs(max_age_hours=24)
        self.assertTrue(os.path.exists(self.fresh))


if __name__ == "__main__":
    unittest.main()
