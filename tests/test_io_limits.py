"""JSON 并发写与 WebSocket 握手头上限的回归测试。"""
import os
import pathlib
import unittest
from concurrent.futures import ThreadPoolExecutor

from helpers import temp_home
from panweb import proxy, store


class JsonWriteTests(unittest.TestCase):
    def test_concurrent_activity_writes_do_not_lose_entries(self):
        with temp_home("panweb-json-"):
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(
                    lambda i: store.log_activity("test", str(i)), range(80)))
            items = store.load_activity()
        self.assertEqual(len(items), 80)
        self.assertEqual({item["text"] for item in items},
                         {str(i) for i in range(80)})

    def test_save_json_replaces_atomically_and_leaves_no_temp(self):
        with temp_home("panweb-json-") as home:
            path = os.path.join(home, "concurrent.json")
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(
                    lambda i: store.save_json(path, {"value": i}), range(50)))
            value = store._load_json(path, None)
            self.assertIsInstance(value, dict)
            self.assertIn("value", value)
            self.assertEqual(list(pathlib.Path(home).glob(
                ".concurrent.json.*.tmp")), [])


class WebSocketHeadTests(unittest.TestCase):
    class FakeUpstream:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        def recv(self, size):
            return self.chunks.pop(0) if self.chunks else b""

    def test_normal_head_is_returned(self):
        head = proxy._read_websocket_head(
            self.FakeUpstream([b"HTTP/1.1 101 Switching\r\n"
                               b"Upgrade: websocket\r\n\r\n"]))
        self.assertTrue(head.endswith(b"\r\n\r\n"))

    def test_oversized_head_is_rejected(self):
        with self.assertRaises(OSError):
            proxy._read_websocket_head(
                self.FakeUpstream([b"x" * 4096] * 3), limit=8192)


if __name__ == "__main__":
    unittest.main()
