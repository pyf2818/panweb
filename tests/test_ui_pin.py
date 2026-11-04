"""改 PIN：同步 pinned、复用条目 id、失败保留旧条目与本地应用。"""
import os
import unittest
from unittest import mock

from helpers import temp_home
from panweb import entries, publish, runtime, ui_actions
from panweb.errors import PanwebError
from panweb.pins import write_pin
from panweb.store import load_state, save_state


class FakeHandler:
    def __init__(self):
        self.payload = None

    def send_json(self, payload):
        self.payload = payload


OLD = {
    "id": "old", "name": "直连应用", "kind": "port", "target": 3000,
    "url": "https://old.trycloudflare.com", "pid": 111,
    "app_pid": 555, "started": "2026-11-04 10:00:00",
}
NEW = {
    "id": "new", "name": "直连应用", "kind": "port", "target": 3000,
    "url": "https://new.trycloudflare.com", "pid": 222, "server_pid": 333,
    "app_pid": 555, "pinned": True, "started": "2026-11-04 10:01:00",
}


class SetPinTests(unittest.TestCase):
    def test_publish_failure_keeps_old_entry(self):
        with temp_home("panweb-pin-"):
            save_state([dict(OLD)])
            handler = FakeHandler()
            with mock.patch.object(publish, "require_publish_license"), \
                    mock.patch.object(publish, "_publish_port",
                                      side_effect=PanwebError(
                                          9, "tunnel_failed", "新隧道挂了")):
                with self.assertRaises(PanwebError):
                    ui_actions._set_pin(handler, {"id": "old", "pin": "1234"})
            self.assertEqual([e["id"] for e in load_state()], ["old"])

    def test_success_swaps_entry_and_keeps_app(self):
        with temp_home("panweb-pin-"):
            save_state([dict(OLD)])
            handler = FakeHandler()
            with mock.patch.object(publish, "require_publish_license"), \
                    mock.patch.object(publish, "_publish_port",
                                      return_value=dict(NEW)), \
                    mock.patch.object(publish, "stop_entry") as stop:
                self.assertTrue(ui_actions._set_pin(
                    handler, {"id": "old", "pin": "1234"}))
            self.assertEqual([e["id"] for e in load_state()], ["old"],
                             "改 PIN 必须复用原 id，否则 visits/secrets 历史会孤立")
            stop.assert_called_once_with(OLD, keep_app=True,
                                         clear_secrets=False)
            self.assertTrue(handler.payload["ok"])

    def test_replace_failure_cleans_new_without_killing_app(self):
        with temp_home("panweb-pin-"):
            save_state([dict(OLD)])
            with mock.patch.object(publish, "require_publish_license"), \
                    mock.patch.object(publish, "_publish_port",
                                      return_value=dict(NEW)), \
                    mock.patch.object(publish, "replace_entry",
                                      side_effect=OSError("state 写失败")), \
                    mock.patch.object(publish, "stop_entry") as stop:
                with self.assertRaises(OSError):
                    ui_actions._set_pin(
                        FakeHandler(), {"id": "old", "pin": "1234"})
            stop.assert_called_once()
            self.assertEqual(stop.call_args[0][0]["id"], "old")
            self.assertEqual(stop.call_args[1],
                             {"keep_app": True, "clear_secrets": False})
            self.assertEqual([e["id"] for e in load_state()], ["old"])

    def test_write_pin_syncs_pinned_flag(self):
        with temp_home("panweb-pin-"):
            save_state([dict(OLD)])
            write_pin("old", "1234")
            self.assertTrue(load_state()[0]["pinned"])
            write_pin("old", None)
            self.assertFalse(load_state()[0]["pinned"])

    def test_stop_without_clear_keeps_visits_and_pin(self):
        with temp_home("panweb-pin-"):
            save_state([dict(OLD)])
            write_pin("old", "1234")
            os.makedirs(runtime.VISITS_DIR, exist_ok=True)
            visits = os.path.join(runtime.VISITS_DIR, "old.jsonl")
            with open(visits, "w", encoding="utf-8") as f:
                f.write("{}\n")
            with mock.patch.object(entries, "kill_process"):
                entries.stop_entry(OLD, keep_app=True, clear_secrets=False)
            self.assertTrue(os.path.exists(visits))
            self.assertTrue(os.path.exists(
                os.path.join(runtime.SECRETS_DIR, "old.pin")))


if __name__ == "__main__":
    unittest.main()
