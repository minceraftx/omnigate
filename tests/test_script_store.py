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

    def test_path_traversal_load_rejected(self):
        # "../../secret" 消毒后变成 "secret"，不触及目录外文件
        with self.assertRaises(KeyError):
            self.store.load("../../secret")

    def test_path_traversal_delete_rejected(self):
        # 先存一个真实脚本，再用 ../ 指向它应被消毒为同名，不删目录外
        self.store.save("real", [{"cmd": "navigate", "url": "x"}])
        with self.assertRaises(KeyError):
            self.store.delete("../no-such")
        self.assertIn("real", self.store.list_names())

    def test_name_normalization_consistent(self):
        # save("my script") 存 myscript.json；load("my script") 也应找到
        self.store.save("my script", [{"cmd": "navigate", "url": "x"}])
        loaded = self.store.load("my script")
        self.assertEqual(loaded, [{"cmd": "navigate", "url": "x"}])
        self.assertIn("myscript", self.store.list_names())


if __name__ == "__main__":
    unittest.main()
