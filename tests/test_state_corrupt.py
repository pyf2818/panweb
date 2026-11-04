"""状态文件损坏不能当空态：留证、告警，并让 CLI 看得见。"""
import glob
import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

import helpers  # noqa: F401
from helpers import temp_home
from panweb import cli_commands, runtime, store


class CorruptStateTests(unittest.TestCase):
    def test_corrupt_state_is_quarantined_and_reported(self):
        with temp_home("panweb-corrupt-"):
            with open(runtime.STATE_FILE, "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual(store.load_state(), [])
            backups = glob.glob(runtime.STATE_FILE + ".corrupt-*")
            self.assertEqual(len(backups), 1, "损坏文件要改名留证")
            issue = store.state_issue()
            self.assertTrue(issue)
            self.assertIn("状态文件", issue["message"])
            self.assertEqual(store.load_state(), [])
            self.assertEqual(len(glob.glob(runtime.STATE_FILE + ".corrupt-*")), 1,
                             "第二次读取不应重复制造备份")

    def test_missing_state_is_normal_empty(self):
        with temp_home("panweb-corrupt-"):
            self.assertEqual(store.load_state(), [])
            self.assertIsNone(store.state_issue())

    def test_cli_list_prints_recovery_hint(self):
        with temp_home("panweb-corrupt-"):
            with open(runtime.STATE_FILE, "w", encoding="utf-8") as f:
                f.write("broken")
            out = io.StringIO()
            with redirect_stdout(out):
                cli_commands.cmd_list(SimpleNamespace(json=False))
            text = out.getvalue()
            self.assertIn("状态文件损坏", text)
            self.assertIn("panweb stop", text)


if __name__ == "__main__":
    unittest.main()
