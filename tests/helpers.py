import atexit
import base64
import contextlib
import os
import pathlib
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from panweb import (agents, discovery, forwarder, pins, runtime, term,
                     ui_context)  # noqa: E402
from panweb.errors import PanwebError  # noqa: E402


def reset_caches():
    discovery._DOCTOR_CACHE.update(ts=0.0, data=None)
    forwarder.FORWARDERS.clear()
    forwarder.CURRENT_POOL = None
    pins.PIN_FAILS.clear()
    ui_context.VISIT_NOTIFIER = None


# 测试一启动就把状态目录挪到临时位置：即使开发者机器上设了 PANWEB_HOME，
# 跑测试也不会读写真实的 ~/.panweb；需要更细隔离的用例再用 temp_home。
_SESSION_HOME = tempfile.mkdtemp(prefix="panweb-tests-")
runtime.set_home(_SESSION_HOME)
reset_caches()
atexit.register(shutil.rmtree, _SESSION_HOME, True)


@contextlib.contextmanager
def temp_home(prefix="panweb-test-"):
    old = runtime.HOME_DIR
    path = tempfile.mkdtemp(prefix=prefix)
    runtime.set_home(path)
    reset_caches()
    try:
        yield path
    finally:
        reset_caches()
        runtime.set_home(old)
        shutil.rmtree(path, ignore_errors=True)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def proxy_log_tail(entry_id, limit=1500):
    """把代理子进程日志带进断言信息：CI 上“代理未启动”时能直接看到根因。"""
    path = os.path.join(runtime.LOG_DIR, "%s-proxy.log" % entry_id)
    try:
        with open(path, "rb") as f:
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return "（没有代理日志）"
    return data[-limit:] or "（代理日志为空）"


# ---- 自检与转发测试共用的假应用 ----
PUBLIC_HOST = "alpha-beta-gamma.trycloudflare.com"
GOOD_PAGE = ('<html><head><link rel="stylesheet" href="/app.css"></head>'
             '<body><div id="root">正在启动…</div>'
             '<script src="/app.js"></script>'
             '<p>这段文字用来把首页撑过空白页阈值，避免自检误报。</p>'
             '</body></html>')
LOGIN_PAGE = ('<html><body><form action="/signin">'
              '<input type="password" name="pw">'
              '<p>请先登录你的账号才能使用本工作台</p></form></body></html>')


class FakeApp(BaseHTTPRequestHandler):
    """按 Host 前缀给状态的假应用：既能演"校验 Host 的应用"，也能演"谁都不给过"。"""

    code_for = {}
    force_code = None
    body = GOOD_PAGE
    redirect = None

    def log_message(self, fmt, *args):
        pass

    def _payload(self):
        if self.path in ("/app.js", "/app.css"):
            return b"/* asset */", "application/javascript"
        return self.body.encode("utf-8"), "text/html; charset=utf-8"

    def do_GET(self):
        if self.path == "/missing.js":
            return self._reply(404)
        if self.redirect and self.path == self.redirect[0]:
            self.send_response(302)
            self.send_header("Location", self.redirect[1])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        host = self.headers.get("Host") or ""
        code = self.force_code
        if code is None:
            code = 200
            for prefix, status in sorted(self.code_for.items()):
                if host.startswith(prefix):
                    code = status
                    break
        self._reply(code)

    def _reply(self, code):
        body, ctype = self._payload()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HostGate(FakeApp):
    """只肯服务公网域名：对本机地址一律 403，正是需要 tunnel Host 模式的应用。"""

    code_for = {"127.0.0.1": 403, "localhost": 403}


class AlwaysForbidden(FakeApp):
    """怎么都不给过——多半是应用自己要登录，改 Host 也没用。"""

    force_code = 403
    body = LOGIN_PAGE


def serve(handler_class=FakeApp, **attrs):
    """起一个假应用；attrs 覆盖类属性，避免测试之间互相污染。"""
    handler = type("ServedApp", (handler_class,), dict(attrs))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def stop_server(srv):
    srv.shutdown()
    srv.server_close()


# ---- 真终端测试共用的假 Agent ----
# 逐字回显键盘，认 exit / crash / size / spam 四条指令，把 argv 打在横幅里
FAKE_PTY = """#!/usr/bin/env python3
import fcntl, os, struct, sys, termios
def w(t):
    os.write(1, t if isinstance(t, bytes) else t.encode())
w("\\x1b[32mARGV " + " ".join(sys.argv[1:]) + "\\x1b[0m\\r\\n")
w("BANNER-HEAD\\r\\n")
w("BANNER-TAIL\\r\\n")
line = b""
while True:
    try:
        chunk = os.read(0, 64)
    except OSError:
        break
    if not chunk:
        break
    for ch in chunk:
        if ch in (13, 10):
            w("\\r\\n")
            text = line.decode()
            line = b""
            if text == "exit":
                sys.exit(0)
            if text == "crash":
                sys.exit(3)
            if text == "size":
                rows, cols = struct.unpack("HHHH", fcntl.ioctl(
                    0, termios.TIOCGWINSZ, b"\\0" * 8))[0:2]
                w("SIZE %d %d\\r\\n" % (rows, cols))
            if text == "spam":
                w(("A" * 4000 + "\\r\\n") * 200)
        elif ch == 3:
            w("^C\\r\\n")
        else:
            line += bytes([ch])
            w(bytes([ch]))
"""


def make_executable(directory, name, body):
    """在临时目录里放一个可执行脚本，供 PATH 白名单解析。"""
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP |
             stat.S_IROTH | stat.S_IXOTH)
    return path


class PtyCase(unittest.TestCase):
    """真终端测试共用：把假 Agent 塞进 PATH、换掉白名单、每个用例清空会话。"""

    TERM_ID = "fake"

    def setUp(self):
        from unittest import mock
        self.ctx = temp_home("panweb-term-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.bin = tempfile.mkdtemp(prefix="panweb-fakepty-")
        self.addCleanup(shutil.rmtree, self.bin, True)
        make_executable(self.bin, "fake-agent", FAKE_PTY)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = self.bin + os.pathsep + old_path
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        terminals = {
            self.TERM_ID: {"bin": "fake-agent", "name": "Fake Agent",
                           "argv": ("--approve-for-me",), "note": "测试用"},
            "missing": {"bin": "definitely-not-installed", "name": "Missing",
                        "argv": (), "note": "测试用"},
        }
        patcher = mock.patch.dict(agents.TERMINALS, terminals, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.close_all()
        self.addCleanup(self.close_all)

    def tearDown(self):
        term._stopping = False

    def close_all(self):
        for sid in list(term._sessions):
            try:
                term.core_terminal_close(sid)
            except PanwebError:
                pass
        term._sessions.clear()
        del term._order[:]

    def open_fake(self):
        return term.core_terminal_open(self.TERM_ID, cwd=self.bin, cols=90,
                                       rows=24)

    def boot(self):
        sid = self.open_fake()["id"]
        self.wait_for(sid, "BANNER-TAIL")
        return sid

    def screen(self, sid):
        session = term._sessions[sid]
        with session["cond"]:
            return session["buf"].decode("utf-8", "replace")

    def wait_for(self, sid, needle, timeout=15.0):
        deadline, text = time.time() + timeout, ""
        while time.time() < deadline:
            text = self.screen(sid)
            if needle in text:
                return text
            time.sleep(0.05)
        self.fail("终端画面里没等到 %r：%s" % (needle, text[-200:]))

    def wait_dead(self, sid, timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not term._sessions[sid]["alive"]:
                return term._summary(term._sessions[sid])
            time.sleep(0.05)
        self.fail("终端里的程序没有退出")

    def type_(self, sid, text):
        term.core_terminal_input(sid, base64.b64encode(text.encode()).decode())
