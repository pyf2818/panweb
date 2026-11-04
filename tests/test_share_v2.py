"""F1 分享页 2.0：标题/说明的校验、落库、渲染与二维码。"""
import hashlib
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import helpers
from panweb import cli, cli_commands, models, publish, qr, share
from panweb.errors import PanwebError

ENTRY = {"id": "e1", "name": "演示应用", "kind": "port", "target": 3000,
         "url": "https://e1.trycloudflare.com", "reachable": True,
         "dns_slow": False, "started": "2026-11-04",
         "share_url": "https://e1.trycloudflare.com/__panweb/share/tok"}

# 由 ui/vendor/qrcode.js（控制台分享图用的实现）生成的矩阵指纹
QR_SAMPLE = "https://panweb-demo.trycloudflare.com/__panweb/share/tok3n"
QR_SAMPLE_HASH = "6acfb478cd0853d4b0877f7201579e0e82e42893fa52d04cd192743b8ededf3a"


class NormalizeTests(unittest.TestCase):
    def test_strips_and_defaults(self):
        self.assertEqual(publish.normalize_title("  演示  "), "演示")
        self.assertIsNone(publish.normalize_title("   "))
        self.assertIsNone(publish.normalize_title(None))

    def test_length_limits(self):
        self.assertEqual(publish.normalize_title("a" * 80), "a" * 80)
        self.assertEqual(publish.normalize_desc("b" * 300), "b" * 300)
        with self.assertRaises(PanwebError):
            publish.normalize_title("a" * 81)
        with self.assertRaises(PanwebError):
            publish.normalize_desc("b" * 301)

    def test_rejects_control_characters(self):
        for value in ("a\nb", "a\rb", "a\tb", "a\x00b", "a\x7fb"):
            with self.assertRaises(PanwebError):
                publish.normalize_title(value)
            with self.assertRaises(PanwebError):
                publish.normalize_desc(value)

    def test_html_payload_is_kept_for_renderer_to_escape(self):
        self.assertEqual(publish.normalize_title("<script>x</script>"),
                         "<script>x</script>")


class EntryTitleTests(unittest.TestCase):
    def test_title_prefers_custom_then_name(self):
        self.assertEqual(models.entry_title({"title": "页标题",
                                             "name": "旧名"}), "页标题")
        self.assertEqual(models.entry_title({"title": " ",
                                             "name": "旧名"}), "旧名")
        self.assertEqual(models.entry_title({}), "panweb")


class CliParserTests(unittest.TestCase):
    def test_publish_accepts_title_desc_qr(self):
        args = cli.build_parser().parse_args(
            ["publish", "3000", "--title", "演示", "--desc", "说明",
             "--qr"])
        self.assertEqual(args.title, "演示")
        self.assertEqual(args.desc, "说明")
        self.assertTrue(args.qr)

    def test_pages_and_run_accept_same_flags(self):
        for cmd in (["pages", "/tmp/site"], ["run", "/tmp/site"]):
            args = cli.build_parser().parse_args(cmd + ["--title", "T",
                                                        "--desc", "D"])
            self.assertEqual((args.title, args.desc), ("T", "D"))
            self.assertFalse(args.qr)

    def test_defaults_keep_old_behaviour(self):
        args = cli.build_parser().parse_args(["publish", "3000"])
        self.assertIsNone(args.title)
        self.assertIsNone(args.desc)
        self.assertFalse(args.qr)


class CliPassthroughTests(unittest.TestCase):
    def test_publish_forwards_and_prints_qr(self):
        args = cli.build_parser().parse_args(
            ["publish", "3000", "--title", "演示", "--desc", "说明", "--qr"])
        out = io.StringIO()
        with mock.patch.object(cli_commands, "load_publish_defaults",
                               return_value={}), \
                mock.patch.object(cli_commands, "core_publish",
                                  return_value=dict(ENTRY)) as core, \
                redirect_stdout(out):
            cli_commands.cmd_publish(args)
        self.assertEqual(core.call_args.kwargs["title"], "演示")
        self.assertEqual(core.call_args.kwargs["desc"], "说明")
        self.assertIn("█", out.getvalue(), "终端二维码应使用半块字符")

    def test_json_mode_stays_clean(self):
        args = cli.build_parser().parse_args(
            ["publish", "3000", "--title", "演示", "--qr", "--json"])
        out = io.StringIO()
        with mock.patch.object(cli_commands, "load_publish_defaults",
                               return_value={}), \
                mock.patch.object(cli_commands, "core_publish",
                                  return_value=dict(ENTRY)), \
                redirect_stdout(out):
            cli_commands.cmd_publish(args)
        text = out.getvalue()
        self.assertNotIn("█", text)
        self.assertIn('"share_url"', text)

    def test_pages_and_run_forward_title_desc(self):
        for func, core_name, argv in (
                (cli_commands.cmd_pages, "core_pages", ["pages", "/tmp/site"]),
                (cli_commands.cmd_run, "core_run", ["run", "/tmp/site"])):
            args = cli.build_parser().parse_args(argv + ["--title", "T",
                                                         "--desc", "D"])
            with mock.patch.object(cli_commands, "load_publish_defaults",
                                   return_value={}), \
                    mock.patch.object(cli_commands, core_name,
                                      return_value=dict(ENTRY)) as core, \
                    redirect_stdout(io.StringIO()):
                func(args)
            self.assertEqual(core.call_args.kwargs["title"], "T")
            self.assertEqual(core.call_args.kwargs["desc"], "D")


class PersistTests(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-share-v2-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def test_publish_writes_title_and_desc_into_entry(self):
        captured = {}

        class Proc:
            pid = 4242

        with mock.patch.object(publish, "require_publish_license"), \
                mock.patch.object(publish, "_ensure_publishable_port"), \
                mock.patch.object(publish, "find_cloudflared",
                                  return_value="/bin/true"), \
                mock.patch.object(publish, "free_port", return_value=5599), \
                mock.patch.object(publish, "_spawn_proxy",
                                  return_value=Proc()), \
                mock.patch.object(publish, "port_listening",
                                  return_value=True), \
                mock.patch.object(publish, "start_tunnel",
                                  return_value=("https://e1.trycloudflare.com",
                                                Proc())), \
                mock.patch.object(publish, "verify_public",
                                  return_value=(True, False)), \
                mock.patch.object(publish, "register_entry",
                                  side_effect=lambda e: captured.update(e)), \
                mock.patch.object(publish, "write_menubar_state"):
            result = publish._publish_port(
                3000, "演示应用", pin="8668", share=True, auto_check=False,
                title="  标题  ", desc="说明")
        self.assertEqual(captured["title"], "标题")
        self.assertEqual(captured["desc"], "说明")
        self.assertEqual(result["title"], "标题")
        self.assertNotEqual(result["share_url"], None)

    def test_invalid_title_fails_before_spawning(self):
        with mock.patch.object(publish, "require_publish_license") as lic, \
                mock.patch.object(publish, "find_cloudflared") as cf:
            with self.assertRaises(PanwebError):
                publish._publish_port(3000, "演示应用", title="a\nb")
        lic.assert_not_called()
        cf.assert_not_called()


class ShareRenderTests(unittest.TestCase):
    def _page(self, entry, **kw):
        return share.build_share_page(entry, "https://x/share/tok",
                                      token="tok", **kw)

    def test_title_and_desc_rendered_and_escaped(self):
        entry = {"name": "旧名", "kind": "port", "title": "<b>标题</b>",
                 "desc": "<script>alert(1)</script>"}
        page = self._page(entry)
        self.assertIn("&lt;b&gt;标题&lt;/b&gt;", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("<title>&lt;b&gt;标题&lt;/b&gt; · panweb</title>",
                      page)

    def test_default_appearance_without_new_fields(self):
        entry = {"name": "演示应用", "kind": "port"}
        page = self._page(entry)
        self.assertIn("<title>演示应用 · panweb</title>", page)
        self.assertIn("这是一个从本机发布的实时应用。打开即可访问，无需安装。",
                      page)

    def test_pin_state_only_never_the_secret(self):
        page = self._page({"name": "演示应用"}, pin=True)
        self.assertIn("口令保护", page)
        self.assertIn('placeholder="访问口令"', page)
        self.assertNotIn("8668", page)


class QrTests(unittest.TestCase):
    def test_matrix_matches_bundled_qrcode_js(self):
        matrix = qr.encode(QR_SAMPLE)
        text = "\n".join("".join(str(v) for v in row) for row in matrix) + "\n"
        self.assertEqual(len(matrix), 33)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(),
                         QR_SAMPLE_HASH)

    def test_deterministic_and_finder_patterns(self):
        a = qr.encode("A")
        b = qr.encode("A")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 21)
        for r in range(7):
            for c in range(7):
                edge = r in (0, 6) or c in (0, 6)
                self.assertEqual(a[r][c], 1 if edge or 2 <= r <= 4 and 2 <= c <= 4
                                 else 0)

    def test_terminal_rendering_has_quiet_zone(self):
        rendered = qr.render_terminal(qr.encode("A"))
        lines = rendered.split("\n")
        self.assertEqual(len(lines), (21 + 8 + 1) // 2)
        self.assertEqual(len(lines[2]), 21 + 4, "右侧静区被 rstrip 收掉")
        self.assertTrue(any(ch in rendered for ch in "█▀▄"))

    def test_too_long_raises(self):
        with self.assertRaises(ValueError):
            qr.encode("x" * 300)


if __name__ == "__main__":
    unittest.main()
