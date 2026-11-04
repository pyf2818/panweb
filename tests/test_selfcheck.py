"""自检编排：走真实的内置代理子进程验证 host_mode 修正与结论落盘。"""
import time
import unittest

from helpers import (PUBLIC_HOST, AlwaysForbidden, HostGate, free_port,
                     proxy_log_tail, serve, stop_server, temp_home)
from panweb import healthcheck, store, upstream
from panweb.errors import PanwebError
from panweb.processes import port_listening, stop_process
from panweb.publish import _spawn_proxy


class CoreCheckTests(unittest.TestCase):
    """代理会缓存条目 2 秒，所以修正必须等真实传播时间，不能只测函数返回值。"""

    def setUp(self):
        self.ctx = temp_home("panweb-check-")
        self.ctx.__enter__()
        store.ensure_private_dirs()

    def tearDown(self):
        self.ctx.__exit__(None, None, None)

    def publish(self, handler_class, entry_id, **attrs):
        srv, backend_port = serve(handler_class, **attrs)
        self.addCleanup(stop_server, srv)
        proxy_port = free_port()
        entry = {"id": entry_id, "name": "自检", "kind": "port",
                 "port": backend_port, "proxy_port": proxy_port,
                 "url": "http://127.0.0.1:%d/" % proxy_port,
                 "host_mode": "loopback"}
        store.save_state([entry])
        proc = _spawn_proxy(proxy_port, entry_id, target_port=backend_port)
        self.addCleanup(stop_process, proc, ("--internal-proxy",))
        # macOS runner 上 HTTPServer 启动时的反解实测约 35 秒，等待窗口要留余量
        deadline = time.time() + 60
        while time.time() < deadline and not port_listening(proxy_port):
            time.sleep(0.1)
        self.assertTrue(port_listening(proxy_port),
                        "代理未启动（poll=%r）\n%s" %
                        (proc.poll(), proxy_log_tail(entry_id)))
        return entry

    def test_host_validation_is_fixed_by_passing_the_public_host(self):
        self.publish(HostGate, "hc1")
        check = healthcheck.core_check("hc1", visitor_host=PUBLIC_HOST,
                                       timeout=4)
        self.assertEqual(check["status"], 200, check["signals"])
        self.assertEqual(check["verdict"], "ok")
        self.assertTrue(check["fixes"], "应当记录一次自动修正")
        self.assertEqual(upstream.host_mode(store.load_state()[0]), "tunnel")
        self.assertEqual(store.load_state()[0]["check"]["verdict"], "ok")

    def test_app_that_refuses_everything_is_not_switched(self):
        self.publish(AlwaysForbidden, "hc2")
        check = healthcheck.core_check("hc2", visitor_host=PUBLIC_HOST,
                                       timeout=4)
        self.assertEqual(check["verdict"], "blocked")
        self.assertEqual(check["fixes"], [])
        self.assertEqual(upstream.host_mode(store.load_state()[0]), "loopback")

    def test_auto_fix_can_be_disabled(self):
        self.publish(HostGate, "hc3")
        check = healthcheck.core_check("hc3", auto_fix=False,
                                       visitor_host=PUBLIC_HOST, timeout=4)
        self.assertEqual(check["verdict"], "blocked")
        self.assertEqual(upstream.host_mode(store.load_state()[0]), "loopback")

    def test_unreachable_backend_is_reported_not_raised(self):
        srv, backend_port = serve(HostGate)
        stop_server(srv)          # 应用已经不在，端口却还留在条目里
        proxy_port = free_port()
        store.save_state([{"id": "hc4", "name": "空端口", "kind": "port",
                           "target": backend_port, "proxy_port": proxy_port,
                           "url": "http://127.0.0.1:%d/" % proxy_port}])
        check = healthcheck.core_check("hc4", visitor_host=PUBLIC_HOST,
                                       timeout=3)
        self.assertEqual(check["verdict"], "blocked")
        self.assertEqual(check["signals"][0]["code"], "unreachable")

    def test_unknown_entry_and_missing_url(self):
        with self.assertRaises(PanwebError):
            healthcheck.core_check("nope")
        store.save_state([{"id": "hc5", "name": "没网址", "kind": "port",
                           "target": 1, "url": ""}])
        with self.assertRaises(PanwebError):
            healthcheck.core_check("hc5")

    def test_schedule_runs_once_per_entry(self):
        healthcheck._RUNNING.add("hc6")
        try:
            self.assertFalse(healthcheck.schedule_check("hc6"))
        finally:
            healthcheck._RUNNING.discard("hc6")

    def test_schedule_persists_a_verdict(self):
        self.publish(HostGate, "hc7")
        self.assertTrue(healthcheck.schedule_check("hc7", delay=0.1))
        check = None
        deadline = time.time() + 20
        while time.time() < deadline:
            check = store.load_state()[0].get("check")
            if check:
                break
            time.sleep(0.2)
        self.assertTrue(check, "后台自检没有落盘")
        self.assertIn(check["verdict"], ("ok", "warn", "blocked"))


if __name__ == "__main__":
    unittest.main()
