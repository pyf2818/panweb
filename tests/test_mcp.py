"""MCP 契约：schema 可发现、异步提交/轮询、超时语义与统一回执。"""
import json
import threading
import time
import unittest
from unittest import mock

import helpers  # noqa: F401  顺带把 src/ 放进 sys.path
from panweb import jobs, mcp_server
from panweb.errors import PanwebError

PUBLISH_SCHEMAS = {
    "publish_port": {"port", "folder", "name", "pin", "expires", "share",
                     "title", "desc", "wait"},
    "publish_pages": {"folder", "name", "pin", "expires", "title", "desc",
                      "wait"},
    "run_project": {"folder", "script", "name", "pin", "expires", "share",
                    "title", "desc", "wait"},
}
RECEIPT_KEYS = {"ok", "job_id", "state", "id", "url", "share_url",
                "expires_at", "check", "error"}


class McpBase(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-mcp-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self._reset()
        self.addCleanup(self._reset)
        self.gate = threading.Event()

    def _reset(self):
        with jobs._LOCK:
            jobs._JOBS.clear()
            jobs._FLIGHT.clear()

    def wait_done(self, job_id, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = jobs.get(job_id)
            if state and state.get("done"):
                return state
            time.sleep(0.01)
        self.fail("任务在 %.1f 秒内没有结束" % timeout)


class SchemaTests(unittest.TestCase):
    def test_every_tool_has_discoverable_object_schema(self):
        tools = {tool["name"]: tool for tool in mcp_server.MCP_TOOLS}
        self.assertIn("get_job", tools)
        for tool in mcp_server.MCP_TOOLS:
            self.assertIsInstance(tool.get("description"), str)
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertIsInstance(schema.get("properties"), dict)

    def test_publish_tools_expose_expected_arguments(self):
        tools = {tool["name"]: tool for tool in mcp_server.MCP_TOOLS}
        for name, expected in PUBLISH_SCHEMAS.items():
            props = tools[name]["inputSchema"]["properties"]
            self.assertEqual(set(props), expected, name)
            self.assertEqual(props["expires"]["enum"],
                             ["1h", "1d", "7d", "permanent"])
            self.assertEqual(props["expires"]["type"], "string")
            self.assertEqual(props["pin"]["type"], "string")
            self.assertEqual(props["wait"]["type"], "boolean")
            self.assertFalse(props["wait"]["default"])
            self.assertIn("不落盘", props["pin"]["description"])
            for key in ("name", "title", "desc"):
                if key in props:
                    self.assertEqual(props[key]["type"], "string")
            if "title" in props:
                self.assertEqual(props["title"]["maxLength"], 80)
            if "desc" in props:
                self.assertEqual(props["desc"]["maxLength"], 300)
            if "port" in props:
                self.assertEqual(props["port"]["minimum"], 1)
                self.assertEqual(props["port"]["maximum"], 65535)

    def test_get_job_requires_id_and_documents_wait(self):
        tool = {t["name"]: t for t in mcp_server.MCP_TOOLS}["get_job"]
        schema = tool["inputSchema"]
        self.assertEqual(schema["required"], ["id"])
        self.assertTrue(schema["properties"]["wait"]["default"] is False)


class AsyncFlowTests(McpBase):
    def test_submit_returns_job_then_poll_succeeds(self):
        def fake(*args, **kwargs):
            self.gate.wait(2)
            kwargs["progress"]("发布完成")
            return {"id": "e1", "url": "https://example.test",
                    "share_url": "https://share.test", "expires_at": 123}
        with mock.patch.object(mcp_server, "core_publish", side_effect=fake):
            first = mcp_server._mcp_call("publish_port", {"port": 3000})
        self.assertTrue(first["ok"])
        self.assertEqual(first["state"], "running")
        self.assertEqual(first["id"], None)
        self.assertIsNotNone(first["job_id"])
        self.assertEqual(RECEIPT_KEYS & set(first), RECEIPT_KEYS)
        self.gate.set()
        done = mcp_server._mcp_call("get_job",
                                    {"id": first["job_id"], "wait": True})
        self.assertEqual(done["state"], "succeeded")
        self.assertTrue(done["ok"])
        self.assertEqual(done["id"], "e1")
        self.assertEqual(done["url"], "https://example.test")
        self.assertEqual(done["share_url"], "https://share.test")
        self.assertEqual(done["expires_at"], 123)
        self.assertIsNone(done["error"])

    def test_wait_timeout_is_not_a_failure(self):
        def fake(*args, **kwargs):
            self.gate.wait(2)
            return {"id": "e2", "url": "https://example.test"}

        with mock.patch.object(mcp_server, "core_publish", side_effect=fake), \
                mock.patch.object(mcp_server, "WAIT_TIMEOUT", 0.05):
            first = mcp_server._mcp_call("publish_port",
                                         {"port": 3000, "wait": True})
        self.assertTrue(first["ok"])
        self.assertEqual(first["state"], "running")
        self.assertIsNotNone(first["job_id"])
        self.assertIsNone(first["error"])
        self.gate.set()
        self.wait_done(first["job_id"])
        done = mcp_server._mcp_call("get_job", {"id": first["job_id"]})
        self.assertEqual(done["state"], "succeeded")

    def test_failed_job_returns_structured_error(self):
        def fake(*args, **kwargs):
            raise PanwebError(2, "invalid_argument", "文件夹不存在：/nope",
                              "确认路径后再试")

        with mock.patch.object(mcp_server, "core_pages", side_effect=fake):
            first = mcp_server._mcp_call("publish_pages", {"folder": "/nope"})
        done = mcp_server._mcp_call("get_job",
                                    {"id": first["job_id"], "wait": True})
        self.assertFalse(done["ok"])
        self.assertEqual(done["state"], "failed")
        self.assertEqual(done["error"]["type"], "invalid_argument")
        self.assertIn("/nope", done["error"]["message"])
        self.assertEqual(done["error"]["hint"], "确认路径后再试")

    def test_same_target_reuses_running_job(self):
        calls = []

        def fake(*args, **kwargs):
            calls.append(1)
            self.gate.wait(2)
            return {"id": "e3", "url": "https://example.test"}

        with mock.patch.object(mcp_server, "core_pages", side_effect=fake):
            one = mcp_server._mcp_call("publish_pages", {"folder": "/tmp/a"})
            two = mcp_server._mcp_call("publish_pages", {"folder": "/tmp/a"})
            other = mcp_server._mcp_call("publish_pages", {"folder": "/tmp/b"})
        self.assertEqual(one["job_id"], two["job_id"])
        self.assertNotEqual(one["job_id"], other["job_id"])
        self.gate.set()
        for job_id in (one["job_id"], other["job_id"]):
            self.wait_done(job_id)
        self.assertEqual(len(calls), 2, "复用请求不能再跑一遍发布")

    def test_unknown_job_id(self):
        got = mcp_server._mcp_call("get_job", {"id": "nope"})
        self.assertFalse(got["ok"])
        self.assertEqual(got["state"], "failed")
        self.assertEqual(got["error"]["type"], "job_not_found")
        self.assertTrue(got["error"]["hint"])

    def test_get_job_requires_id(self):
        with self.assertRaises(PanwebError) as ctx:
            mcp_server._mcp_call("get_job", {})
        self.assertEqual(ctx.exception.err_type, "invalid_argument")

    def test_unknown_tool_raises_for_handler_to_wrap(self):
        with self.assertRaises(PanwebError) as ctx:
            mcp_server._mcp_call("nope", {})
        self.assertEqual(ctx.exception.err_type, "unknown_tool")


class SecretTests(McpBase):
    def test_receipt_never_contains_pin_or_raw_config(self):
        marker = "PIN-OR-CONFIG-MARKER"

        def fake(*args, **kwargs):
            return {"id": "e4", "url": "https://example.test",
                    "share_url": "https://share.test", "pin": marker,
                    "desc": marker, "config": {"pin": marker}}

        with mock.patch.object(mcp_server, "core_pages", side_effect=fake):
            first = mcp_server._mcp_call("publish_pages",
                                         {"folder": ".", "pin": marker})
        done = mcp_server._mcp_call("get_job",
                                    {"id": first["job_id"], "wait": True})
        blob = json.dumps([first, done], ensure_ascii=False)
        self.assertNotIn(marker, blob)
        self.assertEqual(RECEIPT_KEYS & set(done), RECEIPT_KEYS)


if __name__ == "__main__":
    unittest.main()
