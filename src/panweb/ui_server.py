"""控制台 HTTP 服务：回环监听、Host/Origin 校验、静态页面与 API 入口。"""
import json
import os
import signal
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import forwarder, runtime, ui_context
from .browser import open_browser
from .discovery import core_doctor
from .entries import write_menubar_state
from .errors import PanwebError
from .share import ensure_share_tokens
from .store import ensure_private_dirs, log_activity
from .supervisor import cleanup_runtime_files, health_loop, recover_all
from .term import close_all_terms
from .ui_actions import handle_get, handle_post
from .visits import VisitNotifier


def ui_index_bytes():
    data = runtime.read_resource("ui/index.html")
    if data is not None:
        return data
    for d in runtime.ui_dir_candidates():
        path = os.path.join(d, "index.html")
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    return None


def ui_asset_bytes(name):
    data = runtime.read_resource("ui/" + name)
    if data is not None:
        return data
    for d in runtime.ui_dir_candidates():
        path = os.path.join(d, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    return None


class UiHandler(BaseHTTPRequestHandler):
    server_version = "panweb-ui/1.0"

    def log_message(self, fmt, *args):
        pass

    def _local_request_ok(self):
        """只接受发往本机控制台自己的请求，阻断 DNS rebinding 与跨站表单 CSRF。"""
        host = self.headers.get("Host") or ""
        hostname = urllib.parse.urlsplit("//" + host).hostname
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                parts = urllib.parse.urlsplit(origin)
            except ValueError:
                return False
            # 比整个 netloc 而不是只比主机名：本机另一个端口上的页面也别想冒充
            if parts.hostname not in ("127.0.0.1", "localhost", "::1"):
                return False
            if parts.netloc != host:
                return False
        return True

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api_error(self, err, status=None):
        if isinstance(err, PanwebError):
            self.send_json(err.to_dict(),
                           status or (200 if err.exit_code != 1 else 500))
        else:
            self.send_json({"ok": False, "error": {
                "type": "internal_error", "message": str(err)}}, 500)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > runtime.MAX_UI_BODY:
            raise PanwebError(2, "too_large", "请求体过大")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0] \
            .strip().lower()
        if ctype != "application/json":
            raise PanwebError(2, "invalid_argument",
                              "Content-Type 必须是 application/json")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise PanwebError(2, "invalid_json", "请求体不是合法 JSON")
        if not isinstance(data, dict):
            raise PanwebError(2, "invalid_json", "请求体必须是 JSON 对象")
        return data

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if not self._local_request_ok():
                return self.send_json({"ok": False, "error": {
                    "type": "forbidden",
                    "message": "只允许本机访问控制台"}}, 403)
            if path in ("/", "/index.html"):
                return self.serve_index()
            if path == "/favicon.png":
                data = ui_asset_bytes("favicon.png")
                if data is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "max-age=86400")
                self._security_headers()
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if handle_get(self, path):
                return
            self.send_json({"ok": False, "error": {
                "type": "not_found", "message": "未知路径 %s" % path}}, 404)
        except Exception as e:  # noqa: BLE001
            self.api_error(e)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if not self._local_request_ok():
                return self.send_json({"ok": False, "error": {
                    "type": "forbidden",
                    "message": "只允许本机访问控制台"}}, 403)
            body = self.read_body()
            if handle_post(self, path, body):
                return
            self.send_json({"ok": False, "error": {
                "type": "not_found", "message": "未知路径 %s" % path}}, 404)
        except PanwebError as e:
            self.api_error(e, status=200)  # 业务错误保持 200，前端按 ok 判断
        except Exception as e:  # noqa: BLE001
            self.api_error(e)

    def serve_index(self):
        body = ui_index_bytes()
        if body is None:
            body = ("<h1>panweb 控制台</h1><p>缺少 ui/index.html，"
                    "请重新运行 install.sh。</p>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._security_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; "
                         "style-src 'self' 'unsafe-inline'; "
                         "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                         "frame-src http://127.0.0.1:* http://localhost:*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def cmd_ui(args):
    port = args.port
    ensure_private_dirs()
    cleanup_runtime_files()
    ensure_share_tokens()
    ui_context.VISIT_NOTIFIER = VisitNotifier()
    ui_context.VISIT_NOTIFIER.start()
    doctor = core_doctor()
    log_activity("ui", "控制台已启动")
    write_menubar_state()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), UiHandler)
    except OSError as e:
        raise PanwebError(9, "port_in_use",
                          "控制台端口 %d 无法使用：%s" % (port, e),
                          "换一个端口：panweb ui --port 7799")
    server.daemon_threads = True
    url = "http://127.0.0.1:%d" % port
    if doctor["ready"]:
        forwarder.CURRENT_POOL = forwarder.TunnelPool(doctor["cloudflared"],
                                                       size=1)
        forwarder.CURRENT_POOL.prewarm()
        threading.Thread(target=health_loop, daemon=True).start()
        threading.Thread(target=recover_all, daemon=True).start()
    if args.json:
        print(json.dumps({"ok": True, "data": {
            "url": url, "ready": doctor["ready"],
            "pool": bool(forwarder.CURRENT_POOL)}}, ensure_ascii=False),
            flush=True)
    else:
        print("✅ 控制台已启动：%s（Ctrl+C 停止）" % url)
        print("   ⚡ 极速发布已就绪（预热隧道待命）"
              if forwarder.CURRENT_POOL else "")
        if not doctor["ready"]:
            print("   ⚠️  cloudflared 未安装，发布功能不可用"
                  "（brew install cloudflared）")
    if not args.no_open:
        open_browser(url)

    stop_requested = threading.Event()

    def _on_signal(signum, frame):
        if not stop_requested.is_set():
            stop_requested.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass
    try:
        server.serve_forever()
    finally:
        close_all_terms()
        if forwarder.CURRENT_POOL:
            forwarder.CURRENT_POOL.shutdown()
        if ui_context.VISIT_NOTIFIER:
            ui_context.VISIT_NOTIFIER.stop()
        try:
            server.server_close()
        except OSError:
            pass
        write_menubar_state()
        log_activity("ui", "控制台已关闭")
