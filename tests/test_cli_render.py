"""CLI 渲染：target 可能是端口或文件夹，不能无脑用 %d。"""
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401  导入它顺带把 src/ 放进 sys.path
from panweb import cli_commands

PAGES = {"id": "p1", "name": "静态站", "kind": "pages",
         "folder": "/tmp/panweb-site", "url": "https://p1.trycloudflare.com",
         "reachable": True, "dns_slow": False, "started": "2026-11-04"}
PORT = {"id": "a1", "name": "应用", "kind": "port", "port": 3000,
        "url": "https://a1.trycloudflare.com", "reachable": True,
        "dns_slow": False, "started": "2026-11-04"}


class SourceRenderTests(unittest.TestCase):
    def test_source_text_branches_by_kind(self):
        self.assertEqual(cli_commands._source_text(PAGES), "/tmp/panweb-site")
        self.assertEqual(cli_commands._source_text(PORT),
                         "http://127.0.0.1:3000")

    def test_run_static_folder_does_not_crash(self):
        args = SimpleNamespace(folder="/tmp/panweb-site", name=None,
                               json=False, share=None, no_check=True,
                               pin=None, pin_stdin=False, expires=None)
        out = io.StringIO()
        with mock.patch.object(cli_commands, "load_publish_defaults",
                               return_value={}), \
                mock.patch.object(cli_commands, "core_run",
                                  return_value=dict(PAGES)), \
                redirect_stdout(out):
            cli_commands.cmd_run(args)
        text = out.getvalue()
        self.assertIn("已启动并发布", text)
        self.assertIn("/tmp/panweb-site", text)
        self.assertNotIn("127.0.0.1:%d", text)

    def test_list_renders_pages_source(self):
        out = io.StringIO()
        with mock.patch.object(cli_commands, "core_list",
                               return_value=[dict(PAGES), dict(PORT)]), \
                redirect_stdout(out):
            cli_commands.cmd_list(SimpleNamespace(json=False))
        text = out.getvalue()
        self.assertIn("/tmp/panweb-site", text)
        self.assertIn("http://127.0.0.1:3000", text)


if __name__ == "__main__":
    unittest.main()
