"""项目级配置：优先级、校验、权限告警与秘密边界。"""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers
from panweb import publish, publish_options, project_config, runtime
from panweb.errors import PanwebError


class ConfigBase(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-f2-config-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.folder = self.dir.name

    def write(self, value, name=".panweb.json"):
        path = os.path.join(self.folder, name)
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(value, str):
                f.write(value)
            else:
                json.dump(value, f)
        return path


class LoadTests(ConfigBase):
    def test_absent_config_is_not_an_error(self):
        got = project_config.load_project_config(self.folder)
        self.assertFalse(got["exists"])
        self.assertEqual(got["values"], {})

    def test_valid_fields_are_normalized(self):
        self.write({"port": 8080, "script": " serve ", "name": " 项目 ",
                    "expires": "permanent", "share": False,
                    "title": " 标题 ", "desc": " 说明 ",
                    "pin_policy": "required"})
        got = project_config.load_project_config(self.folder)
        self.assertEqual(got["values"], {
            "port": 8080, "script": "serve", "name": "项目", "expires": "",
            "share": False, "title": "标题", "desc": "说明",
            "pin_policy": "required"})

    def test_unknown_key_is_rejected(self):
        self.write({"unknown": 1})
        with self.assertRaises(PanwebError) as ctx:
            project_config.load_project_config(self.folder)
        self.assertEqual(ctx.exception.err_type, "invalid_config")
        self.assertIn("unknown", ctx.exception.message)
        self.assertIn("port", ctx.exception.hint)

    def test_pin_plaintext_has_no_legal_place(self):
        for key in ("pin", "token", "password", "secret"):
            self.write({key: "s3cret-value"})
            with self.assertRaises(PanwebError) as ctx:
                project_config.load_project_config(self.folder)
            self.assertEqual(ctx.exception.err_type, "invalid_config")
            self.assertIn("不能写进", ctx.exception.message)
            self.assertNotIn("s3cret-value", ctx.exception.message)

    def test_type_errors_are_readable(self):
        cases = ({"port": "3000"}, {"port": True}, {"port": 0},
                 {"share": "yes"}, {"expires": "30m"}, {"title": 123},
                 {"title": "x" * 81}, {"desc": "换行\n说明"},
                 {"pin_policy": "optional"}, {"script": ""})
        for data in cases:
            self.write(data)
            with self.assertRaises(PanwebError) as ctx:
                project_config.load_project_config(self.folder)
            self.assertEqual(ctx.exception.err_type, "invalid_config")
            self.assertTrue(ctx.exception.message)

    def test_bad_json_and_non_object(self):
        for raw in ("{oops", "[]", "null"):
            self.write(raw)
            with self.assertRaises(PanwebError) as ctx:
                project_config.load_project_config(self.folder)
            self.assertEqual(ctx.exception.err_type, "invalid_config")

    def test_permission_warning_does_not_block(self):
        path = self.write({"name": "demo"})
        os.chmod(path, 0o644)
        got = project_config.load_project_config(self.folder)
        self.assertEqual(got["values"]["name"], "demo")
        self.assertTrue(any(w["type"] == "config_permission"
                            for w in got["warnings"]))
        os.chmod(path, 0o600)
        self.assertEqual(project_config.load_project_config(
            self.folder)["warnings"], [])

    def test_does_not_walk_upwards(self):
        self.write({"port": 9999})
        child = os.path.join(self.folder, "child")
        os.makedirs(child)
        got = project_config.load_project_config(child)
        self.assertFalse(got["exists"])
        self.assertEqual(got["values"], {})

    def test_inspect_reports_error_instead_of_raising(self):
        self.write("{oops")
        got = project_config.inspect_project_config(self.folder)
        self.assertTrue(got["exists"])
        self.assertEqual(got["error"]["type"], "invalid_config")
        self.assertTrue(got["error"]["hint"])


class PriorityTests(ConfigBase):
    def test_config_beats_memory(self):
        publish.remember_publish(expires="1h", share=False, last_port=4000)
        self.write({"port": 8080, "name": "配置名", "expires": "7d",
                    "share": True, "title": "配置标题", "desc": "配置说明"})
        got = publish_options.resolve_options(self.folder)
        self.assertEqual(got["port"], 8080)
        self.assertEqual(got["name"], "配置名")
        self.assertEqual(got["expires"], "7d")
        self.assertTrue(got["share"])
        self.assertEqual(got["title"], "配置标题")
        self.assertEqual(got["sources"]["expires"], "config")
        self.assertEqual(got["sources"]["share"], "config")

    def test_explicit_beats_config(self):
        self.write({"port": 8080, "name": "配置名", "expires": "7d",
                    "share": True, "title": "配置标题"})
        got = publish_options.resolve_options(
            self.folder, port=3000, name="显式名", expires="1h",
            share=False, title="显式标题")
        self.assertEqual(got["port"], 3000)
        self.assertEqual(got["name"], "显式名")
        self.assertEqual(got["expires"], "1h")
        self.assertFalse(got["share"])
        self.assertEqual(got["title"], "显式标题")
        for key in ("port", "name", "expires", "share", "title"):
            self.assertEqual(got["sources"][key], "argument")

    def test_memory_and_builtins_fill_the_rest(self):
        publish.remember_publish(expires="1d", share=False)
        got = publish_options.resolve_options(self.folder)
        self.assertEqual(got["expires"], "1d")
        self.assertFalse(got["share"])
        self.assertEqual(got["sources"]["expires"], "defaults")
        self.assertEqual(got["sources"]["name"], "builtin")

    def test_pin_policy_required_but_no_pin(self):
        self.write({"pin_policy": "required"})
        with self.assertRaises(PanwebError) as ctx:
            publish_options.resolve_options(self.folder)
        self.assertEqual(ctx.exception.err_type, "pin_required")
        self.assertIn("不会写进", ctx.exception.hint)
        got = publish_options.resolve_options(self.folder, pin="abcd")
        self.assertEqual(got["pin"], "abcd")

    def test_pin_policy_none_allows_explicit_pin(self):
        self.write({"pin_policy": "none"})
        self.assertEqual(publish_options.resolve_options(
            self.folder, pin="abcd")["pin"], "abcd")


class CoreIntegrationTests(ConfigBase):
    def _entry(self, **extra):
        entry = {"id": "x1", "name": "demo", "url": "https://x",
                 "share_url": "https://share", "reachable": True,
                 "dns_slow": False}
        entry.update(extra)
        return entry

    def test_core_publish_uses_config_port_and_fields(self):
        self.write({"port": 8080, "name": "配置名", "expires": "1h",
                    "title": "T", "desc": "D", "share": False})
        with mock.patch.object(publish, "port_listening", return_value=True), \
                mock.patch.object(publish, "_publish_port",
                                  return_value=self._entry()) as core:
            publish.core_publish(folder=self.folder)
        self.assertEqual(core.call_args.args[0], 8080)
        self.assertEqual(core.call_args.kwargs["title"], "T")
        self.assertEqual(core.call_args.kwargs["desc"], "D")
        self.assertFalse(core.call_args.kwargs["share"])

    def test_core_pages_uses_config_fields(self):
        self.write({"name": "配置名", "expires": "7d", "title": "T"})
        with mock.patch.object(publish, "_publish_port",
                               return_value=self._entry()) as core:
            publish.core_pages(self.folder)
        self.assertEqual(core.call_args.args[1], "配置名")
        self.assertEqual(core.call_args.kwargs["title"], "T")

    def test_config_content_does_not_reach_event_stream(self):
        marker = "SECRET-CONFIG-MARKER-123"
        self.write({"name": "demo", "desc": marker})
        with mock.patch.object(publish, "_publish_port",
                               return_value=self._entry()):
            publish.core_pages(self.folder)
        root = runtime.HOME_DIR
        blob = ""
        for base, _, files in os.walk(root):
            for name in files:
                path = os.path.join(base, name)
                try:
                    with open(path, "rb") as f:
                        blob += f.read().decode("utf-8", "replace")
                except OSError:
                    pass
        self.assertNotIn(marker, blob, "配置内容不能进事件流/日志")


if __name__ == "__main__":
    unittest.main()
