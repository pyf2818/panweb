"""代理语义：OPTIONS、真实客户端 IP、伪造头、chunked 请求体与响应收口。"""
import json
import os
import socket
import threading
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import temp_home
from panweb import runtime, store, upstream, visits
from panweb.proxy import ProxyHandler
from panweb.visits import _hash_ip

VISITOR = "demo-a-b-c.trycloudflare.com"


class RecordingHandler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, fmt, *args):
        pass

    def _record(self):
        body = b""
        length = self.headers.get("Content-Length")
        if length:
            body = self.rfile.read(int(length))
        RecordingHandler.seen.append({
            "method": self.command,
            "host": self.headers.get("Host"),
            "auth": self.headers.get("Authorization"),
            "xff_all": self.headers.get_all("X-Forwarded-For") or [],
            "real_all": self.headers.get_all("X-Real-IP") or [],
            "forwarded": self.headers.get("Forwarded"),
            "cf": self.headers.get("CF-Connecting-IP"),
            "body": body,
        })
        return body

    def _reply(self, status, body=b"UPSTREAM"):
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._record()
        self._reply(200, b"UPSTREAM-SAW-YOU")

    def do_POST(self):
        body = self._record()
        self._reply(200, b"GOT:" + body)

    def do_OPTIONS(self):
        self._record()
        self._reply(204)


class PartialHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "100")
        self.end_headers()
        self.wfile.write(b"PARTIAL")
        self.wfile.flush()
        self.close_connection = True


def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class ForwardHeaderUnitTests(unittest.TestCase):
    ITEMS = [("Host", VISITOR),
             ("Authorization", "Bearer attacker"),
             ("X-Forwarded-For", "6.6.6.6"),
             ("X-Real-IP", "7.7.7.7"),
             ("X-Forwarded-Proto", "http"),
             ("X-Forwarded-Host", "evil.example"),
             ("CF-Connecting-IP", "8.8.8.8"),
             ("Forwarded", "for=6.6.6.6")]

    def pairs(self, **kw):
        return upstream.forward_headers(self.ITEMS, "203.0.113.9", **kw)

    def test_forged_forwarding_headers_are_stripped_not_appended(self):
        pairs = self.pairs(host_value="127.0.0.1:3000")
        self.assertEqual([v for k, v in pairs if k.lower() == "x-forwarded-for"],
                         ["203.0.113.9"])
        self.assertEqual([v for k, v in pairs if k.lower() == "x-real-ip"],
                         ["203.0.113.9"])
        for name in ("Forwarded", "CF-Connecting-IP", "X-Forwarded-Proto"):
            self.assertEqual([v for k, v in pairs if k.lower() == name.lower()],
                             [] if name != "X-Forwarded-Proto"
                             else ["https"])
        self.assertEqual([v for k, v in pairs
                          if k.lower() == "x-forwarded-host"], [VISITOR])

    def test_configured_auth_replaces_visitor_authorization(self):
        pairs = self.pairs(host_value="127.0.0.1:3000",
                           auth=("Authorization", "Bearer own-token"))
        self.assertEqual([v for k, v in pairs
                          if k.lower() == "authorization"], ["Bearer own-token"])

    def test_visitor_authorization_survives_when_panweb_sets_no_auth(self):
        pairs = self.pairs(host_value="127.0.0.1:3000")
        self.assertEqual([v for k, v in pairs
                          if k.lower() == "authorization"], ["Bearer attacker"],
                         "没配置上游凭据时不能吞掉应用自己的登录头")


class ClientIpUnitTests(unittest.TestCase):
    def test_prefers_cloudflare_then_falls_back(self):
        self.assertEqual(upstream.client_ip(
            {"CF-Connecting-IP": "203.0.113.5", "X-Real-IP": "10.0.0.1"},
            "127.0.0.1"), "203.0.113.5")
        self.assertEqual(upstream.client_ip(
            {"X-Forwarded-For": "bad, 198.51.100.7, 10.0.0.1"},
            "127.0.0.1"), "198.51.100.7")
        self.assertEqual(upstream.client_ip({}, "127.0.0.1"), "127.0.0.1")

    def test_invalid_values_are_ignored(self):
        self.assertEqual(upstream.client_ip(
            {"CF-Connecting-IP": "not-an-ip", "X-Real-IP": "also bad"},
            "127.0.0.1"), "127.0.0.1")


class ProxySemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = temp_home("panweb-sem-")
        cls.home = cls.ctx.__enter__()
        store.ensure_private_dirs()
        cls.backend = serve(RecordingHandler)
        cls.backend_port = cls.backend.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        store.save_json(runtime.STATE_FILE, [{
            "id": "sem1", "name": "语义", "kind": "port",
            "target": self.backend_port, "url": "https://" + VISITOR,
        }])
        RecordingHandler.seen = []
        upstream.remove_auth_file("sem1")
        self.proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        self.proxy.daemon_threads = True
        self.proxy.entry_id = "sem1"
        self.proxy.serve_dir = None
        self.proxy.target_port = self.backend_port
        self.proxy.target_host = "127.0.0.1"
        self.proxy.entry_cache = None
        self.port = self.proxy.server_address[1]
        threading.Thread(target=self.proxy.serve_forever, daemon=True).start()

    def tearDown(self):
        self.proxy.shutdown()
        self.proxy.server_close()
        upstream.remove_auth_file("sem1")

    def request(self, method, headers=None, raw=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        if raw:
            conn.putrequest(method, "/")
            for k, v in (headers or {}).items():
                conn.putheader(k, v)
            conn.endheaders()
            conn.send(raw)
        else:
            conn.request(method, "/", headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_options_is_routed_to_the_upstream(self):
        status, _ = self.request("OPTIONS", headers={"Host": VISITOR})
        self.assertEqual(status, 204)
        self.assertEqual(RecordingHandler.seen[-1]["method"], "OPTIONS")

    def test_client_ip_and_forged_headers_end_to_end(self):
        headers = {"Host": VISITOR, "CF-Connecting-IP": "203.0.113.9",
                   "X-Forwarded-For": "6.6.6.6", "X-Real-IP": "7.7.7.7",
                   "Forwarded": "for=6.6.6.6"}
        status, _ = self.request("GET", headers=headers)
        self.assertEqual(status, 200)
        seen = RecordingHandler.seen[-1]
        self.assertEqual(seen["xff_all"], ["203.0.113.9"])
        self.assertEqual(seen["real_all"], ["203.0.113.9"])
        self.assertIsNone(seen["forwarded"])
        self.assertIsNone(seen["cf"])
        visit_file = visits._visits_path("sem1")
        with open(visit_file, encoding="utf-8") as f:
            recorded = json.loads(f.readlines()[-1])["ip"]
        self.assertEqual(recorded, _hash_ip("203.0.113.9"),
                         "UV 指纹应来自真实访客 IP，而不是恒定的 127.0.0.1")
        self.assertNotEqual(recorded, _hash_ip("127.0.0.1"))

    def test_configured_auth_beats_forged_authorization(self):
        upstream.set_auth("sem1",
                          upstream.normalize_auth("bearer", token="own-token"))
        status, _ = self.request("GET", headers={
            "Host": VISITOR, "Authorization": "Bearer attacker"})
        self.assertEqual(status, 200)
        self.assertEqual(RecordingHandler.seen[-1]["auth"], "Bearer own-token")

    def test_chunked_request_body_is_decoded(self):
        status, body = self.request(
            "POST", headers={"Host": VISITOR, "Transfer-Encoding": "chunked"},
            raw=b"5\r\nhello\r\n0\r\n\r\n")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"GOT:hello")

    def test_unsupported_transfer_encoding_returns_411(self):
        status, _ = self.request(
            "POST", headers={"Host": VISITOR, "Transfer-Encoding": "gzip"})
        self.assertEqual(status, 411)

    def test_no_second_error_after_headers_are_sent(self):
        backend = serve(PartialHandler)
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        proxy.daemon_threads = True
        proxy.entry_id = "sem1"
        proxy.serve_dir = None
        proxy.target_port = backend.server_address[1]
        proxy.target_host = "127.0.0.1"
        proxy.entry_cache = None
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        try:
            sock = socket.create_connection(("%s" % "127.0.0.1",
                                             proxy.server_address[1]),
                                            timeout=5)
            sock.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            sock.close()
            body = data.partition(b"\r\n\r\n")[2]
            self.assertIn(b"PARTIAL", body)
            self.assertNotIn("应用暂时无响应".encode(), body,
                             "响应头发出后不能再拼第二个错误响应")
        finally:
            proxy.shutdown()
            proxy.server_close()
            backend.shutdown()
            backend.server_close()


if __name__ == "__main__":
    unittest.main()
