import contextlib
import os
import pathlib
import shutil
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from panweb import discovery, forwarder, pins, runtime, ui_context  # noqa: E402


def reset_caches():
    discovery._DOCTOR_CACHE.update(ts=0.0, data=None)
    forwarder.FORWARDERS.clear()
    forwarder.CURRENT_POOL = None
    pins.PIN_FAILS.clear()
    ui_context.VISIT_NOTIFIER = None


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
