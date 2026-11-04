"""state v2：旧 target 迁移、幂等、备份、未知字段保留与访问器。"""
import json
import os
import tempfile
import unittest
from unittest import mock

import helpers
from panweb import discovery, models, publish, runtime, store

PORT_V1 = {
    "id": "p1", "name": "端口应用", "kind": "port", "target": 3000,
    "url": "https://p1.trycloudflare.com", "custom": {"keep": True},
}
PAGES_V1 = {
    "id": "g1", "name": "只读网页", "kind": "pages", "target": "/tmp/site",
    "url": "https://g1.trycloudflare.com", "share_token": "tok",
}


def read_raw(path=None):
    with open(path or runtime.STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-state-v2-")
        self.home = self.ctx.__enter__()
        store.ensure_private_dirs()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def write_v1(self, entries):
        store.save_json(runtime.STATE_FILE, entries)

    def test_port_fixture_migrates_to_port_field(self):
        self.write_v1([PORT_V1])
        entries = store.load_state()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "port")
        self.assertEqual(entries[0]["port"], 3000)
        self.assertNotIn("target", entries[0])
        self.assertEqual(entries[0]["custom"], {"keep": True}, "未知字段要保留")

    def test_pages_fixture_migrates_to_folder_field(self):
        self.write_v1([PAGES_V1])
        entries = store.load_state()
        self.assertEqual(entries[0]["kind"], "pages")
        self.assertEqual(entries[0]["folder"], "/tmp/site")
        self.assertNotIn("target", entries[0])
        self.assertEqual(entries[0]["share_token"], "tok")

    def test_numeric_string_target_becomes_int(self):
        self.write_v1([dict(PORT_V1, target="3000")])
        self.assertEqual(store.load_state()[0]["port"], 3000)

    def test_load_is_idempotent_for_the_same_file(self):
        self.write_v1([PORT_V1, PAGES_V1])
        first = store.load_state()
        second = store.load_state()
        self.assertEqual(first, second, "同一份旧 state 连读两次必须一致")

    def test_migrate_entries_is_idempotent(self):
        once = store.migrate_entries([PORT_V1, PAGES_V1])
        twice = store.migrate_entries(once)
        self.assertEqual(once, twice)

    def test_save_writes_schema_version_two(self):
        self.write_v1([PORT_V1])
        store.save_state(store.load_state())
        raw = read_raw()
        self.assertEqual(raw["schema_version"], 2)
        self.assertEqual(raw["entries"][0]["port"], 3000)
        self.assertNotIn("target", raw["entries"][0])

    def test_save_preserves_unknown_top_level_fields(self):
        self.write_v1([PORT_V1])
        store.save_json(runtime.STATE_FILE,
                        {"schema_version": 2, "third_party": {"x": 1},
                         "entries": [PORT_V1]})
        store.save_state(store.load_state())
        raw = read_raw()
        self.assertEqual(raw["third_party"], {"x": 1})
        self.assertEqual(raw["schema_version"], 2)
        self.assertNotIn("target", raw["entries"][0])

    def test_legacy_file_is_backed_up_once(self):
        self.write_v1([PORT_V1, PAGES_V1])
        store.load_state()
        backup = runtime.STATE_FILE + ".v1-backup"
        self.assertTrue(os.path.isfile(backup), "旧 state 应先留备份")
        self.assertEqual(read_raw(backup), [PORT_V1, PAGES_V1])
        store.save_state(store.load_state())
        self.assertEqual(read_raw(backup), [PORT_V1, PAGES_V1],
                         "备份不能被改写")

    def test_scan_legacy_target_reads_raw_state(self):
        self.write_v1([PORT_V1, {"id": "ok", "kind": "port", "port": 1}])
        self.assertEqual(store.scan_legacy_target(), ["p1"])
        store.save_state(store.load_state())
        self.assertEqual(store.scan_legacy_target(), [])

    def test_v2_file_without_target_needs_no_backup(self):
        store.save_json(runtime.STATE_FILE,
                        {"schema_version": 2,
                         "entries": [{"id": "a", "kind": "port", "port": 9}]})
        self.assertEqual(store.load_state()[0]["port"], 9)
        self.assertFalse(os.path.exists(runtime.STATE_FILE + ".v1-backup"))

    def test_doctor_reports_legacy_target(self):
        self.write_v1([PORT_V1, PAGES_V1])
        data = discovery.core_doctor(force=True)
        self.assertEqual(data["legacy_target"]["count"], 2)
        self.assertFalse(data["legacy_target"]["ok"])
        self.assertIn("自动迁移", data["legacy_target"]["message"])
        store.save_state(store.load_state())
        data = discovery.core_doctor(force=True)
        self.assertEqual(data["legacy_target"]["count"], 0)
        self.assertTrue(data["legacy_target"]["ok"])


class _Proc:
    pid = 4242


class WritePathTests(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-state-v2-write-")
        self.ctx.__enter__()
        store.ensure_private_dirs()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def _publish(self, **kw):
        with mock.patch.object(publish, "require_publish_license"), \
                mock.patch.object(publish, "_ensure_publishable_port"), \
                mock.patch.object(publish, "find_cloudflared",
                                  return_value="/bin/true"), \
                mock.patch.object(publish, "free_port", return_value=5599), \
                mock.patch.object(publish, "_spawn_proxy",
                                  return_value=_Proc()), \
                mock.patch.object(publish, "port_listening",
                                  return_value=True), \
                mock.patch.object(publish, "start_tunnel",
                                  return_value=("https://e1.test", _Proc())), \
                mock.patch.object(publish, "register_entry",
                                  side_effect=lambda e: None), \
                mock.patch.object(publish, "write_menubar_state"):
            return publish._publish_port(register=False, auto_check=False, **kw)

    def test_port_entry_uses_port_not_target(self):
        entry = self._publish(port=3000, name="应用")
        self.assertEqual(entry["kind"], "port")
        self.assertEqual(entry["port"], 3000)
        self.assertNotIn("target", entry)

    def test_pages_entry_uses_folder_not_target(self):
        with tempfile.TemporaryDirectory() as folder:
            entry = self._publish(port=0, name="网页", serve_dir=folder)
        self.assertEqual(entry["kind"], "pages")
        self.assertEqual(entry["folder"], folder)
        self.assertNotIn("target", entry)
        self.assertNotIn("port", entry)

    def test_saved_state_has_no_target(self):
        entry = self._publish(port=3000, name="应用")
        store.save_state([entry])
        raw = read_raw()
        self.assertEqual(raw["schema_version"], 2)
        self.assertNotIn("target", raw["entries"][0])
        self.assertEqual(raw["entries"][0]["port"], 3000)


class AccessorTests(unittest.TestCase):
    def test_entry_port_only_for_port_kind(self):
        self.assertEqual(models.entry_port({"kind": "port", "port": 3000}), 3000)
        self.assertEqual(models.entry_port({"kind": "port", "port": "3000"}),
                         3000)
        self.assertIsNone(models.entry_port({"kind": "pages", "port": 3000}))
        self.assertIsNone(models.entry_port({"kind": "port", "port": 0}))
        self.assertIsNone(models.entry_port({"kind": "port", "port": True}))
        self.assertIsNone(models.entry_port({"kind": "port"}))

    def test_entry_folder_only_for_pages_kind(self):
        self.assertEqual(models.entry_folder(
            {"kind": "pages", "folder": "/tmp/site"}), "/tmp/site")
        self.assertIsNone(models.entry_folder({"kind": "port", "folder": "/x"}))
        self.assertIsNone(models.entry_folder({"kind": "pages", "folder": ""}))
        self.assertIsNone(models.entry_folder({"kind": "pages"}))

    def test_entry_local_port_falls_back_to_source_port(self):
        self.assertEqual(models.entry_local_port(
            {"kind": "port", "port": 3000}), 3000)
        self.assertEqual(models.entry_local_port(
            {"kind": "port", "port": 3000, "proxy_port": 4000}), 4000)
        self.assertIsNone(models.entry_local_port({"kind": "pages"}))


if __name__ == "__main__":
    unittest.main()
