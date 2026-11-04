import time
import unittest

from helpers import temp_home
from panweb import last_deploy, store, ui_actions, visits
from panweb.entries import core_stop
from panweb.lifecycle import sweep_expired
from panweb.publish_defaults import remember_publish
from panweb.publish_options import resolve_options


class SnapshotEntryTests(unittest.TestCase):
    def test_snapshot_keeps_display_fields_without_secrets(self):
        entry = {
            "id": "a1", "name": "demo", "title": "演示站", "kind": "port",
            "port": 3000, "proxy_port": 5100, "pinned": True, "pin": "1234",
            "pin_hash": "$argon2id$x", "share_token": "tok",
            "url": "https://x.trycloudflare.com", "expires_at": 2000000000,
            "started": "2026-01-01 00:00:00",
        }
        snap = last_deploy.snapshot_entry(
            entry, reason="user", now=time.time(), domain={},
            visits={"total": 3, "uv": 2, "last": 1})
        self.assertIsInstance(snap["pinned"], bool)
        self.assertIs(snap["pinned"], True)
        self.assertNotIn("pin", snap)
        self.assertNotIn("pin_hash", snap)
        self.assertNotIn("share_token", snap)
        self.assertNotIn("proxy_port", snap)
        self.assertEqual(snap["port"], 3000)
        self.assertEqual(snap["pv"]["uv"], 2)
        self.assertTrue(snap["expires_text"].startswith("剩余"))


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-lastdeploy-")
        self.home = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        store.ensure_private_dirs()

    def test_dedup_by_target_and_cap(self):
        for i in range(6):
            last_deploy.remember_last({"id": "p%d" % i, "name": "n%d" % i,
                                       "kind": "port", "port": 7000 + i,
                                       "url": "https://e%d.example" % i})
        snaps = last_deploy.load_snapshots()
        self.assertEqual(len(snaps), last_deploy.MAX_SNAPSHOTS)
        self.assertEqual([s["id"] for s in snaps], ["p5", "p4", "p3", "p2", "p1"])
        last_deploy.remember_last({"id": "p0b", "name": "again", "kind": "port",
                                   "port": 7000, "url": "https://e0.example"})
        snaps = last_deploy.load_snapshots()
        self.assertEqual(snaps[0]["id"], "p0b")
        self.assertNotIn("p0", [s["id"] for s in snaps])
        self.assertEqual(len(snaps), last_deploy.MAX_SNAPSHOTS)

    def test_active_target_hides_stale_snapshot(self):
        last_deploy.remember_last({"id": "s1", "name": "demo", "kind": "port",
                                   "port": 8123})
        active = [{"id": "n1", "name": "demo", "kind": "port", "port": 8123}]
        self.assertEqual(last_deploy.load_snapshots(active), [])
        self.assertEqual(len(last_deploy.load_snapshots()), 1)

    def test_find_snapshot(self):
        last_deploy.remember_last({"id": "s2", "name": "x", "kind": "pages",
                                   "folder": "/tmp/site"})
        found = last_deploy.find_snapshot("s2")
        self.assertEqual(found["id"], "s2")
        self.assertIsNone(last_deploy.find_snapshot("nope"))

    def test_stop_records_snapshot_before_visits_are_deleted(self):
        visits.log_visit("s1", "/", "203.0.113.9",
                         "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")
        store.save_state([{
            "id": "s1", "name": "demo", "kind": "port", "port": 9000,
            "proxy_port": 5001, "url": "https://x.trycloudflare.com",
            "share_token": "tok", "pinned": True, "pin": "1234",
            "started": "2026-01-01 00:00:00",
        }])
        core_stop("s1", source="cli")
        self.assertEqual(store.load_state(), [])
        snap = last_deploy.load_snapshots()[0]
        self.assertEqual(snap["stop_reason"], "user")
        self.assertGreaterEqual(snap["pv"]["total"], 1)
        self.assertTrue(snap["share_url"].endswith("/__panweb/share/tok"))

    def test_expired_reason_is_kept(self):
        store.save_state([{
            "id": "e1", "name": "old", "kind": "pages", "folder": "/tmp/old",
            "target": "/tmp/old", "expires_at": 1,
            "url": "https://x.trycloudflare.com",
        }])
        sweep_expired()
        snap = last_deploy.load_snapshots()[0]
        self.assertEqual(snap["stop_reason"], "expired")
        self.assertEqual(snap["expires_text"], "已到期")

    def test_republish_config_comes_from_backend_memory(self):
        remember_publish(expires="3d", share=False)
        snap = last_deploy.snapshot_entry({
            "id": "r1", "name": "demo", "kind": "port", "port": 8123,
            "url": "https://x.trycloudflare.com"})
        opts = resolve_options(port=snap["port"], name=snap["name"],
                               expires=None, share=None)
        self.assertEqual(opts["port"], 8123)
        self.assertEqual(opts["expires"], "3d")
        self.assertEqual(opts["sources"]["expires"], "defaults")
        self.assertIs(opts["share"], False)
        self.assertEqual(opts["sources"]["share"], "defaults")

    def test_history_falls_back_to_snapshot(self):
        store.save_state([{
            "id": "s3", "name": "demo", "kind": "pages", "folder": "/tmp/site",
            "url": "https://x.trycloudflare.com",
            "expires_at": time.time() + 3600,
            "started": "2026-01-01 00:00:00",
        }])
        core_stop("s3", source="ui")

        class Handler:
            path = "/api/history?id=s3&limit=10"

            def send_json(self, payload):
                self.payload = payload

        handler = Handler()
        ui_actions.handle_get(handler, "/api/history")
        detail = handler.payload["data"]["detail"]
        self.assertTrue(detail["from_snapshot"])
        self.assertEqual(detail["stop_reason"], "user")
        self.assertTrue(detail["stopped_at"])
        self.assertTrue(detail["expires_text"].startswith("剩余"))
        self.assertIsInstance(detail["pin_required"], bool)
        self.assertNotIn("pin", detail)


if __name__ == "__main__":
    unittest.main()
