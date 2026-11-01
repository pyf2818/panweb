"""WebSocket 透传回归：代理必须原样搬 101 握手和后续帧。"""
import base64
import hashlib
import os
import socket
import struct
import threading
import time
import unittest
from http.server import ThreadingHTTPServer

from helpers import temp_home
from panweb import runtime, store
from panweb.proxy import ProxyHandler

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def ws_accept(key):
    digest = hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def read_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise AssertionError("连接被提前关闭")
        buf += chunk
    return buf


def read_frame(conn):
    """读一个未掩码帧（服务端→客户端方向）。"""
    b0, b1 = read_exact(conn, 2)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", read_exact(conn, 2))[0]
    payload = read_exact(conn, length) if length else b""
    return b0 & 0x0F, payload


def read_masked_frame(conn):
    """读一个客户端帧并按协议要求的掩码还原。"""
    b0, b1 = read_exact(conn, 2)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", read_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read_exact(conn, 8))[0]
    key = read_exact(conn, 4) if b1 & 0x80 else b"\x00" * 4
    payload = read_exact(conn, length) if length else b""
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return b0 & 0x0F, masked


def write_frame(conn, opcode, payload, mask=False):
    head = bytearray([0x80 | opcode, (0x80 if mask else 0x00) | len(payload)])
    conn.sendall(bytes(head) + payload)


def send_masked_frame(conn, opcode, payload=b""):
    """客户端→服务端必须掩码，长度 <126 足够测试用。"""
    key = os.urandom(4)
    masked = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    conn.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + key + masked)


def send_masked_text(conn, text):
    send_masked_frame(conn, 0x1, text.encode("utf-8"))


class EchoWsServer:
    """最小 WebSocket 回显后端：完成握手后把客户端帧原样回给对面。"""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.upgraded = []
        self.running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._session, args=(conn,),
                             daemon=True).start()

    def _session(self, conn):
        conn.settimeout(5)
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                head += chunk
            text = head.decode("latin-1", "replace")
            key = ""
            for line in text.split("\r\n"):
                if line.lower().startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            self.upgraded.append(text)
            conn.sendall((
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                "Sec-WebSocket-Accept: %s\r\n\r\n" % ws_accept(key)
            ).encode("ascii"))
            while True:
                opcode, payload = read_masked_frame(conn)
                if opcode == 0x8:      # close
                    write_frame(conn, 0x8, b"")
                    return
                if opcode == 0x9:      # ping → pong
                    write_frame(conn, 0xA, payload)
                    continue
                write_frame(conn, 0x1, b"echo:" + payload)
        except (OSError, AssertionError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


class WebSocketProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = temp_home("panweb-ws-")
        cls.home = cls.ctx.__enter__()
        store.ensure_private_dirs()
        cls.backend = EchoWsServer()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
        cls.server.daemon_threads = True
        cls.server.entry_id = "ws1"
        cls.server.serve_dir = None
        cls.server.target_host = "127.0.0.1"
        cls.server.target_port = cls.backend.port
        cls.server.entry_cache = None
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()
        store.save_json(runtime.STATE_FILE, [{
            "id": "ws1", "name": "WS 演示", "kind": "port",
            "target": cls.backend.port, "proxy_port": cls.port,
            "share_token": "tok_ws", "url": "https://ws.trycloudflare.com"}])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.backend.close()
        cls.ctx.__exit__(None, None, None)

    def handshake(self, path="/ws?x=1"):
        conn = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        conn.settimeout(5)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        conn.sendall((
            "GET %s HTTP/1.1\r\n"
            "Host: 127.0.0.1:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: https://ws.trycloudflare.com\r\n"
            "\r\n" % (path, self.port, key)).encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = conn.recv(4096)
            if not chunk:
                break
            head += chunk
        return conn, head.decode("latin-1", "replace"), key

    def test_upgrade_is_forwarded_and_frames_echo(self):
        conn, head, key = self.handshake()
        try:
            self.assertIn(" 101 ", head.split("\r\n", 1)[0])
            self.assertIn("Sec-WebSocket-Accept: %s" % ws_accept(key), head)
            send_masked_text(conn, "hello")
            opcode, payload = read_frame(conn)
            self.assertEqual(opcode, 0x1)
            self.assertEqual(payload, b"echo:hello")
            send_masked_text(conn, "again")
            self.assertEqual(read_frame(conn)[1], b"echo:again")
            send_masked_frame(conn, 0x9, b"hb")      # ping
            opcode, payload = read_frame(conn)
            self.assertEqual((opcode, payload), (0xA, b"hb"))   # pong
        finally:
            conn.close()

    def test_handshake_headers_reach_backend(self):
        before = len(self.backend.upgraded)
        conn, _, _ = self.handshake(path="/live?id=7")
        conn.close()
        deadline = time.time() + 3
        while (len(self.backend.upgraded) == before
               and time.time() < deadline):
            time.sleep(0.05)
        self.assertGreater(len(self.backend.upgraded), before)
        raw = self.backend.upgraded[-1]
        self.assertIn("GET /live?id=7 HTTP/1.1", raw)
        self.assertIn("Upgrade: websocket", raw)
        self.assertIn("Origin: https://ws.trycloudflare.com", raw)
        self.assertNotIn("Proxy-Connection", raw)


if __name__ == "__main__":
    unittest.main()
