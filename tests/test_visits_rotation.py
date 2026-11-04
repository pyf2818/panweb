"""访问日志按天分文件：访问越多统计不能反而变小。"""
import json
import os
import time
import unittest
from unittest import mock

from helpers import temp_home
from panweb import runtime, store, visits

UA = "Mozilla/5.0 (Macintosh) Chrome/120 Safari/537.36"


class VisitsRotationTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-visits-rot-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        os.makedirs(runtime.VISITS_DIR, exist_ok=True)

    def _write(self, entry_id, count, ts=None):
        when = time.time() if ts is None else ts
        path = visits._visits_path(entry_id, when)
        rec = json.dumps({"ts": when, "path": "/", "ip": "ip", "kind": "app",
                          "device": "桌面端", "browser": "Chrome"})
        with open(path, "a", encoding="utf-8") as f:
            f.write((rec + "\n") * count)

    def test_log_visit_uses_daily_file(self):
        visits.log_visit("e1", "/", "1.1.1.1", UA)
        names = os.listdir(runtime.VISITS_DIR)
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r"^e1-\d{8}\.jsonl$")
        self.assertEqual(visits.aggregate_visits("e1", 24)["total"], 1)

    def test_total_does_not_shrink_past_two_megabytes(self):
        self._write("e1", 20000)
        self.assertGreater(os.path.getsize(visits._visits_path("e1")),
                           2 * 1024 * 1024)
        data = visits.aggregate_visits("e1", 24)
        self.assertEqual(data["total"], 20000)
        self.assertEqual(data["uv"], 1)

    def test_total_grows_monotonically_with_appends(self):
        self._write("e1", 5)
        self.assertEqual(visits.aggregate_visits("e1", 24)["total"], 5)
        self._write("e1", 5)
        self.assertEqual(visits.aggregate_visits("e1", 24)["total"], 10)

    def test_records_split_by_day(self):
        now = time.time()
        self._write("e1", 1, now - 86400)
        self._write("e1", 1, now)
        names = [n for n in os.listdir(runtime.VISITS_DIR)
                 if n.endswith(".jsonl")]
        self.assertEqual(len(names), 2)
        self.assertEqual(visits.aggregate_visits("e1", 48)["total"], 2)

    def test_legacy_single_file_still_counted(self):
        with open(os.path.join(runtime.VISITS_DIR, "e1.jsonl"), "w",
                  encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "path": "/",
                                "ip": "old"}) + "\n")
        self.assertEqual(visits.aggregate_visits("e1", 24)["total"], 1)

    def test_recent_list_is_bounded(self):
        self._write("e1", 40)
        data = visits.aggregate_visits("e1", 24, recent=5)
        self.assertEqual(len(data["recent"]), 5)


class NotifierRotationTests(unittest.TestCase):
    def test_notifier_follows_new_day_file(self):
        with temp_home("panweb-visits-notify-"):
            store.ensure_private_dirs()
            store.save_json(runtime.STATE_FILE, [{
                "id": "e1", "name": "演示", "url": "https://x.trycloudflare.com"}])
            notifier = visits.VisitNotifier()
            day1 = time.time()
            with mock.patch.object(visits, "notify_macos"), \
                    mock.patch.object(visits.time, "time", return_value=day1):
                visits.log_visit("e1", "/", "1.1.1.1", UA)
                notifier.poll_once()  # 首次只记游标，不回放历史
                visits.log_visit("e1", "/", "2.2.2.2", UA)
                notifier.poll_once()
                self.assertEqual(len(notifier.snapshot()), 1)
            with mock.patch.object(visits.time, "time",
                                   return_value=day1 + 86400):
                visits.log_visit("e1", "/", "3.3.3.3", UA)
                notifier.poll_once()
                self.assertEqual(len(notifier.snapshot()), 2)


if __name__ == "__main__":
    unittest.main()
