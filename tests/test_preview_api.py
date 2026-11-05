"""`/api/preview` 契约：只解析本机真实条目，禁嵌/不可达给出可读降级。"""
import os
import sys
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import free_port  # noqa: E402

from panweb import ui_actions  # noqa: E402


class _FakeUi:
    def __init__(self, query):
        self.path = "/api/preview?" + query
        self.payload = None

    def send_json(self, obj, status=200):
        self.payload = obj
        return True


def call(query):
    handler = _FakeUi(query)
    ui_actions.handle_get(handler, "/api/preview")
    return handler.payload


def entry(**overrides):
    base = {"id": "demo", "name": "Demo", "kind": "port", "port": 4321,
            "alive": True}
    base.update(overrides)
    return base


class _HeadApp(BaseHTTPRequestHandler):
    xfo = None
    csp = None

    def log_message(self, fmt, *args):
        pass

    def do_HEAD(self):
        self.send_response(200)
        if self.xfo:
            self.send_header("X-Frame-Options", self.xfo)
        if self.csp:
            self.send_header("Content-Security-Policy", self.csp)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if self.xfo:
            self.send_header("X-Frame-Options", self.xfo)
        if self.csp:
            self.send_header("Content-Security-Policy", self.csp)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def head_server(**attrs):
    handler = type("HeadApp", (_HeadApp,), attrs)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


class PreviewApiTests(unittest.TestCase):
    def test_unknown_and_stopped_entries_have_no_preview(self):
        with mock.patch.object(ui_actions, "core_list", return_value=[]):
            payload = call("id=ghost")
        self.assertFalse(payload["ok"])
        self.assertIn("没有本机预览", payload["error"]["message"])

        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(alive=False)]):
            payload = call("id=demo")
        self.assertFalse(payload["ok"])
        self.assertIn("已停止", payload["error"]["message"])

    def test_direct_port_entry_uses_localhost_only(self):
        srv, port = head_server()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(port=port)]):
            payload = call("id=demo")
        self.assertTrue(payload["ok"], payload)
        data = payload["data"]
        self.assertEqual(data["url"], "http://127.0.0.1:%d/" % port)
        self.assertEqual(data["source"], "port")
        self.assertTrue(data["embeddable"])
        self.assertNotIn("cloudflare", data["url"])

    def test_proxy_port_wins_over_source_port(self):
        srv, port = head_server()
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(port=1, proxy_port=port)]):
            payload = call("id=demo")
        self.assertEqual(payload["data"]["source"], "proxy")
        self.assertEqual(payload["data"]["url"],
                         "http://127.0.0.1:%d/" % port)

    def test_xfo_deny_is_readable_degrade(self):
        srv, port = head_server(xfo="DENY")
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(port=port)]):
            payload = call("id=demo")
        self.assertFalse(payload["data"]["embeddable"])
        self.assertEqual(payload["data"]["reason"], "该应用禁止内嵌，请用打开")

    def test_csp_frame_ancestors_none_is_blocked(self):
        srv, port = head_server(csp="default-src 'self'; frame-ancestors 'none'")
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(port=port)]):
            payload = call("id=demo")
        self.assertFalse(payload["data"]["embeddable"])

    def test_csp_frame_ancestors_star_is_allowed(self):
        srv, port = head_server(csp="frame-ancestors *")
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(port=port)]):
            payload = call("id=demo")
        self.assertTrue(payload["data"]["embeddable"])
        self.assertEqual(payload["data"]["reason"], "")

    def test_csp_frame_ancestors_self_blocks_cross_port_origin(self):
        srv, port = head_server(csp="frame-ancestors 'self'")
        self.addCleanup(srv.shutdown)
        self.addCleanup(srv.server_close)
        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(port=port)]):
            payload = call("id=demo")
        self.assertFalse(payload["data"]["embeddable"])

    def test_connection_refused_is_readable_degrade(self):
        port = free_port()
        with mock.patch.object(ui_actions, "core_list",
                               return_value=[entry(port=port)]):
            payload = call("id=demo")
        self.assertTrue(payload["ok"], payload)
        self.assertFalse(payload["data"]["embeddable"])
        self.assertEqual(payload["data"]["reason"], "本机预览加载失败，请用打开")

    def test_query_never_accepts_arbitrary_url(self):
        with mock.patch.object(ui_actions, "core_list", return_value=[]):
            payload = call("id=" + urllib.parse.quote("http://evil.example"))
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
