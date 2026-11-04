"""目录选择器：只列能看的、能选的，别把选择器变成文件浏览器。"""
import os
import unittest
from unittest import mock

from helpers import temp_home
from panweb import folders, store
from panweb.errors import PanwebError


class FolderListTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-folders-")
        self.home = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.tree = os.path.join(self.home, "tree")
        for name in ("beta", "Alpha", "gamma"):
            os.makedirs(os.path.join(self.tree, name))
        os.makedirs(os.path.join(self.tree, ".hidden"))
        with open(os.path.join(self.tree, "readme.md"), "w", encoding="utf-8") as f:
            f.write("x")
        os.symlink("/", os.path.join(self.tree, "escape"))

    def names(self, result):
        return [e["name"] for e in result["entries"]]

    def test_lists_only_real_subdirectories_sorted(self):
        out = folders.core_folders(self.tree)
        self.assertEqual(self.names(out), ["Alpha", "beta", "gamma"],
                         "隐藏目录、文件与符号链接都不该出现")
        self.assertEqual(out["path"], os.path.realpath(self.tree))
        self.assertEqual(out["parent"], os.path.realpath(self.home))
        self.assertEqual(out["label"], "tree")

    def test_home_is_offered_and_not_publishable(self):
        out = folders.core_folders("")
        home = os.path.realpath(os.path.expanduser("~"))
        self.assertEqual(out["path"], home)
        self.assertFalse(out["publishable"]["ok"], "整盘/主目录不能直接发布")
        self.assertIn("不允许", out["publishable"]["reason"])
        labels = [q["label"] for q in out["quick"]]
        self.assertIn("主目录", labels)

    def test_recently_published_folders_are_quick_picks(self):
        store.save_state([{"id": "a", "name": "周报", "kind": "pages",
                           "folder": self.tree, "url": "https://x.test"}])
        labels = {q["label"]: q["path"] for q in folders.quick_picks()}
        self.assertEqual(labels.get("周报"), self.tree)

    def test_missing_path_and_nul_are_refused(self):
        with self.assertRaises(PanwebError) as gone:
            folders.core_folders(os.path.join(self.tree, "nope"))
        self.assertEqual(gone.exception.err_type, "not_found")
        with self.assertRaises(PanwebError) as nul:
            folders.core_folders("/tmp\x00/etc")
        self.assertEqual(nul.exception.err_type, "invalid_argument")

    def test_long_listings_are_capped_not_streamed(self):
        for i in range(6):
            os.makedirs(os.path.join(self.tree, "d%d" % i))
        with mock.patch.object(folders, "MAX_ENTRIES", 3):
            out = folders.core_folders(self.tree)
        self.assertEqual(len(out["entries"]), 3)
        self.assertEqual(out["truncated"], 6, "9 个可见目录留下 3 个，要告诉界面还剩 6 个")

    def test_unreadable_directory_reports_an_error_not_a_crash(self):
        with mock.patch("panweb.folders.os.listdir", side_effect=OSError(13, "denied")):
            with self.assertRaises(PanwebError) as bad:
                folders.core_folders(self.tree)
        self.assertEqual(bad.exception.err_type, "unreadable")


if __name__ == "__main__":
    unittest.main()
