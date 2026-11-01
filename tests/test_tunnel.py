"""隧道传输选择：QUIC 被网络吃掉时要能改走 http2，而不是留下永远 530 的网址。"""
import os
import shutil
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401  先把 src/ 放进 sys.path
from panweb import tunnel

FAKE_URL = "https://fake-tunnel-host.trycloudflare.com"


class FakePopen:
    """替掉 cloudflared：只记录 argv，并把网址写进日志让 start_tunnel 读到。"""

    def __init__(self, argv, **kw):
        self.argv = list(argv)
        self.pid = os.getpid()
        self.returncode = None
        stream = kw.get("stdout")
        if stream is not None:
            stream.write(("%s has been created\n" % FAKE_URL).encode())
            stream.flush()

    def poll(self):
        return None


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        os.environ.pop("PANWEB_TUNNEL_PROTOCOL", None)
        tunnel._quic_probe.update(at=0.0, ok=False)
        self.dir = tempfile.mkdtemp(prefix="panweb-tunnel-")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_forced_protocol_wins(self):
        for value in ("http2", "quic", "auto"):
            os.environ["PANWEB_TUNNEL_PROTOCOL"] = value
            self.assertEqual(tunnel.tunnel_protocol(), value)

    def test_probe_failure_selects_http2(self):
        with mock.patch.object(tunnel, "quic_usable", return_value=False):
            self.assertEqual(tunnel.tunnel_protocol(), "http2")
        with mock.patch.object(tunnel, "quic_usable", return_value=True):
            self.assertEqual(tunnel.tunnel_protocol(), "auto")

    def test_quic_probe_is_cached_per_process(self):
        with mock.patch("panweb.tunnel.socket.getaddrinfo",
                        side_effect=OSError("no dns")) as resolver:
            self.assertFalse(tunnel.quic_usable(timeout=0.1))
            self.assertFalse(tunnel.quic_usable(timeout=0.1))
            self.assertEqual(resolver.call_count, 1, "探测结果没被复用，发布会被拖慢")

    def test_start_tunnel_passes_the_protocol_flag(self):
        log = os.path.join(self.dir, "t.log")
        seen = {}
        class SpyPopen(FakePopen):
            def __init__(self, argv, **kw):
                super().__init__(argv, **kw)
                seen["argv"] = self.argv
        with mock.patch.object(tunnel, "tunnel_protocol", return_value="http2"), \
                mock.patch("panweb.tunnel.subprocess.Popen", SpyPopen):
            url, _ = tunnel.start_tunnel("cloudflared", 3000, log)
        self.assertEqual(url, FAKE_URL)
        self.assertEqual(seen["argv"][-2:], ["--protocol", "http2"])

    def test_auto_keeps_the_command_line_unchanged(self):
        seen = {}
        class SpyPopen(FakePopen):
            def __init__(self, argv, **kw):
                super().__init__(argv, **kw)
                seen["argv"] = self.argv
        log = os.path.join(self.dir, "t2.log")
        with mock.patch.object(tunnel, "tunnel_protocol", return_value="auto"), \
                mock.patch("panweb.tunnel.subprocess.Popen", SpyPopen):
            tunnel.start_tunnel("cloudflared", 3000, log)
        self.assertNotIn("--protocol", seen["argv"])
        self.assertIn("--no-autoupdate", seen["argv"])


if __name__ == "__main__":
    unittest.main()
