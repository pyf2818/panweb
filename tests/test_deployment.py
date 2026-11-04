import json
import unittest

from panweb.deployment import build_detail, link_history, remaining_text


def sample_entry(**over):
    entry = {
        "id": "demo-1",
        "name": "demo",
        "title": "演示站",
        "kind": "port",
        "port": 3000,
        "proxy_port": 43000,
        "url": "https://new.example.trycloudflare.com",
        "share_token": "tok",
        "pinned": True,
        "expires_at": None,
        "started": "2026-11-04 20:10",
        "pin": "top-secret-99",
    }
    entry.update(over)
    return entry


def url_change(ts, before, after):
    return {"type": "url_change", "ts": ts,
            "details": {"url_before": before, "url_after": after}}


class LinkHistoryTests(unittest.TestCase):
    def test_current_and_expired_links_are_ordered_and_unique(self):
        entry = sample_entry()
        events = [
            url_change(300, "https://b.example", entry["url"]),
            url_change(200, "https://a.example", "https://b.example"),
            url_change(100, "https://a.example", "https://a.example"),
            {"type": "restart", "ts": 50, "details": {}},
        ]
        links = link_history(entry, events)
        self.assertEqual([x["url"] for x in links], [
            entry["url"], "https://b.example", "https://a.example"])
        self.assertEqual(links[0]["status"], "current")
        self.assertTrue(all(x["status"] == "expired" for x in links[1:]))

    def test_only_url_change_events_are_used(self):
        entry = sample_entry()
        links = link_history(entry, [
            {"type": "pin_change", "ts": 10,
             "details": {"url_before": "https://ignored.example"}},
        ])
        self.assertEqual([x["url"] for x in links], [entry["url"]])

    def test_empty_entry_has_no_links(self):
        self.assertEqual(link_history({}, [url_change(1, "https://x", "https://y")]), [])
        self.assertEqual(link_history(None, []), [])

    def test_current_link_follows_bound_domain(self):
        entry = sample_entry()
        domain = {"configured": True, "domain": "app.example.com",
                  "bound_id": entry["id"]}
        links = link_history(entry, [url_change(10, "https://old", entry["url"])],
                             domain)
        self.assertEqual(links[0]["url"], "https://app.example.com")
        self.assertEqual(links[0]["status"], "current")
        self.assertIn(entry["url"], [x["url"] for x in links[1:]])


class DetailTests(unittest.TestCase):
    def test_empty_selection_returns_none(self):
        self.assertIsNone(build_detail(None, []))
        self.assertIsNone(build_detail({}, []))

    def test_detail_exposes_pin_state_as_boolean_only(self):
        entry = sample_entry()
        detail = build_detail(entry, [url_change(10, "https://old", entry["url"])],
                              visits={"total": 12, "uv": 7, "last": 1700000000})
        self.assertTrue(detail["pin_required"])
        self.assertNotIn("pin", detail)
        self.assertNotIn("top-secret-99", json.dumps(detail, ensure_ascii=False))
        self.assertFalse(build_detail(sample_entry(pinned=False), [])["pin_required"])
        self.assertEqual(detail["links"][1]["status"], "expired")

    def test_fields_cover_links_expiry_visits_rebuilds(self):
        entry = sample_entry(pinned=False)
        now = 1_000_000
        entry["expires_at"] = now + 90_000
        events = [url_change(400, "https://old-1", entry["url"]),
                  {"type": "restart", "ts": 300, "details": {}},
                  {"type": "stop", "ts": 200, "details": {}}]
        detail = build_detail(entry, events, visits={"total": 3, "uv": 2,
                                                     "last": 999999}, now=now)
        self.assertFalse(detail["pin_required"])
        self.assertEqual(detail["expires_text"], "剩余 1 天 1 小时")
        self.assertEqual(detail["published_at"], "2026-11-04 20:10")
        self.assertEqual(detail["rebuild_count"], 2)
        self.assertEqual(detail["last_rebuild_at"], 400)
        self.assertEqual(detail["source"], "127.0.0.1:3000")
        self.assertTrue(detail["visits"]["available"])
        self.assertEqual(detail["visits"]["total"], 3)
        self.assertTrue(detail["share_url"].endswith("/__panweb/share/tok"))

    def test_direct_publish_has_no_stats_and_unknown_publish_time(self):
        entry = sample_entry(proxy_port=None, started=None)
        detail = build_detail(entry, [])
        self.assertFalse(detail["visits"]["available"])
        self.assertIsNone(detail["published_at"])
        self.assertIsNone(detail["share_url"])
        self.assertEqual(detail["expires_text"], "永久")
        self.assertEqual(detail["rebuild_count"], 0)
        self.assertIsNone(detail["last_rebuild_at"])

    def test_remaining_text(self):
        now = 1_000_000
        self.assertEqual(remaining_text(None, now), "永久")
        self.assertEqual(remaining_text(now - 1, now), "已到期")
        self.assertEqual(remaining_text(now + 60, now), "剩余 1 分钟")
        self.assertEqual(remaining_text(now + 3600, now), "剩余 1 小时 0 分")
        self.assertEqual(remaining_text("bad", now), "未知")


if __name__ == "__main__":
    unittest.main()
