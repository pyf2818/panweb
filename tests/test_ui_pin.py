"""改 PIN 时必须先建新发布，失败则保留旧条目与本地应用。"""
import unittest
from unittest import mock

from helpers import temp_home
from panweb import publish, ui_actions
from panweb.errors import PanwebError
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
            self.assertEqual([e["id"] for e in load_state()], ["new"])
            stop.assert_called_once_with(OLD, keep_app=True)
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
            stop.assert_called_once_with(NEW, keep_app=True)
            self.assertEqual([e["id"] for e in load_state()], ["old"])


if __name__ == "__main__":
    unittest.main()
