"""CLI 是独立进程，stop 必须能通过控制 socket 回收控制台里的 Forwarder。"""
import os
import time
import unittest

from helpers import temp_home
from panweb import forwarder, runtime
from panweb.processes import free_port, port_listening


class ForwarderControlTests(unittest.TestCase):
    def test_remote_stop_releases_listening_port(self):
        with temp_home("panweb-fw-"):
            os.makedirs(runtime.FORWARDERS_DIR, exist_ok=True)
            port = free_port()
            fw = forwarder.Forwarder(port)
            fw.start()
            fw.enable_control("f1")
            self.assertTrue(port_listening(port))
            forwarder.FORWARDERS.clear()
            self.assertTrue(forwarder.stop_remote("f1"))
            for _ in range(20):
                if not port_listening(port):
                    break
                time.sleep(0.05)
            self.assertFalse(port_listening(port),
                             "控制 socket 必须能关掉另一个进程语义下的转发器")
            self.assertFalse(os.path.exists(
                os.path.join(runtime.FORWARDERS_DIR, "f1.sock")))

    def test_unknown_entry_is_not_an_error_and_stale_socket_is_removed(self):
        with temp_home("panweb-fw-"):
            os.makedirs(runtime.FORWARDERS_DIR, exist_ok=True)
            path = os.path.join(runtime.FORWARDERS_DIR, "gone.sock")
            with open(path, "w", encoding="utf-8") as f:
                f.write("")
            self.assertFalse(forwarder.stop_remote("gone"))
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
