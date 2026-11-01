import json
import os
import shutil
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from helpers import ROOT, temp_home
from panweb import runtime, store
from panweb.publish import core_publish
from panweb.ui_server import UiHandler


class UiSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = temp_home("panweb-ui-")
        cls.home = cls.ctx.__enter__()
        cls.saved_env = (os.environ.pop("PANWEB_LICENSE_PUBKEY", None),
                         os.environ.pop("PANWEB_LICENSE_OFF", None))
        store.ensure_private_dirs()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), UiHandler)
        cls.server.daemon_threads = True
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        pub, off = cls.saved_env
        if pub is not None:
            os.environ["PANWEB_LICENSE_PUBKEY"] = pub
        if off is not None:
            os.environ["PANWEB_LICENSE_OFF"] = off
        cls.ctx.__exit__(None, None, None)

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data

    def test_rejects_foreign_host_and_origin(self):
        good = {"Host": "127.0.0.1:%d" % self.port}
        self.assertEqual(self.request("GET", "/", headers={
            "Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={
            **good, "Origin": "http://evil.example"})[0], 403)

    def test_requires_json_content_type_and_valid_json(self):
        good = {"Host": "127.0.0.1:%d" % self.port}
        status, data = self.request("POST", "/api/stop",
                                    body='{"target":"all"}',
                                    headers={**good,
                                             "Content-Type": "text/plain"})
        self.assertFalse(json.loads(data)["ok"])
        status, data = self.request("POST", "/api/stop", body="not-json",
                                    headers={**good,
                                             "Content-Type": "application/json"})
        self.assertFalse(json.loads(data)["ok"])
        self.assertEqual(json.loads(data)["error"]["type"], "invalid_json")

    def test_console_port_is_not_publishable(self):
        old = os.environ.get("PANWEB_CLOUDFLARED")
        os.environ["PANWEB_CLOUDFLARED"] = shutil.which("false") or "/usr/bin/false"
        try:
            with self.assertRaises(Exception) as ctx:
                core_publish(self.port, "console")
            self.assertEqual(getattr(ctx.exception, "err_type", ""),
                             "internal_port")
        finally:
            if old is None:
                os.environ.pop("PANWEB_CLOUDFLARED", None)
            else:
                os.environ["PANWEB_CLOUDFLARED"] = old

    def test_state_and_license_shape(self):
        good = {"Host": "127.0.0.1:%d" % self.port}
        status, data = self.request("GET", "/api/state", headers=good)
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertTrue(payload["ok"], payload)
        self.assertIn("apps", payload["data"])
        self.assertEqual(payload["data"]["license"]["mode"], "development")
        status, data = self.request("GET", "/api/license", headers=good)
        self.assertTrue(json.loads(data)["data"]["can_publish"])

    def test_enable_share_for_existing_proxy_entry(self):
        good = {"Host": "127.0.0.1:%d" % self.port,
                "Content-Type": "application/json"}
        entry = {"id": "share01", "name": "旧应用", "kind": "pages",
                 "target": os.path.join(self.home, "site"), "proxy_port": 43210,
                 "url": "https://old.trycloudflare.com",
                 "started": "2026-10-31 12:00"}
        store.save_json(runtime.STATE_FILE, [entry])
        status, data = self.request("POST", "/api/share", body='{"id":"share01"}',
                                    headers=good)
        payload = json.loads(data)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["data"]["share_url"].endswith(
            "/__panweb/share/" + store.load_state()[0]["share_token"]))
        self.assertTrue(store.load_state()[0]["share_token"])
        store.save_json(runtime.STATE_FILE, [])


    def test_compat_route_keeps_the_secret_out_of_responses(self):
        good = {"Host": "127.0.0.1:%d" % self.port,
                "Content-Type": "application/json"}
        entry = {"id": "compat01", "name": "兼容测试", "kind": "port",
                 "target": 9, "proxy_port": 43211, "url": "http://127.0.0.1:9",
                 "started": "2026-10-31 12:00"}
        store.save_json(runtime.STATE_FILE, [entry])
        status, data = self.request(
            "POST", "/api/compat",
            body='{"id":"compat01","auth_kind":"bearer","token":"top-secret"}',
            headers=good)
        payload = json.loads(data)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["data"]["auth"]["kind"], "bearer")
        self.assertNotIn(b"top-secret", data)
        self.assertEqual(store.load_state()[0]["auth_kind"], "bearer")
        # 注入换行的头值会被挡在规范化之外，不会写进 secrets
        status, data = self.request(
            "POST", "/api/compat",
            body='{"id":"compat01","auth_kind":"header",'
                 '"header_name":"X-A","header_value":"a\\r\\nX-B: 1"}',
            headers=good)
        payload = json.loads(data)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["error"]["type"], "invalid_argument")
        status, data = self.request(
            "POST", "/api/compat",
            body='{"id":"compat01","host_mode":"tunnel"}', headers=good)
        self.assertEqual(json.loads(data)["data"]["host_mode"], "tunnel")
        self.assertEqual(store.load_state()[0]["host_mode"], "tunnel")
        status, data = self.request(
            "GET", "/api/compat?id=compat01", headers=good)
        payload = json.loads(data)
        self.assertNotIn(b"top-secret", data)
        self.assertEqual(payload["data"]["auth"]["label"], "Bearer 令牌")
        store.save_json(runtime.STATE_FILE, [])

    def test_check_route_persists_a_verdict(self):
        good = {"Host": "127.0.0.1:%d" % self.port,
                "Content-Type": "application/json"}
        store.save_json(runtime.STATE_FILE, [{
            "id": "check01", "name": "自检测试", "kind": "port", "target": 9,
            "url": "http://127.0.0.1:9", "started": "2026-10-31 12:00"}])
        status, data = self.request("POST", "/api/check",
                                    body='{"id":"check01"}', headers=good)
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["data"]["verdict"], "blocked")
        self.assertIn("unreachable", [s["code"]
                                      for s in payload["data"]["signals"]])
        self.assertEqual(store.load_state()[0]["check"]["verdict"], "blocked")
        status, data = self.request("POST", "/api/check",
                                    body='{"id":"missing"}', headers=good)
        self.assertFalse(json.loads(data)["ok"])
        store.save_json(runtime.STATE_FILE, [])


if __name__ == "__main__":
    unittest.main()
