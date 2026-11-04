"""拆分后的对外契约：行数上限、核心签名与旧名字仍可导入/打补丁。"""
import inspect
import pathlib
import unittest
from unittest import mock

import helpers  # noqa: F401  顺带把 src/ 放进 sys.path
from panweb import cli_commands, publish

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "panweb"


def lines(name):
    return len((SRC / name).read_text(encoding="utf-8").splitlines())


class SizeTests(unittest.TestCase):
    def test_publish_stays_below_limit(self):
        self.assertLess(lines("publish.py"), 400)

    def test_cli_commands_stays_below_limit(self):
        self.assertLess(lines("cli_commands.py"), 450)


class SignatureTests(unittest.TestCase):
    def test_public_core_signatures_are_kept(self):
        expected = {
            "core_publish": ("port", "name", "pin", "expires", "share",
                             "auto_check", "progress", "title", "desc",
                             "folder"),
            "core_pages": ("folder", "name", "pin", "expires", "auto_check",
                           "progress", "title", "desc"),
            "core_run": ("folder", "name", "share", "auto_check", "pin",
                         "expires", "progress", "title", "desc", "script"),
            "core_set_pin": ("entry_id", "pin", "actor"),
            "core_detect": ("folder",),
        }
        for name, params in expected.items():
            got = tuple(inspect.signature(getattr(publish, name)).parameters)
            self.assertEqual(got, params, name)

    def test_legacy_names_are_still_reexported(self):
        for name in ("load_publish_defaults", "remember_publish",
                     "normalize_title", "normalize_desc", "core_detect",
                     "_pick_port", "_sniff_port", "_ensure_publishable_port",
                     "is_risky_port", "_emit", "_publish_port"):
            self.assertTrue(hasattr(publish, name), name)
        with mock.patch.object(publish, "_publish_port", return_value={}):
            self.assertEqual(publish._publish_port(), {})


class CliReexportTests(unittest.TestCase):
    def test_source_text_is_still_on_cli_commands(self):
        self.assertTrue(hasattr(cli_commands, "_source_text"))


if __name__ == "__main__":
    unittest.main()
