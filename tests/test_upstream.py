"""上游兼容层：Host 透传模式、鉴权头注入与代理转发接线。"""
import base64
import os
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import free_port, proxy_log_tail, temp_home
from panweb import runtime, store, upstream
from panweb.errors import PanwebError
from panweb.processes import port_listening, stop_process
from panweb.publish import _spawn_proxy

VISITOR_HOST = "demo-a-b-c.trycloudflare.com"


class RecordHandler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        RecordHandler.seen.append({
            "host": self.headers.get("Host"),
            "auth": self.headers.get("Authorization"),
            "api_key": self.headers.get("X-Api-Key"),
            "forwarded_host": self.headers.get("X-Forwarded-Host"),
            "forwarded_proto": self.headers.get("X-Forwarded-Proto"),
            "connection": self.headers.get("Connection"),
        })
        body = b"UPSTREAM-SAW-YOU"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ForwardHeadersTests(unittest.TestCase):
    ITEMS = [("Host", VISITOR_HOST), ("User-Agent", "curl/8"),
             ("Cookie", "sid=1"), ("Connection", "keep-alive"),
             ("Proxy-Connection", "keep-alive"), ("Transfer-Encoding", "chunked")]

    def pairs(self, **kw):
        return dict(upstream.forward_headers(self.ITEMS, "1.2.3.4", **kw))

    def test_loopback_keeps_local_host_and_records_public_one(self):
        headers = self.pairs(host_value="127.0.0.1:3000")
        self.assertEqual(headers["Host"], "127.0.0.1:3000")
        self.assertEqual(headers["X-Forwarded-Host"], VISITOR_HOST)
        self.assertEqual(headers["X-Forwarded-Proto"], "https")
        self.assertEqual(headers["X-Forwarded-For"], "1.2.3.4")

    def test_tunnel_mode_passes_public_host_through(self):
        headers = self.pairs(host_value=VISITOR_HOST)
        self.assertEqual(headers["Host"], VISITOR_HOST)

    def test_hop_by_hop_headers_are_dropped(self):
        headers = self.pairs(host_value="127.0.0.1:3000")
        for name in ("Connection", "Proxy-Connection", "Transfer-Encoding"):
            self.assertNotIn(name, headers)

    def test_websocket_handshake_headers_survive(self):
        items = self.ITEMS + [("Upgrade", "websocket"), ("Connection", "Upgrade")]
        pairs = upstream.forward_headers(items, "1.2.3.4", websocket=True)
        names = [k for k, _ in pairs]
        self.assertIn("Upgrade", names)
        self.assertEqual(dict(pairs)["Connection"], "Upgrade")

    def test_auth_header_is_appended(self):
        headers = self.pairs(host_value="127.0.0.1:3000",
                             auth=("Authorization", "Bearer t0k"))
        self.assertEqual(headers["Authorization"], "Bearer t0k")


class NormalizeAuthTests(unittest.TestCase):
    def test_bearer_and_basic_and_header(self):
        self.assertEqual(upstream.normalize_auth("bearer", token="abc"),
                         {"kind": "bearer", "token": "abc"})
        rec = upstream.normalize_auth("basic", user="anna", password="p@ss")
        pair = upstream.auth_header_of(rec)
        self.assertEqual(pair[0], "Authorization")
        self.assertEqual(base64.b64decode(pair[1][6:]).decode(), "anna:p@ss")
        self.assertEqual(
            upstream.auth_header_of(
                upstream.normalize_auth("header", name="X-Api-Key", value="k-1")),
            ("X-Api-Key", "k-1"))

    def test_newlines_cannot_become_extra_headers(self):
        for bad in ("abc\r\nX-Evil: 1", "abc\nX-Evil: 1", "abc\x00"):
            with self.assertRaises(PanwebError):
                upstream.normalize_auth("bearer", token=bad)
        with self.assertRaises(PanwebError):
            upstream.normalize_auth("header", name="X-Evil\r\nHost: attacker",
                                    value="v")

    def test_non_ascii_and_oversize_rejected(self):
        with self.assertRaises(PanwebError):
            upstream.normalize_auth("bearer", token="令牌 abc")
        with self.assertRaises(PanwebError):
            upstream.normalize_auth("bearer", token="x" * 513)
        with self.assertRaises(PanwebError):
            upstream.normalize_auth("bearer", token="   ")

    def test_connection_layer_headers_cannot_be_overridden(self):
        for name in ("Host", "Connection", "Upgrade", "Content-Length"):
            with self.assertRaises(PanwebError):
                upstream.normalize_auth("header", name=name, value="v")

    def test_unknown_kind_and_mode_rejected(self):
        with self.assertRaises(PanwebError):
            upstream.normalize_auth("digest", token="x")
        self.assertEqual(upstream.normalize_host_mode("TUNNEL"), "tunnel")
        with self.assertRaises(PanwebError):
            upstream.normalize_host_mode("public")


class AuthStoreTests(unittest.TestCase):
    def test_secret_lives_outside_state_and_is_masked(self):
        with temp_home("panweb-auth-"):
            store.ensure_private_dirs()
            store.save_json(runtime.STATE_FILE, [{"id": "a1", "name": "演示"}])
            upstream.set_auth("a1", upstream.normalize_auth(
                "bearer", token="sup3r-s3cret"))
            path = upstream.auth_file_path("a1")
            self.assertTrue(runtime.SECRETS_DIR in path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(upstream.auth_header("a1"),
                             ("Authorization", "Bearer sup3r-s3cret"))
            with open(runtime.STATE_FILE, encoding="utf-8") as f:
                self.assertNotIn("sup3r-s3cret", f.read())
            self.assertEqual(store.load_state()[0]["auth_kind"], "bearer")
            info = upstream.describe_auth("a1")
            self.assertEqual(info["label"], "Bearer 令牌")
            self.assertNotIn("sup3r-s3cret", str(info))
            upstream.clear_auth("a1")
            self.assertIsNone(upstream.auth_header("a1"))
            self.assertFalse(os.path.exists(path))
            self.assertNotIn("auth_kind", store.load_state()[0])

    def test_missing_or_broken_file_is_no_configuration(self):
        with temp_home("panweb-auth-"):
            store.ensure_private_dirs()
            self.assertIsNone(upstream.auth_header("nope"))
            with open(upstream.auth_file_path("a2"), "w", encoding="utf-8") as f:
                f.write("{ not json")
            self.assertIsNone(upstream.auth_header("a2"))
            self.assertIsNone(upstream.auth_header_of({"kind": "bearer"}))
            self.assertIsNone(upstream.auth_header_of({"kind": "header",
                                                      "name": "Host",
                                                      "value": "evil"}))


class HostModeTests(unittest.TestCase):
    def test_default_is_loopback_and_mode_persisted(self):
        with temp_home("panweb-host-"):
            store.ensure_private_dirs()
            store.save_json(runtime.STATE_FILE, [{"id": "h1", "name": "n"}])
            self.assertEqual(upstream.host_mode(store.load_state()[0]), "loopback")
            self.assertEqual(upstream.host_mode(None), "loopback")
            upstream.set_host_mode("h1", "tunnel")
            self.assertEqual(store.load_state()[0]["host_mode"], "tunnel")
            self.assertEqual(upstream.host_mode(store.load_state()[0]), "tunnel")
            with self.assertRaises(PanwebError):
                upstream.set_host_mode("missing", "tunnel")


class ProxyUpstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = temp_home("panweb-upstream-")
        cls.home = cls.ctx.__enter__()
        store.ensure_private_dirs()
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), RecordHandler)
        cls.backend.daemon_threads = True
        cls.backend_port = cls.backend.server_address[1]
        cls.thread = threading.Thread(target=cls.backend.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.ctx.__exit__(None, None, None)

    def spawn(self, entry_id, **entry_extra):
        proxy_port = free_port()
        entry = {"id": entry_id, "name": "上游测试", "kind": "port",
                 "target": self.backend_port, "proxy_port": proxy_port,
                 "url": "https://%s" % VISITOR_HOST}
        entry.update(entry_extra)
        store.save_state([entry])
        proc = _spawn_proxy(proxy_port, entry_id, target_port=self.backend_port)
        self.assertIsNotNone(proc)
        # macOS runner 首次启动子进程明显更慢，20 秒仍远小于测试超时
        deadline = time.time() + 20
        while time.time() < deadline and not port_listening(proxy_port):
            time.sleep(0.1)
        self.assertTrue(port_listening(proxy_port),
                        "代理未启动（poll=%r）\n%s" %
                        (proc.poll(), proxy_log_tail(entry_id)))
        return proxy_port, proc

    def get(self, port):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/", headers={"Host": VISITOR_HOST})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_default_mode_gives_upstream_the_local_host(self):
        port, proc = self.spawn("up1")
        RecordHandler.seen = []
        try:
            status, body = self.get(port)
            self.assertEqual(status, 200)
            self.assertIn(b"UPSTREAM-SAW-YOU", body)
            seen = RecordHandler.seen[-1]
            self.assertEqual(seen["host"], "127.0.0.1:%d" % self.backend_port)
            self.assertEqual(seen["forwarded_host"], VISITOR_HOST)
            self.assertIsNone(seen["auth"])
        finally:
            stop_process(proc, ("--internal-proxy",))

    def test_tunnel_mode_and_bearer_reach_the_upstream(self):
        upstream.set_auth("up2", upstream.normalize_auth("bearer", token="t0k-9"))
        try:
            port, proc = self.spawn("up2", host_mode="tunnel")
            RecordHandler.seen = []
            try:
                status, _ = self.get(port)
                self.assertEqual(status, 200)
                seen = RecordHandler.seen[-1]
                self.assertEqual(seen["host"], VISITOR_HOST)
                self.assertEqual(seen["auth"], "Bearer t0k-9")
            finally:
                stop_process(proc, ("--internal-proxy",))
        finally:
            upstream.remove_auth_file("up2")

    def test_custom_header_auth_reaches_the_upstream(self):
        upstream.set_auth("up3", upstream.normalize_auth(
            "header", name="X-Api-Key", value="key-777"))
        try:
            port, proc = self.spawn("up3")
            RecordHandler.seen = []
            try:
                status, _ = self.get(port)
                self.assertEqual(status, 200)
                self.assertEqual(RecordHandler.seen[-1]["api_key"], "key-777")
            finally:
                stop_process(proc, ("--internal-proxy",))
        finally:
            upstream.remove_auth_file("up3")


if __name__ == "__main__":
    unittest.main()
