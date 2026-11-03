"""发布默认值与 CLI 参数：少填一步，但不能把危险默认悄悄塞给用户。"""
import unittest
from unittest import mock

import helpers
from panweb import cli, publish
from panweb.errors import PanwebError


def cand(port, published=False, title=None, risky=None):
    return {"port": port, "title": title or "应用 %d" % port,
            "process": "node", "published": published, "risky": risky}


class DefaultsTests(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-defaults-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def test_roundtrip(self):
        publish.remember_publish(last_port=3000, last_folder="/tmp/site",
                                 expires="7d", share=False)
        got = publish.load_publish_defaults()
        self.assertEqual(got["last_port"], 3000)
        self.assertEqual(got["last_folder"], "/tmp/site")
        self.assertEqual(got["expires"], "7d")
        self.assertFalse(got["share"])
        self.assertNotIn("pin", got, "口令只能留在浏览器标签页，不能落盘")

    def test_no_defaults_is_safe(self):
        got = publish.load_publish_defaults()
        self.assertEqual(got["expires"], "")
        self.assertTrue(got["share"], "默认生成分享页，和网页端一致")


class PickPortTests(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-pick-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def _pick(self, candidates, last=None):
        if last:
            publish.remember_publish(last_port=last)
        with mock.patch("panweb.discovery.core_discover",
                        return_value=candidates):
            return publish._pick_port()

    def test_last_port_wins_when_alive(self):
        self.assertEqual(self._pick([cand(3000), cand(8080)], last=8080), 8080)

    def test_single_fresh_candidate(self):
        self.assertEqual(self._pick([cand(3000, published=True), cand(8080)]), 8080)

    def test_ambiguous_asks_for_port(self):
        with self.assertRaises(PanwebError) as ctx:
            self._pick([cand(3000), cand(8080)])
        self.assertEqual(ctx.exception.err_type, "ambiguous_port")
        self.assertIn("3000", ctx.exception.hint)

    def test_nothing_running(self):
        with self.assertRaises(PanwebError) as ctx:
            self._pick([])
        self.assertEqual(ctx.exception.err_type, "invalid_argument")
        self.assertIn("panweb discover", ctx.exception.hint)


class ProgressAndCliTests(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-progress-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)

    def test_publish_reports_port_step(self):
        entry = {"id": "x", "name": "demo", "url": "https://x", "share_url": ""}
        steps = []
        with mock.patch.object(publish, "port_listening", return_value=True), \
                mock.patch.object(publish, "_publish_port", return_value=entry):
            publish.core_publish(3000, progress=steps.append)
        self.assertTrue(any("端口 3000" in s for s in steps), steps)

    def test_cli_port_and_folder_are_optional(self):
        parser = cli.build_parser()
        self.assertIsNone(parser.parse_args(["publish"]).port)
        self.assertEqual(parser.parse_args(["pages"]).folder, ".")
        self.assertEqual(parser.parse_args(["run"]).folder, ".")


if __name__ == "__main__":
    unittest.main()
