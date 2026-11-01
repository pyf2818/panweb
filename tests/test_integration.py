import os
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import free_port, temp_home
from panweb import runtime, store
from panweb.pins import write_pin
from panweb.processes import port_listening, stop_process
from panweb.publish import _spawn_proxy


class BackendHandler(BaseHTTPRequestHandler):
    server_version = "demo-backend/1.0"

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        body = b"HELLO-FROM-BACKEND"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ProxySpawnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = temp_home("panweb-integration-")
        cls.home = cls.ctx.__enter__()
        store.ensure_private_dirs()
        cls.backend = ThreadingHTTPServer(("127.0.0.1", 0), BackendHandler)
        cls.backend.daemon_threads = True
        cls.backend_port = cls.backend.server_address[1]
        cls.backend_thread = threading.Thread(
            target=cls.backend.serve_forever, daemon=True)
        cls.backend_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.ctx.__exit__(None, None, None)

    def request(self, port, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        result = (resp.status, dict(resp.getheaders()), data)
        conn.close()
        return result

    def test_spawned_proxy_forwards_and_serves_share(self):
        entry_id = "itest1"
        proxy_port = free_port()
        store.save_json(runtime.STATE_FILE, [{
            "id": entry_id, "name": "集成测试", "kind": "port",
            "target": self.backend_port, "proxy_port": proxy_port,
            "share_token": "tok_itest",
            "url": "https://itest.trycloudflare.com"}])
        write_pin(entry_id, None)
        proc = _spawn_proxy(proxy_port, entry_id,
                            target_port=self.backend_port)
        self.assertIsNotNone(proc)
        try:
            deadline = time.time() + 8
            while time.time() < deadline and not port_listening(proxy_port):
                time.sleep(0.1)
            self.assertTrue(port_listening(proxy_port), "代理未启动")
            status, _, body = self.request(proxy_port, "GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(b"HELLO-FROM-BACKEND", body)
            status, _, body = self.request(
                proxy_port, "GET", "/__panweb/share/tok_itest")
            self.assertEqual(status, 200)
            self.assertIn("集成测试", body.decode("utf-8"))
            self.assertIn('property="og:title"', body.decode("utf-8"))
        finally:
            stop_process(proc, ("--internal-proxy",))
            store.save_json(runtime.STATE_FILE, [])

    def test_spawned_proxy_pin_gate(self):
        entry_id = "itest2"
        proxy_port = free_port()
        store.save_json(runtime.STATE_FILE, [{
            "id": entry_id, "name": "口令测试", "kind": "port",
            "target": self.backend_port, "proxy_port": proxy_port,
            "share_token": "tok_pin",
            "url": "https://pin.trycloudflare.com"}])
        proc = _spawn_proxy(proxy_port, entry_id,
                            target_port=self.backend_port, pin="secret99")
        self.assertIsNotNone(proc)
        try:
            deadline = time.time() + 8
            while time.time() < deadline and not port_listening(proxy_port):
                time.sleep(0.1)
            self.assertTrue(port_listening(proxy_port), "代理未启动")
            status, headers, _ = self.request(
                proxy_port, "GET", "/")
            self.assertEqual(status, 302)
            self.assertIn("/__panweb/login", headers.get("Location", ""))
            status, headers, _ = self.request(
                proxy_port, "POST", "/__panweb/login",
                body="pw=secret99&next=/",
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(status, 302)
            cookie = (headers.get("Set-Cookie") or "").split(";")[0]
            self.assertIn("panweb_auth=", cookie)
            status, _, body = self.request(proxy_port, "GET", "/",
                                           headers={"Cookie": cookie})
            self.assertEqual(status, 200)
            self.assertIn(b"HELLO-FROM-BACKEND", body)
        finally:
            stop_process(proc, ("--internal-proxy",))
            store.save_json(runtime.STATE_FILE, [])


if __name__ == "__main__":
    unittest.main()
