import json
import os
import pathlib
import shutil
import socket
import tempfile
import time
import unittest
from unittest import mock

from helpers import temp_home
from panweb import models, pins, share, static, store, visits
from panweb.errors import PanwebError
from panweb.forwarder import duplex
from panweb.lifecycle import parse_expires
from panweb.safety import safe_upload_rel_path


class PathTests(unittest.TestCase):
    def test_safe_upload_rel_path(self):
        f = safe_upload_rel_path
        self.assertEqual(f("index.html"), "index.html")
        self.assertEqual(f("assets/app.js"), "assets/app.js")
        self.assertEqual(f("/leading/slash.txt"), "leading/slash.txt")
        for bad in ("../x", "a/../../x", "..", "./..", "....//x/../../../y"):
            with self.assertRaises(PanwebError):
                f(bad)
        self.assertNotIn("..", f("....//state.json").split("/"))

    def test_parse_expires(self):
        f = parse_expires
        self.assertIsNone(f(None))
        self.assertIsNone(f(""))
        now = time.time()
        self.assertGreater(f("1h"), now + 3500)
        self.assertGreater(f("7d"), now + 6 * 86400)
        self.assertIsNone(f(str(now - 10)))
        with self.assertRaises(PanwebError):
            f("nonsense")

    def test_resolve_static_file_blocks_traversal(self):
        root = tempfile.mkdtemp(prefix="panweb-static-")
        try:
            site = os.path.join(root, "site")
            sibling = os.path.join(root, "site-private")
            os.makedirs(site)
            os.makedirs(sibling)
            pathlib.Path(site, "index.html").write_text("INDEX", encoding="utf-8")
            pathlib.Path(site, "a.txt").write_text("A", encoding="utf-8")
            pathlib.Path(site, ".env").write_text("SECRET", encoding="utf-8")
            pathlib.Path(sibling, "secret.txt").write_text("SECRET",
                                                           encoding="utf-8")
            os.symlink("/etc/passwd", os.path.join(site, "leak.txt"))

            self.assertEqual(static.resolve_static_file(site, "/"),
                             (os.path.realpath(os.path.join(site, "index.html")),
                              200))
            self.assertEqual(static.resolve_static_file(site, "/a.txt")[1], 200)
            self.assertEqual(static.resolve_static_file(
                site, "/../site-private/secret.txt")[1], 403)
            self.assertEqual(static.resolve_static_file(
                site, "/%2e%2e/site-private/secret.txt")[1], 403)
            self.assertEqual(static.resolve_static_file(site, "/.env")[1], 404)
            self.assertEqual(static.resolve_static_file(site, "/leak.txt")[1], 403)
        finally:
            shutil.rmtree(root)


class StateTests(unittest.TestCase):
    def test_pin_hash_and_legacy_migration(self):
        with temp_home("panweb-pin-"):
            entry_id = "abc123"
            pins.write_pin(entry_id, "secret99")
            rec = pins.read_pin_record(entry_id)
            self.assertIn("hash", rec)
            self.assertNotIn("secret99", json.dumps(rec))
            self.assertTrue(pins.verify_pin(entry_id, "secret99"))
            self.assertFalse(pins.verify_pin(entry_id, "wrong"))
            stat = os.stat(pins.pin_file_path(entry_id))
            self.assertEqual(stat.st_mode & 0o777, 0o600)

            legacy_id = "legacy1"
            with open(pins.pin_file_path(legacy_id), "w",
                      encoding="utf-8") as f:
                f.write("1234")
            self.assertTrue(pins.verify_pin(legacy_id, "1234"))
            rec = pins.read_pin_record(legacy_id)
            self.assertIn("hash", rec)
            self.assertTrue(pins.verify_pin(legacy_id, "1234"))

    def test_state_lock_is_reentrant(self):
        with temp_home("panweb-lock-"):
            from panweb import runtime
            with store.state_lock():
                with store.state_lock():
                    pass
            self.assertTrue(os.path.exists(runtime.STATE_LOCK_FILE))

    def test_share_url_and_domain(self):
        entry = {"id": "a1", "url": "https://demo.trycloudflare.com",
                 "proxy_port": 4321, "share_token": "tok_123"}
        self.assertEqual(models.entry_share_url(entry, {}),
                         "https://demo.trycloudflare.com/__panweb/share/tok_123")
        domain = {"configured": True, "domain": "demo.example.com",
                  "bound_id": "a1"}
        self.assertEqual(models.entry_share_url(entry, domain),
                         "https://demo.example.com/__panweb/share/tok_123")
        self.assertIsNone(models.entry_share_url(
            dict(entry, share_token=None), {}))
        self.assertIsNone(models.entry_share_url(
            dict(entry, proxy_port=None), {}))

    def test_ensure_share_tokens_only_pages(self):
        with temp_home("panweb-token-"):
            from panweb import runtime
            store.save_json(runtime.STATE_FILE, [
                {"id": "p1", "kind": "pages", "proxy_port": 1234},
                {"id": "a1", "kind": "port", "proxy_port": 2345},
            ])
            share.ensure_share_tokens()
            entries = store.load_state()
            self.assertTrue(entries[0].get("share_token"))
            self.assertFalse(entries[1].get("share_token"))


class VisitTests(unittest.TestCase):
    def test_visit_analytics(self):
        with temp_home("panweb-visits-"):
            visits.log_visit(
                "e1", "/", "1.1.1.1",
                "Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 "
                "Version/17.0 Mobile/15E148 Safari/604.1",
                kind="share", referrer="https://example.com/x?q=1",
                country="CN")
            visits.log_visit(
                "e1", "/", "1.1.1.1",
                "Mozilla/5.0 (Macintosh) Chrome/120.0 Safari/537.36",
                kind="app", country="cn")
            visits.log_visit(
                "e1", "/", "8.8.8.8",
                "Googlebot/2.1 (+http://www.google.com/bot.html)",
                kind="share")
            from panweb import runtime
            with open(os.path.join(runtime.VISITS_DIR, "e1.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "path": "/old",
                                    "ip": "old",
                                    "ua": "Mozilla/5.0 Chrome/119"}) + "\n")
            data = visits.aggregate_visits("e1", 24)
            self.assertEqual(data["share"], 1)
            self.assertEqual(data["app"], 2)
            self.assertEqual(data["uv"], 2)
            self.assertEqual(data["countries"], {"CN": 2})
            self.assertEqual(data["referrers"], {"example.com": 1})
            self.assertEqual(data["browsers"].get("Safari"), 1)
            self.assertEqual(data["browsers"].get("Chrome"), 2)
            self.assertEqual(data["devices"].get("移动端"), 1)
            self.assertEqual(data["devices"].get("桌面端"), 2)
            self.assertGreaterEqual(data["points"][-1]["count"], 1)
            self.assertEqual(visits._clean_country("xx"), "")
            self.assertTrue(visits._is_bot("Googlebot/2.1"))

    def test_visit_notifier(self):
        with temp_home("panweb-notify-"):
            from panweb import runtime
            store.ensure_private_dirs()
            store.save_json(runtime.STATE_FILE, [{
                "id": "e1", "name": "演示页", "proxy_port": 1234,
                "share_token": "tok", "url": "https://x.trycloudflare.com"}])
            notified = []
            with mock.patch.object(visits, "notify_macos",
                                   lambda message, subtitle="":
                                   notified.append((message, subtitle))):
                n = visits.VisitNotifier()
                n.poll_once()  # 首次只记 offset，不回放历史
                store.save_json(runtime.META_FILE, {
                    "notify_visits": True,
                    "owner_grace": {"e1": time.time() + 60},
                })
                visits.log_visit(
                    "e1", "/__panweb/share/tok", "9.9.9.9",
                    "Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 "
                    "Version/17.0 Mobile/15E148 Safari/604.1",
                    kind="share", country="CN")
                n.poll_once()
                snap = n.snapshot()
                self.assertEqual(len(snap), 1)
                self.assertEqual(snap[0]["kind"], "share")
                self.assertEqual(snap[0]["name"], "演示页")
                self.assertEqual(len(notified), 0)  # 控制台自己打开，不发通知
                store.save_json(runtime.META_FILE, {"notify_visits": True})
                visits.log_visit(
                    "e1", "/", "8.8.8.8",
                    "Mozilla/5.0 (Macintosh) Chrome/120 Safari/537.36",
                    kind="app", country="US")
                n.poll_once()
                self.assertEqual(len(n.snapshot()), 2)
                self.assertEqual(len(notified), 1)
                self.assertIn("演示页", notified[0][0])
                n.poll_once()
                self.assertEqual(len(notified), 1)


class PipeTests(unittest.TestCase):
    def test_duplex_returns_both_sockets(self):
        """隧道每来一个访客就调用一次；两端 socket 必须被关回，否则按访客数漏 fd。"""
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        client = socket.create_connection(("127.0.0.1",
                                           listener.getsockname()[1]))
        peer, _ = listener.accept()
        listener.close()
        client.settimeout(0.3)
        peer.settimeout(0.3)
        try:
            client.sendall(b"ping")
            duplex(client, peer)
            self.assertTrue(client._closed, "客户端 socket 未归还")
            self.assertTrue(peer._closed, "回源 socket 未归还")
        finally:
            for sock in (client, peer):
                try:
                    sock.close()
                except OSError:
                    pass


class ShareNoteTests(unittest.TestCase):
    """分享页上那句话说的是访客会遇到什么，不是本机内部构造。"""

    def entry(self, **over):
        base = {"id": "n1", "name": "演示", "kind": "port", "target": 3000,
                "url": "https://demo.trycloudflare.com", "proxy_port": 4321,
                "share_token": "tok"}
        base.update(over)
        return base

    def page(self, entry, pin=False):
        return share.build_share_page(
            entry, "https://demo.trycloudflare.com/__panweb/share/tok",
            token="tok", pin=pin)

    def test_blocked_check_says_so_and_downgrades_status(self):
        entry = self.entry(check={"verdict": "blocked", "summary": "公网没有响应",
                                  "signals": [{"code": "unreachable",
                                               "label": "公网没有响应",
                                               "severity": "bad"}]})
        page = self.page(entry)
        self.assertIn("还没准备好", page)
        self.assertIn("主人自检未通过", page)
        self.assertNotIn(">在线<", page)

    def test_own_account_is_explained(self):
        entry = self.entry(check={"verdict": "warn", "summary": "应用自己也要登录",
                                  "signals": [{"code": "app_login",
                                               "label": "应用自己也要登录",
                                               "severity": "warn"}]})
        page = self.page(entry, pin=True)
        self.assertIn("它自己的账号", page)
        self.assertIn("账号请向主人索取", page)

    def test_injected_credentials_tell_visitor_not_to_login(self):
        page = self.page(self.entry(auth_kind="bearer"))
        self.assertIn("主人已经替你带上", page)

    def test_no_check_means_no_note(self):
        page = self.page(self.entry())
        self.assertNotIn('<div class="note">', page)
        self.assertIn(">在线<", page)

    def test_note_is_escaped(self):
        entry = self.entry(check={"verdict": "warn", "summary": "<script>x</script>",
                                  "signals": []})
        self.assertNotIn("<script>x</script>", self.page(entry))

    def test_core_list_drops_auth_tag_without_the_secret(self):
        with temp_home("panweb-authtag-"):
            from panweb import entries, runtime, upstream
            store.save_json(runtime.STATE_FILE, [
                {"id": "x1", "name": "a", "kind": "port", "target": 1,
                 "url": "https://x.trycloudflare.com", "auth_kind": "bearer"}])
            self.assertNotIn("auth_kind", entries.core_list()[0])
            upstream.set_auth("x1", upstream.normalize_auth("bearer", "tk"))
            self.assertEqual(entries.core_list()[0]["auth_kind"], "bearer")


if __name__ == "__main__":
    unittest.main()
