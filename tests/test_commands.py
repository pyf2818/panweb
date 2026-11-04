import os
import tempfile
import unittest
from unittest import mock

from helpers import temp_home
from panweb import entries
from panweb.commands import MAX_COMMAND_LEN, parse_command


class CommandParseTests(unittest.TestCase):
    def parsed(self, text, defaults=None):
        result = parse_command(text, defaults)
        self.assertTrue(result["ok"], result)
        return result

    def rejected(self, text, kind="invalid_command", defaults=None):
        result = parse_command(text, defaults)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["type"], kind)
        self.assertTrue(result["examples"])
        return result

    def test_publish_port_and_defaults(self):
        d = self.parsed("发布 3000", {"share": False, "expires": "1d"})
        self.assertEqual((d["verb"], d["action"]), ("publish", "publish"))
        self.assertEqual(d["port"], 3000)
        self.assertIsNone(d["folder"])
        self.assertEqual(d["options"], {"pin": None, "expires": "1d",
                                        "share": False, "name": None})

    def test_publish_options_and_aliases(self):
        d = self.parsed("publish 3000 pin=1234 expires=1h share=off 名称=演示站")
        self.assertEqual(d["options"]["pin"], "1234")
        self.assertEqual(d["options"]["expires"], "1h")
        self.assertFalse(d["options"]["share"])
        self.assertEqual(d["options"]["name"], "演示站")
        self.assertEqual(self.parsed("发布 3000 有效期=永久")["options"]["expires"], "")

    def test_publish_folder_and_quotes(self):
        d = self.parsed("发布 /tmp/site")
        self.assertEqual(d["action"], "pages")
        self.assertEqual(d["folder"], "/tmp/site")
        d = self.parsed('发布 "./my site"')
        self.assertEqual(d["folder"], "./my site")
        self.assertEqual(self.parsed("发布 ~/site")["action"], "pages")

    def test_publish_omitted_target_is_left_to_core(self):
        d = self.parsed("发布")
        self.assertIsNone(d["port"])
        self.assertIsNone(d["folder"])
        self.assertEqual(d["action"], "publish")
        d = self.parsed("启动")
        self.assertEqual(d["action"], "run")
        self.assertIsNone(d["folder"])

    def test_run_folder(self):
        d = self.parsed("启动 /tmp/project share=off")
        self.assertEqual((d["verb"], d["action"]), ("run", "run"))
        self.assertEqual(d["folder"], "/tmp/project")
        self.assertFalse(d["options"]["share"])

    def test_stop_and_check_targets(self):
        self.assertEqual(self.parsed("停止 8080")["port"], 8080)
        self.assertEqual(self.parsed("stop all")["scope"], "all")
        self.assertEqual(self.parsed("停止 全部")["scope"], "all")
        self.assertEqual(self.parsed("停止 当前")["scope"], "current")
        self.assertEqual(self.parsed("检查 当前")["scope"], "current")
        self.assertEqual(self.parsed("check abc123")["id"], "abc123")

    def test_help(self):
        d = self.parsed("帮助")
        self.assertEqual(d["action"], "help")
        self.assertGreaterEqual(len(d["examples"]), 6)

    def test_rejects_shell_shapes_and_control_chars(self):
        for text in ("发布 3000; rm -rf /", "发布 3000 | cat",
                     "发布 $(whoami)", "发布 `id`", "发布 3000\n停止 全部"):
            self.rejected(text)

    def test_rejects_length(self):
        self.rejected("发布 " + "a" * MAX_COMMAND_LEN)

    def test_rejects_bad_options(self):
        self.rejected("发布 3000 pin=123")
        self.rejected("发布 3000 有效期=24h")
        self.rejected("发布 3000 分享=也许")
        self.rejected("发布 3000 名称=")
        self.rejected("发布 3000 pin=1234 pin=5678")
        self.rejected("发布 3000 foo=bar")

    def test_rejects_bad_targets_and_verbs(self):
        self.rejected("发布 0")
        self.rejected("发布 99999")
        self.rejected("发布 dist")
        self.rejected("发布 3000 3001")
        self.rejected("停止")
        self.rejected("检查 全部")
        self.rejected("停止 8080 pin=1234")
        self.rejected("rm -rf /", kind="invalid_command")

    def test_risky_port_is_refused_without_side_effects(self):
        result = self.rejected("发布 5432", kind="risky_port")
        self.assertIn("高级发布", result["error"]["hint"])
        self.assertIn("5432", result["error"]["message"])

    def test_parser_never_writes_pin(self):
        with temp_home("panweb-cmd-") as home:
            parse_command("发布 3000 pin=top-secret-99")
            for root, _dirs, files in os.walk(home):
                for name in files:
                    path = os.path.join(root, name)
                    with open(path, "rb") as f:
                        self.assertNotIn(b"top-secret-99", f.read(), path)


class EntryNodesTests(unittest.TestCase):
    def test_tunnel_states(self):
        self.assertEqual(entries.entry_nodes({})["tunnel"]["state"], "unknown")
        with mock.patch.object(entries, "pid_alive", return_value=True):
            node = entries.entry_nodes({"pid": 10})["tunnel"]
        self.assertEqual(node["state"], "online")
        with mock.patch.object(entries, "pid_alive", return_value=False):
            node = entries.entry_nodes({"pid": 10})["tunnel"]
        self.assertEqual(node["state"], "offline")

    def test_proxy_states(self):
        self.assertEqual(entries.entry_nodes({})["proxy"]["state"], "disabled")
        self.assertEqual(
            entries.entry_nodes({"proxy_port": 43000})["proxy"]["state"],
            "unknown")
        with mock.patch.object(entries, "pid_alive", return_value=False):
            node = entries.entry_nodes({"proxy_port": 43000,
                                        "server_pid": 12})["proxy"]
        self.assertEqual(node["state"], "offline")
        with mock.patch.object(entries, "pid_alive", return_value=True), \
                mock.patch.object(entries, "port_listening", return_value=True):
            node = entries.entry_nodes({"proxy_port": 43000,
                                        "server_pid": 12})["proxy"]
        self.assertEqual(node["state"], "online")

    def test_source_port_and_pages(self):
        with mock.patch.object(entries, "port_listening", return_value=False):
            self.assertEqual(entries.entry_nodes(
                {"kind": "port", "target": 9})["source"]["state"], "offline")
        with mock.patch.object(entries, "port_listening", return_value=True):
            self.assertEqual(entries.entry_nodes(
                {"kind": "port", "target": 3000})["source"]["state"], "online")
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(entries.entry_nodes(
                {"kind": "pages", "target": folder})["source"]["state"],
                "online")
            self.assertEqual(entries.entry_nodes(
                {"kind": "pages", "target": folder + "/missing"})["source"]["state"],
                "offline")
        self.assertEqual(entries.entry_nodes(
            {"kind": "port"})["source"]["state"], "unknown")

    def test_core_list_attaches_nodes(self):
        with temp_home("panweb-nodes-"):
            entries.register_entry({"id": "x", "name": "x", "kind": "pages",
                                    "target": "/tmp"})
            item = entries.core_list()[0]
            self.assertIn("nodes", item)
            self.assertEqual(set(item["nodes"]), {"tunnel", "proxy", "source"})
class FrontendPinTests(unittest.TestCase):
    def test_command_ui_never_persists_pin(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "ui", "src", "js",
                               "commands.js"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("localStorage", source)
        self.assertNotIn("sessionStorage", source)
        self.assertIn("maskPin(text)", source)
        self.assertIn('"$1$2****"', source)


if __name__ == "__main__":
    unittest.main()
