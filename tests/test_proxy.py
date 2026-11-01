import json
import os
import pathlib
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from helpers import temp_home
from panweb import pins, runtime, store
from panweb.proxy import ProxyHandler


class ProxyShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = temp_home("panweb-share-")
        cls.home = cls.ctx.__enter__()
        store.ensure_private_dirs()
        cls.site = os.path.join(cls.home, "site")
        os.makedirs(cls.site)
        pathlib.Path(cls.site, "index.html").write_text("INDEX",
                                                        encoding="utf-8")
        cls.entry = {
            "id": "abc123", "name": "演示 <页面>", "kind": "pages",
            "target": cls.site, "proxy_port": 12345,
            "share_token": "tok_123", "url": "https://demo.trycloudflare.com",
            "started": "2026-10-31 12:00", "desc": "给客户看的版本",
            "expires_at": None,
        }
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        cls.server.daemon_threads = True
        cls.server.entry_id = "abc123"
        cls.server.serve_dir = cls.site
        cls.server.target_port = None
        cls.server.target_host = "127.0.0.1"
        cls.server.entry_cache = None
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        pins.write_pin("abc123", None)
        store.save_json(runtime.STATE_FILE, [dict(self.entry)])
        self.server.entry_cache = None
        visit_file = os.path.join(runtime.VISITS_DIR, "abc123.jsonl")
        if os.path.exists(visit_file):
            os.remove(visit_file)

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        result = (resp.status, dict(resp.getheaders()),
                  data.decode("utf-8", "replace"))
        conn.close()
        return result

    def test_share_page_renders_and_validates_token(self):
        status, headers, body = self.request("GET",
                                             "/__panweb/share/tok_123")
        self.assertEqual(status, 200)
        self.assertIn('property="og:title"', body)
        self.assertIn("演示 &lt;页面&gt;", body)
        self.assertIn("给客户看的版本", body)
        self.assertNotIn("演示 <页面>", body)
        self.assertNotRegex(body, r"__[A-Z_]+__")
        self.assertIn('property="og:url" content="https://', body)
        self.assertIn("/__panweb/share/tok_123", body)
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertIn("打开应用", body)
        self.assertEqual(self.request("GET", "/__panweb/share/wrong")[0], 404)
        self.assertEqual(self.request("GET", "/__panweb/share")[0], 404)
        visits = pathlib.Path(runtime.VISITS_DIR, "abc123.jsonl").read_text(
            encoding="utf-8").strip().splitlines()
        rec = json.loads(visits[-1])
        self.assertEqual(rec["kind"], "share")
        self.assertEqual(rec["path"], "/__panweb/share")
        self.assertNotIn("tok_123", visits[-1])

    def test_pin_login_from_share_page(self):
        pins.write_pin("abc123", "secret99")
        status, _, body = self.request("GET", "/__panweb/share/tok_123")
        self.assertEqual(status, 200)
        self.assertIn("<form", body)
        status, _, body = self.request(
            "POST", "/__panweb/login?share=tok_123",
            body="pw=bad&next=/",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 200)
        self.assertIn("口令不对", body)
        self.assertNotIn("panweb_auth=", body)
        status, headers, _ = self.request(
            "POST", "/__panweb/login?share=tok_123",
            body="pw=secret99&next=/",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 302)
        self.assertEqual(headers.get("Location"), "/")
        cookie = (headers.get("Set-Cookie") or "").split(";")[0]
        self.assertIn("panweb_auth=", cookie)
        status, _, body = self.request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertEqual(body, "INDEX")
        self.assertEqual(self.request("GET", "/")[0], 302)

    def test_expired_share_and_root(self):
        entry = dict(self.entry, expires_at=time.time() - 10)
        store.save_json(runtime.STATE_FILE, [entry])
        self.server.entry_cache = None
        status, _, body = self.request("GET", "/__panweb/share/tok_123")
        self.assertEqual(status, 200)
        self.assertIn("链接已过期", body)
        self.assertNotIn("打开应用", body)
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 410)
        self.assertIn("已过期", body)


if __name__ == "__main__":
    unittest.main()
