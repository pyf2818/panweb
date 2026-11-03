import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.parse
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest import mock

from helpers import FAKE_PTY, ROOT, make_executable, temp_home
from panweb import agents, runtime, store, term
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

    def test_folder_picker_lists_directories_only_for_local_hosts(self):
        good = {"Host": "127.0.0.1:%d" % self.port}
        tree = os.path.join(self.home, "pick-me")
        os.makedirs(os.path.join(tree, "dist"))
        os.makedirs(os.path.join(tree, ".cache"))
        with open(os.path.join(tree, "index.html"), "w", encoding="utf-8") as f:
            f.write("<p>x</p>")
        status, data = self.request(
            "GET", "/api/folders?path=" + urllib.parse.quote(tree), headers=good)
        payload = json.loads(data)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual([e["name"] for e in payload["data"]["entries"]], ["dist"])
        self.assertEqual(payload["data"]["parent"], os.path.realpath(self.home))
        # 没有本机 Host 就一份目录清单都拿不到
        self.assertEqual(self.request("GET", "/api/folders", headers={
            "Host": "evil.example"})[0], 403)
        status, data = self.request("GET", "/api/folders?path=/nope/nope",
                                    headers=good)
        self.assertFalse(json.loads(data)["ok"])
        self.assertEqual(json.loads(data)["error"]["type"], "not_found")

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

    def test_term_routes_replaced_the_chat_panel(self):
        """旧的「一次性对话」接口拿掉了，换成真终端；坏输入要说清而不是 500。"""
        good = {"Host": "127.0.0.1:%d" % self.port,
                "Content-Type": "application/json"}
        agents = json.loads(self.request("GET", "/api/term/agents",
                                         headers=good)[1])["data"]["agents"]
        self.assertEqual({a["id"] for a in agents},
                         {"claude", "codex", "opencode"})
        self.assertEqual(self.request("GET", "/api/agent/agents",
                                      headers=good)[0], 404)
        body = json.loads(self.request("POST", "/api/term/open",
                                       body='{"agent":"sh"}',
                                       headers=good)[1])
        self.assertEqual(body["error"]["type"], "not_found")
        # 推流前先查会话：查不到就回 JSON，不会挂一条没人收尾的流
        body = json.loads(self.request("GET", "/api/term/output?id=nope",
                                       headers=good)[1])
        self.assertEqual(body["error"]["type"], "not_found")

    def test_term_open_and_close_over_http(self):
        """真的通过 HTTP 开一个伪终端：列得出来、关得掉、坏目录说得清。"""
        bin_dir = tempfile.mkdtemp(prefix="panweb-uipty-")
        self.addCleanup(shutil.rmtree, bin_dir, True)
        make_executable(bin_dir, "fake-agent", FAKE_PTY)
        good = {"Host": "127.0.0.1:%d" % self.port,
                "Content-Type": "application/json"}
        terminals = {"fake": {"bin": "fake-agent", "name": "Fake Agent",
                              "argv": (), "note": "测试用"}}
        with mock.patch.dict(agents.TERMINALS, terminals, clear=True), \
             mock.patch.dict(os.environ, {"PATH": bin_dir}):
            payload = json.loads(self.request(
                "POST", "/api/term/open",
                body='{"agent":"fake","cwd":"%s","cols":80,"rows":20}' % bin_dir,
                headers=good)[1])
            self.assertTrue(payload["ok"], payload)
            sid = payload["data"]["id"]
            self.assertEqual((payload["data"]["cols"],
                              payload["data"]["rows"]), (80, 20))
            self.addCleanup(lambda: self.request(
                "POST", "/api/term/close", body='{"id":"%s"}' % sid,
                headers=good))
            listed = json.loads(self.request("GET", "/api/term/sessions",
                                             headers=good)[1])["data"]["sessions"]
            self.assertEqual([s["id"] for s in listed], [sid])
            bad = json.loads(self.request(
                "POST", "/api/term/open",
                body='{"agent":"fake","cwd":"/definitely/not/here"}',
                headers=good)[1])
            self.assertEqual(bad["error"]["type"], "invalid_argument")
            closed = json.loads(self.request(
                "POST", "/api/term/close", body='{"id":"%s"}' % sid,
                headers=good)[1])
            self.assertTrue(closed["data"]["closed"])
            left = json.loads(self.request("GET", "/api/term/sessions",
                                           headers=good)[1])["data"]["sessions"]
            self.assertEqual(left, [])


if __name__ == "__main__":
    unittest.main()
