"""真终端的 SSE 推流：游标、补发、断线、缓冲丢段与收尾。"""
import base64
import io
import json
import threading
import time
from unittest import mock

from helpers import PtyCase
from panweb import term
from panweb.errors import PanwebError


class StreamStub:
    """够用的 handler 替身：请求头可读，发出去的帧可查。"""

    class _W:
        def __init__(self, target, fail_after=None):
            self.target = target
            self.fail_after = fail_after

        def write(self, data):
            if self.fail_after is not None and len(self.target.getvalue()) >= self.fail_after:
                raise OSError("客户端走了")
            self.target.write(data)

        def flush(self):
            pass

    def __init__(self, request_headers=None, fail_after=None):
        self.buf = io.BytesIO()
        self.headers = request_headers or {}      # 请求头（Last-Event-ID 在这）
        self.sent = {}                            # 我们回给浏览器的响应头
        self.status = None
        self.wfile = self._W(self.buf, fail_after)

    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.sent[key] = value

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def end_headers(self):
        pass

    def blocks(self):
        return [b for b in self.buf.getvalue().decode("utf-8").split("\n\n") if b]

    def frames(self):
        out = []
        for block in self.blocks():
            payload = [l[6:] for l in block.splitlines() if l.startswith("data: ")]
            out.extend(json.loads(p) for p in payload)
        return out

    def text(self):
        return b"".join(base64.b64decode(f["d"]) for f in self.frames()
                        if f.get("d")).decode("utf-8", "replace")


def run_stream(stub, sid, after=0):
    done = threading.Event()

    def go():
        try:
            term.core_terminal_stream(stub, sid, after)
        finally:
            done.set()

    threading.Thread(target=go, daemon=True).start()
    return done


class StreamTests(PtyCase):
    def wait_text(self, stub, needle, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if needle in stub.text():
                return
            time.sleep(0.05)
        self.fail("SSE 里没有 %r：%s" % (needle, stub.text()[-200:]))

    def test_pushes_frames_and_stops_at_exit(self):
        sid = self.boot()
        stub = StreamStub()
        done = run_stream(stub, sid, 0)
        self.type_(sid, "look\r")
        self.wait_text(stub, "look")
        self.assertEqual(stub.status, 200)
        self.assertEqual(stub.sent["Content-Type"],
                         "text/event-stream; charset=utf-8")
        self.assertEqual(stub.sent["X-Frame-Options"], "DENY")
        self.assertEqual(stub.frames()[0]["meta"]["id"], sid)
        self.assertIn("BANNER-HEAD", stub.text())
        self.type_(sid, "exit\r")
        self.assertTrue(done.wait(15), "进程退出后 SSE 应该收工")
        self.assertEqual(stub.frames()[-1]["exit"], 0)

    def test_frames_carry_ids_so_reconnect_can_resume(self):
        sid = self.boot()
        stub = StreamStub()
        run_stream(stub, sid, 0)
        self.wait_text(stub, "BANNER-HEAD")
        self.assertTrue(any("id: " in b for b in stub.blocks()),
                        "没有 id 行的话，浏览器自动重连会从头重播")

    def test_skips_what_the_client_already_has(self):
        sid = self.boot()
        after = term._sessions[sid]["end"]
        stub = StreamStub()
        run_stream(stub, sid, after)
        self.type_(sid, "fresh\r")
        self.wait_text(stub, "fresh")
        self.assertNotIn("BANNER-HEAD", stub.text())

    def test_cursor_ahead_of_the_stream_does_not_stall(self):
        """游标被写坏（after 超过总字节）时也不能装死：继续推后面的画面。"""
        sid = self.boot()
        stub = StreamStub()
        run_stream(stub, sid, 10 ** 12)
        self.type_(sid, "still-alive\r")
        self.wait_text(stub, "still-alive")

    def test_reconnect_uses_last_event_id(self):
        sid = self.boot()
        after = term._sessions[sid]["end"]
        stub = StreamStub(request_headers={"Last-Event-ID": str(after)})
        run_stream(stub, sid, 0)
        self.type_(sid, "resumed\r")
        self.wait_text(stub, "resumed")
        self.assertNotIn("BANNER-HEAD", stub.text())

    def test_gap_is_announced_when_the_buffer_ate_history(self):
        sid = self.boot()
        with mock.patch.object(term, "MAX_BUFFER", 4000):
            self.type_(sid, "spam\r")
            deadline = time.time() + 15
            while time.time() < deadline and term._sessions[sid]["start"] == 0:
                time.sleep(0.05)
            stub = StreamStub()
            run_stream(stub, sid, 0)      # 客户端要的是已被丢掉的那段
            self.wait_text(stub, "AAAA")
            self.assertTrue(any(f.get("gap") for f in stub.frames()),
                            "跳过一段必须说一声，否则前端接着画就是半截转义序列")

    def test_client_disconnect_ends_the_stream(self):
        sid = self.boot()
        stub = StreamStub(fail_after=40)   # 头刚发完就写失败
        done = run_stream(stub, sid, 0)
        self.assertTrue(done.wait(10), "前端断了推流线程要立刻收工")

    def test_close_while_streaming_ends_the_stream(self):
        sid = self.boot()
        stub = StreamStub()
        done = run_stream(stub, sid, 0)
        time.sleep(0.3)
        term.core_terminal_close(sid)
        self.assertTrue(done.wait(12), "关掉终端后挂着它的 SSE 必须收工")
        self.assertIn("exit", stub.frames()[-1])

    def test_unknown_session_errors_before_any_headers(self):
        stub = StreamStub()
        with self.assertRaises(PanwebError) as gone:
            term.core_terminal_stream(stub, "nope", 0)
        self.assertEqual(gone.exception.err_type, "not_found")
        self.assertIsNone(stub.status, "已经发过头就没法再回 JSON 了")
