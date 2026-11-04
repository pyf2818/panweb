"""健康阈值与手动恢复：抖动不换网址，恢复只碰真正异常的条目。"""
import unittest
from unittest import mock

from helpers import temp_home
from panweb import supervisor, ui_actions
from panweb.store import save_state


def entry(eid="e1", url="https://e1.trycloudflare.com"):
    return {"id": eid, "name": eid, "kind": "port", "target": 3000,
            "proxy_port": 9001, "server_pid": 501, "pid": 601, "url": url}


class HealthThresholdTests(unittest.TestCase):
    def setUp(self):
        supervisor.HEALTH_FAILS.clear()
        self.entry = entry()

    def tearDown(self):
        supervisor.HEALTH_FAILS.clear()

    def step(self, status=502, tunnel_alive=True):
        with mock.patch.object(supervisor, "port_listening", return_value=True), \
                mock.patch.object(supervisor, "pid_alive",
                                  side_effect=lambda pid: tunnel_alive
                                  if pid == self.entry["pid"] else True), \
                mock.patch.object(supervisor, "public_status",
                                  return_value=status), \
                mock.patch.object(supervisor, "restart_entry_proxy",
                                  return_value=True) as proxy, \
                mock.patch.object(supervisor, "restart_entry_tunnel",
                                  return_value="https://new.trycloudflare.com") as tun:
            supervisor._health_step(self.entry)
        return proxy, tun

    def test_502_uses_threshold_and_keeps_url_while_tunnel_alive(self):
        for _ in range(2):
            proxy, tun = self.step(502)
            proxy.assert_not_called()
            tun.assert_not_called()
        proxy, tun = self.step(502)
        proxy.assert_called_once()
        tun.assert_not_called()
        self.assertEqual(supervisor.HEALTH_FAILS.get("e1"), None)

    def test_530_same_threshold(self):
        for _ in range(3):
            _, tun = self.step(530)
        tun.assert_not_called()

    def test_tunnel_dead_rebuilds_url_after_threshold(self):
        for _ in range(2):
            _, tun = self.step(530, tunnel_alive=False)
            tun.assert_not_called()
        _, tun = self.step(530, tunnel_alive=False)
        tun.assert_called_once()

    def test_recovery_clears_counter(self):
        self.step(502)
        self.step(502)
        self.step(502)
        self.assertEqual(supervisor.HEALTH_FAILS.get("e1"), None)
        _, tun = self.step(200)
        tun.assert_not_called()


class RecoverFailingTests(unittest.TestCase):
    def test_only_dead_or_public_failed_entries_are_restarted(self):
        healthy = entry("ok")
        dead = entry("dead")
        public_bad = entry("bad", "https://bad.trycloudflare.com")
        with temp_home("panweb-rec-"):
            save_state([healthy, dead, public_bad])

            def alive(e):
                return e["id"] != "dead"

            def status(url, timeout=6):
                return 0 if "bad" in url else 1

            with mock.patch.object(supervisor, "entry_alive",
                                   side_effect=alive), \
                    mock.patch.object(supervisor, "pinned_status",
                                      side_effect=status), \
                    mock.patch.object(supervisor, "restart_entry_tunnel",
                                      side_effect=lambda e: "https://new-" + e["id"]):
                result = supervisor.recover_failing()
        self.assertEqual([r["id"] for r in result["recovered"]], ["dead", "bad"])
        self.assertEqual(result["checked"], 2)

    def test_api_starts_background_job(self):
        class Handler:
            def __init__(self):
                self.payload = None

            def send_json(self, payload):
                self.payload = payload

        handler = Handler()
        with mock.patch.object(ui_actions.jobs, "start",
                               return_value="job1") as start:
            self.assertTrue(ui_actions._recover(handler))
        self.assertEqual(handler.payload["data"]["job"], "job1")
        self.assertEqual(start.call_args[0][0], "recover")


if __name__ == "__main__":
    unittest.main()
