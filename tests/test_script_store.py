"""Unit tests for script store (no browser needed)."""
import tempfile
import unittest

from omnigate.script_store import ScriptStore


class TestScriptStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="omni-script-")
        self.store = ScriptStore(self.tmp)

    def test_save_and_list(self):
        self.store.save("bilibili-summary", [{"cmd": "navigate", "url": "https://bilibili.com"}])
        names = self.store.list_names()
        self.assertIn("bilibili-summary", names)

    def test_load_roundtrip(self):
        steps = [{"cmd": "navigate", "url": "x"}, {"cmd": "extract", "field": "text"}]
        self.store.save("t", steps)
        loaded = self.store.load("t")
        self.assertEqual(loaded, steps)

    def test_delete(self):
        self.store.save("t", [{"cmd": "navigate", "url": "x"}])
        self.store.delete("t")
        self.assertNotIn("t", self.store.list_names())

    def test_missing_raises(self):
        with self.assertRaises(KeyError):
            self.store.load("does-not-exist")


if __name__ == "__main__":
    unittest.main()
