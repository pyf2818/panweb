"""发布/启动失败时，半成品代理、隧道、PIN 与项目进程都要被回收。"""
import shutil
import tempfile
import unittest
from unittest import mock

from helpers import temp_home
from panweb import entries, pins, publish
from panweb.errors import PanwebError, TunnelError


class FakeProc:
    pid = 4242

    def poll(self):
        return None


class PublishFailureCleanupTests(unittest.TestCase):
    def test_tunnel_failure_stops_proxy_and_clears_pin(self):
        with temp_home("panweb-publish-"):
            ids = []

            def spawn(listen_port, entry_id, **kw):
                ids.append(entry_id)
                pins.write_pin(entry_id, kw.get("pin"))
                return FakeProc()

            with mock.patch.object(publish, "find_cloudflared",
                                   return_value="/bin/cloudflared"), \
                    mock.patch.object(publish, "free_port",
                                      return_value=4567), \
                    mock.patch.object(publish, "_spawn_proxy",
                                      side_effect=spawn), \
                    mock.patch.object(publish, "port_listening",
                                      return_value=True), \
                    mock.patch.object(publish, "start_tunnel",
                                      side_effect=TunnelError("隧道挂了")), \
                    mock.patch.object(entries, "kill_process",
                                      return_value=True):
                with self.assertRaises(PanwebError):
                    publish._publish_port(3000, "隧道失败", pin="1234")

            self.assertEqual(len(ids), 1)
            self.assertIsNone(pins.read_pin_record(ids[0]))

    def test_run_failure_stops_app_process(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        proc = FakeProc()
        with temp_home("panweb-run-"), \
                mock.patch.object(publish, "core_detect",
                                  return_value={"type": "node", "script": "dev",
                                                "folder": folder, "detail": ""}), \
                mock.patch.object(publish.shutil, "which",
                                  return_value="/usr/bin/npm"), \
                mock.patch.object(publish, "listening_ports",
                                  return_value=[]), \
                mock.patch.object(publish.subprocess, "Popen",
                                  return_value=proc), \
                mock.patch.object(publish, "_sniff_port",
                                  return_value=3000), \
                mock.patch.object(publish, "_publish_port",
                                  side_effect=PanwebError(
                                      9, "tunnel_failed", "隧道挂了")), \
                mock.patch.object(publish, "stop_process") as stop:
            with self.assertRaises(PanwebError):
                publish.core_run(folder, "启动后发布失败")

        stop.assert_called_once_with(
            proc, ("npm", "node", "pnpm", "yarn", "bun"))


if __name__ == "__main__":
    unittest.main()
