"""F3 事件流：旁路写入、隐私白名单、tail 读取、CLI/API 与关键埋点。"""
import contextlib
import io
import json
import os
import threading
import time
import unittest
import urllib.parse
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

from helpers import temp_home
from panweb import events, runtime, store
from panweb.history_cli import cmd_history
from panweb.entries import core_stop
from panweb.lifecycle import sweep_expired
from panweb.ui_server import UiHandler


def _raw_events():
    parts = []
    for name in sorted(os.listdir(runtime.EVENTS_DIR)):
        if name.endswith(".jsonl"):
            with open(os.path.join(runtime.EVENTS_DIR, name),
                      encoding="utf-8") as f:
                parts.append(f.read())
    return "\n".join(parts)


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-events-")
        self.home = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        store.ensure_private_dirs()
        os.makedirs(runtime.EVENTS_DIR, exist_ok=True)

    def test_fields_and_order(self):
        for i in range(3):
            events.log_event("a", "publish", "第 %d 次发布" % i,
                             url_after="https://x.trycloudflare.com/p",
                             expires_at=100 + i, source="publish")
        rows = events.read_events("a", 3)
        self.assertEqual([r["summary"] for r in rows],
                         ["第 2 次发布", "第 1 次发布", "第 0 次发布"])
        row = rows[0]
        for field in ("ts", "entry_id", "type", "summary", "details"):
            self.assertIn(field, row)
        self.assertIsInstance(row["ts"], float)
        self.assertEqual(row["details"]["source"], "publish")

    def test_limit_and_entry_filter(self):
        for i in range(4):
            events.log_event("a", "restart", "a%d" % i)
            events.log_event("b", "restart", "b%d" % i)
        self.assertEqual(len(events.read_events("a", 2)), 2)
        self.assertEqual([r["summary"] for r in events.read_events("a", 2)],
                         ["a3", "a2"])
        self.assertEqual(len(events.read_events(limit=2000)), 8)

    def test_sensitive_details_are_dropped_and_urls_cleaned(self):
        events.log_event(
            "a", "pin_change", "改了口令",
            pin="super-secret-pin", token="share-token-xyz",
            authorization="Bearer abc123", password="pa55word",
            secret="hidden", unknown="keep-me-not",
            url_after="https://user:pass@x.trycloudflare.com/p?token=abc#f",
            reason="user", source="ui")
        raw = _raw_events()
        for needle in ("super-secret-pin", "share-token-xyz", "Bearer abc123",
                       "pa55word", "hidden", "keep-me-not"):
            self.assertNotIn(needle, raw)
        for key in ('"pin"', '"token"', '"authorization"', '"password"',
                    '"secret"', '"unknown"'):
            self.assertNotIn(key, raw)
        row = events.read_events("a", 1)[0]
        self.assertEqual(row["details"]["url_after"],
                         "https://x.trycloudflare.com/p")

    def test_bad_type_and_empty_id_are_ignored(self):
        self.assertFalse(events.log_event("", "publish", "x"))
        self.assertFalse(events.log_event("a", "not-a-type", "x"))
        self.assertEqual(events.read_events("a", 5), [])

    def test_write_failure_is_sidepath(self):
        with mock.patch.object(events, "_append_line",
                               side_effect=OSError("disk full")):
            ok = events.log_event("a", "stop", "停止了「x」")
        self.assertFalse(ok)
        activity = store.load_activity()
        self.assertTrue(any("事件日志写入失败" in a["text"] for a in activity))
        self.assertIsNotNone(events.read_events("a", 1))

    def test_tail_reads_do_not_load_whole_file(self):
        path = os.path.join(runtime.EVENTS_DIR,
                            events._day_name() + ".jsonl")
        line = json.dumps({"ts": time.time(), "entry_id": "a",
                           "type": "publish", "summary": "x"}) + "\n"
        with open(path, "w", encoding="utf-8") as f:
            f.write(line * 100000)
        size = os.path.getsize(path)
        read_total = [0]
        real_open = open

        class Counted:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.f.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.f, name)

            def read(self, n=-1):
                data = self.f.read(n)
                read_total[0] += len(data) if isinstance(data, bytes) else 0
                return data

        def fake_open(file, mode="r", *args, **kwargs):
            handle = real_open(file, mode, *args, **kwargs)
            if str(file) == path and mode == "rb":
                return Counted(handle)
            return handle

        with mock.patch("builtins.open", fake_open):
            rows = events.read_events(limit=5)
        self.assertGreater(size, 5 * 1024 * 1024)
        self.assertEqual(len(rows), 5)
        self.assertLess(read_total[0], size // 10)

    def test_bad_lines_are_skipped(self):
        path = os.path.join(runtime.EVENTS_DIR,
                            events._day_name() + ".jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write("not json\n")
            f.write(json.dumps({"ts": 1, "entry_id": "a",
                                "type": "publish", "summary": "ok"}) + "\n")
        self.assertEqual([r["summary"] for r in events.read_events("a", 5)],
                         ["ok"])


class HistoryCliTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-history-cli-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        events.log_event("a", "publish", "发布了「demo」",
                         url_after="https://x.trycloudflare.com", source="publish")

    def _run(self, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_history(SimpleNamespace(**kw))
        return out.getvalue()

    def test_json_output(self):
        payload = json.loads(self._run(id="a", limit=10, json=True))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["id"], "a")
        self.assertEqual(len(payload["data"]["events"]), 1)

    def test_human_output(self):
        text = self._run(id="a", limit=10, json=False)
        self.assertIn("发布了「demo」", text)
        self.assertIn("发布", text)

    def test_empty_state_is_human(self):
        text = self._run(id="missing", limit=10, json=False)
        self.assertIn("还没有变更记录", text)


class HistoryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = temp_home("panweb-history-api-")
        cls.home = cls.ctx.__enter__()
        store.ensure_private_dirs()
        events.log_event("x", "publish", "x-publish")
        events.log_event("y", "publish", "y-publish")
        events.log_event("x", "stop", "x-stop")
        for i in range(210):
            events.log_event("bulk", "restart", "bulk-%d" % i)
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
        cls.ctx.__exit__(None, None, None)

    def get(self, query):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/api/history?" + query,
                     headers={"Host": "127.0.0.1:%d" % self.port})
        data = json.loads(conn.getresponse().read())
        conn.close()
        return data

    def test_filter_and_order(self):
        data = self.get("id=x&limit=2")
        self.assertTrue(data["ok"])
        self.assertEqual([e["summary"] for e in data["data"]["events"]],
                         ["x-stop", "x-publish"])

    def test_limit_cap_and_unknown_id(self):
        data = self.get("id=bulk&limit=999")
        self.assertEqual(len(data["data"]["events"]), 200)
        self.assertEqual(self.get("id=nope&limit=5")["data"]["events"], [])


class HistoryHookTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-history-hooks-")
        self.home = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        store.ensure_private_dirs()

    def test_stop_records_source(self):
        store.save_state([{"id": "s1", "name": "demo", "kind": "pages",
                           "target": "/tmp/demo",
                           "url": "https://x.trycloudflare.com"}])
        stopped = core_stop("s1", source="cli")
        self.assertEqual(stopped[0]["id"], "s1")
        row = events.read_events("s1", 1)[0]
        self.assertEqual(row["type"], "stop")
        self.assertEqual(row["details"]["source"], "cli")

    def test_expire_records_event(self):
        store.save_state([{"id": "e1", "name": "old", "kind": "pages",
                           "target": "/tmp/old", "expires_at": 1,
                           "url": "https://x.trycloudflare.com"}])
        swept = sweep_expired()
        self.assertEqual(swept, ["old"])
        row = events.read_events("e1", 1)[0]
        self.assertEqual(row["type"], "expire")
        self.assertEqual(row["details"]["expires_at"], 1)

    def test_dirty_expires_at_expires_immediately_with_alert(self):
        store.save_state([{"id": "e1", "name": "bad", "kind": "pages",
                           "target": "/tmp/bad", "expires_at": "not-a-time",
                           "url": "https://x.trycloudflare.com"}])
        swept = sweep_expired()
        self.assertEqual(swept, ["bad"])
        self.assertEqual(store.load_state(), [])
        row = events.read_events("e1", 1)[0]
        self.assertEqual(row["details"]["reason"], "invalid_expires_at")
        self.assertIn("损坏", row["summary"])
