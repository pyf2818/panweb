"""自愈不能骗人：死隧道不进取用池，恢复失败就说失败。"""
import os
import unittest

from helpers import temp_home
from panweb import forwarder, store, supervisor
from panweb.errors import TunnelError

DEAD_PID = 999999


class FakeProc:
    pid = 4242

    def poll(self):
        return None


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-pool-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        store.ensure_private_dirs()

    def pool(self, items):
        p = forwarder.TunnelPool("cloudflared")
        p.items = list(items)
        return p

    def test_dead_pooled_tunnels_are_not_handed_out(self):
        live = {"pid": os.getpid(), "port": 1, "url": "https://live.test",
                "forwarder": None}
        pool = self.pool([{"pid": DEAD_PID, "port": 0, "url": "https://dead.test",
                           "forwarder": None},
                          {"pid": DEAD_PID + 1, "port": 0,
                           "url": "https://dead2.test", "forwarder": None},
                          live])
        got = pool.acquire()
        self.assertEqual(got, live, "两次自愈都取到死隧道，就是那 9 分钟的死循环")
        self.assertEqual(pool.items, [])

    def test_empty_after_all_dead(self):
        pool = self.pool([{"pid": DEAD_PID, "port": 0, "url": "https://x.test",
                           "forwarder": None}])
        self.assertIsNone(pool.acquire())


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-recover-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        store.ensure_private_dirs()
        self.entry = {"id": "e1", "name": "演示", "kind": "port", "target": 3000,
                      "url": "https://old.test", "pid": DEAD_PID}
        store.save_state([dict(self.entry)])
        self.saved_pool = forwarder.CURRENT_POOL
        forwarder.CURRENT_POOL = None
        self.addCleanup(setattr, forwarder, "CURRENT_POOL", self.saved_pool)

    def test_dead_new_tunnel_is_not_recorded_as_recovered(self):
        calls = {}

        def fake_start(cf, port, log_path):
            calls["killed"] = False
            return "https://new.test", FakeProc()

        def fake_kill(pid, markers):
            calls["killed"] = True

        orig_start, orig_kill, orig_pinned = (supervisor.start_tunnel,
                                             supervisor.kill_process,
                                             supervisor.pinned_status)
        supervisor.start_tunnel = fake_start
        supervisor.kill_process = fake_kill
        supervisor.pinned_status = lambda url, timeout: 530
        # 只改自己的重试间隔常量；直接换 time.sleep 会污染同进程的其他测试
        orig_wait = supervisor.RETRY_WAIT
        supervisor.RETRY_WAIT = 0.0
        self.addCleanup(setattr, supervisor, "start_tunnel", orig_start)
        self.addCleanup(setattr, supervisor, "kill_process", orig_kill)
        self.addCleanup(setattr, supervisor, "pinned_status", orig_pinned)
        self.addCleanup(setattr, supervisor, "RETRY_WAIT", orig_wait)
        with self.assertRaises(TunnelError):
            supervisor.restart_entry_tunnel(dict(self.entry))
        self.assertTrue(calls.get("killed"), "死隧道该被杀掉")
        kept = store.load_state()[0]
        self.assertEqual(kept["url"], "https://old.test",
                         "没验证通过的网址不能写进状态")

    def test_serving_tunnel_is_adopted(self):
        def fake_start(cf, port, log_path):
            return "https://new.test", FakeProc()

        orig = (supervisor.start_tunnel, supervisor.pinned_status)
        supervisor.start_tunnel = fake_start
        supervisor.pinned_status = lambda url, timeout: 200
        self.addCleanup(setattr, supervisor, "start_tunnel", orig[0])
        self.addCleanup(setattr, supervisor, "pinned_status", orig[1])
        self.assertEqual(supervisor.restart_entry_tunnel(dict(self.entry)),
                         "https://new.test")
        self.assertEqual(store.load_state()[0]["url"], "https://new.test")


if __name__ == "__main__":
    unittest.main()
