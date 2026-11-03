"""内置代理：访问口令、分享页、访问统计、反向转发与只读静态服务。"""
import hmac
import http.client
import http.cookies
import mimetypes
import os
import re
import socket
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import runtime, upstream
from .forwarder import duplex
from .pins import (pin_clear_fail, pin_record_fail, pin_retry_after,
                   pin_session, read_pin_record, verify_pin)
from .processes import port_listening
from .share import LOGIN_PAGE, build_share_page
from .static import resolve_static_file
from .store import ensure_private_dirs, load_state
from .visits import log_visit


def _read_websocket_head(up, limit=None):
    """读上游 WebSocket 握手响应头；超过上限必须中止，不能无限攒内存。"""
    limit = runtime.MAX_WS_HEAD if limit is None else limit
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = up.recv(4096)
        if not chunk:
            break
        head += chunk
        if len(head) > limit:
            raise OSError("握手响应头超过 %d KB" % (limit // 1024))
    return head


class ProxyHandler(BaseHTTPRequestHandler):
    """由 panweb 以子进程方式运行：

      panweb --internal-proxy --listen-port N
             (--target-port T | --serve-dir DIR) --entry-id ID
    """

    server_version = "panweb-proxy/1.0"

    def log_message(self, fmt, *args):
        pass

    def _text_error(self, status, text):
        """ASCII reason + UTF-8 body，避免 Python 3.9 latin-1 状态行崩溃。"""
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    # ---- 入口 ----
    def _entry_snapshot(self):
        now = time.time()
        cache = getattr(self.server, "entry_cache", None)
        if cache and now - cache[0] < 2.0:
            return cache[1]
        entry = None
        for e in load_state():
            if e.get("id") == self.server.entry_id:
                entry = e
                break
        self.server.entry_cache = (now, entry)
        return entry

    def _is_document_request(self):
        if self.command != "GET" or self.headers.get("Upgrade"):
            return False
        dest = (self.headers.get("Sec-Fetch-Dest") or "").lower()
        if dest:
            return dest == "document"
        accept = (self.headers.get("Accept") or "").lower()
        if "text/html" in accept:
            return True
        path = urllib.parse.urlsplit(self.path).path
        return path in ("", "/") or path.endswith("/")

    def _visit_context(self):
        return {"referrer": self.headers.get("Referer") or "",
                "country": self.headers.get("CF-IPCountry") or ""}

    def _handle(self):
        entry_id = self.server.entry_id
        path = urllib.parse.urlsplit(self.path).path
        entry = self._entry_snapshot()
        expired = False
        if entry and entry.get("expires_at"):
            try:
                expired = time.time() >= float(entry["expires_at"])
            except (TypeError, ValueError):
                expired = False
        if path == runtime.SHARE_PATH or path.startswith(runtime.SHARE_PATH + "/"):
            token = (path[len(runtime.SHARE_PATH) + 1:].strip("/")
                     if path.startswith(runtime.SHARE_PATH + "/") else "")
            return self._serve_share(entry, token, expired=expired)
        if expired:
            return self._send_expired(entry)
        if read_pin_record(entry_id) and not self._authed(entry_id):
            return self._gate(entry_id)
        if self._is_document_request():
            log_visit(entry_id, self.path, self.client_address[0],
                      self.headers.get("User-Agent"), kind="app",
                      **self._visit_context())
        if self.server.serve_dir:
            if self.command not in ("GET", "HEAD"):
                return self._text_error(403, "只读发布，不接受写入")
            return self._serve_static(self.server.serve_dir)
        if self.headers.get("Upgrade", "").lower() == "websocket":
            return self._forward_websocket(self.server.target_host,
                                           self.server.target_port)
        return self._forward(self.server.target_host, self.server.target_port)

    do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = _handle

    # ---- 分享页 ----
    def _app_online(self, entry):
        if not entry:
            return False
        if entry.get("kind") == "pages":
            target = entry.get("target") or self.server.serve_dir or ""
            return bool(target and os.path.isdir(target))
        try:
            return port_listening(int(entry.get("target")))
        except (TypeError, ValueError):
            return False

    def _send_html(self, body, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; "
                         "img-src data:; form-action 'self'; base-uri 'none'")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _share_host(self, entry):
        host = (self.headers.get("Host") or "").strip()
        if not host:
            host = urllib.parse.urlsplit(entry.get("url") or "").netloc
        return host

    def _share_scheme(self):
        proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0] \
            .strip().lower()
        return proto if proto in ("http", "https") else "https"

    def _serve_share(self, entry, token, expired=False, err="", status=200,
                     record=True, allow_post=False):
        if not entry:
            return self._text_error(404, "分享页不存在")
        expected = entry.get("share_token") or ""
        if not expected or not token or not hmac.compare_digest(token, expected):
            return self._text_error(404, "分享页不存在")
        if self.command not in ("GET", "HEAD") and not allow_post:
            return self._text_error(405, "只支持 GET 访问分享页")
        host = self._share_host(entry)
        share_path = runtime.SHARE_PATH + "/" + token
        share_url = ((self._share_scheme() + "://" + host + share_path)
                     if host else (entry.get("url") or ""))
        pin = bool(read_pin_record(entry.get("id")))
        offline = (not expired) and not self._app_online(entry)
        body = build_share_page(entry, share_url, token=token, expired=expired,
                                offline=offline, pin=pin, err=err)
        if record and not expired and self.command == "GET":
            log_visit(entry.get("id"), share_path, self.client_address[0],
                      self.headers.get("User-Agent"), kind="share",
                      **self._visit_context())
        self._send_html(body, status=status)

    def _send_expired(self, entry):
        host = self._share_host(entry) if entry else ""
        share_url = ((self._share_scheme() + "://" + host + "/")
                     if host else "")
        body = build_share_page(entry or {}, share_url, expired=True)
        self._send_html(body, status=410)

    # ---- 口令 ----
    def _authed(self, entry_id):
        session = pin_session(entry_id)
        if not session:
            return True
        cookie = http.cookies.SimpleCookie(self.headers.get("Cookie") or "")
        morsel = cookie.get("panweb_auth")
        return bool(morsel) and hmac.compare_digest(morsel.value, session)

    def _safe_next(self, value):
        value = (value or "/").strip()
        if not value.startswith("/") or value.startswith("//") or "\\" in value:
            return "/"
        return value

    def _query_share_token(self):
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        return (qs.get("share") or [""])[0]

    def _share_login_failure(self, entry_id, share, err, status=200):
        if share:
            entry = self._entry_snapshot()
            if (entry and entry.get("id") == entry_id
                    and entry.get("share_token")
                    and hmac.compare_digest(share, entry["share_token"])):
                return self._serve_share(entry, share, err=err, status=status,
                                         record=False, allow_post=True)
        return self._login_page(err, status=status)

    def _gate(self, entry_id):
        share = self._query_share_token()
        if self.path.startswith(runtime.LOGIN_PATH) and self.command == "POST":
            wait = pin_retry_after(entry_id)
            if wait:
                return self._share_login_failure(
                    entry_id, share,
                    "尝试次数过多，请 %d 分钟后再试" % max(1, wait // 60),
                    status=429)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > 4096:
                return self._share_login_failure(entry_id, share, "请求过大",
                                                 status=413)
            try:
                form = urllib.parse.parse_qs(
                    self.rfile.read(length).decode("utf-8", "replace"))
            except OSError:
                form = {}
            if verify_pin(entry_id, form.get("pw", [""])[0]):
                pin_clear_fail(entry_id)
                session = pin_session(entry_id)
                if not session:
                    return self._redirect("/")
                cookie = ("panweb_auth=%s; Path=/; HttpOnly; Secure; "
                          "SameSite=Lax; Max-Age=604800" % session)
                self.send_response(302)
                self.send_header("Set-Cookie", cookie)
                self.send_header("Location", self._safe_next(
                    form.get("next", ["/"])[0]))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            pin_record_fail(entry_id)
            self._share_login_failure(entry_id, share, "口令不对，再试试")
            return
        if self.path.startswith(runtime.LOGIN_PATH):
            if share:
                entry = self._entry_snapshot()
                if (entry and entry.get("id") == entry_id
                        and entry.get("share_token")
                        and hmac.compare_digest(share, entry["share_token"])):
                    return self._serve_share(entry, share, record=False)
            return self._login_page("")
        self._redirect(runtime.LOGIN_PATH)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login_page(self, err, status=200):
        body = LOGIN_PAGE.replace("__PANWEB_ERR__", err)
        self._send_html(body, status=status)

    # ---- 反向转发 ----
    def _upstream_plan(self, host, port):
        """上游该看到什么 Host、要不要替访客补上应用自己的凭据。"""
        local = "%s:%d" % (host, port)
        visitor_host = (self.headers.get("Host") or "").strip()
        mode = upstream.host_mode(self._entry_snapshot())
        host_value = (visitor_host or local) if mode == "tunnel" else local
        return host_value, upstream.auth_header(self.server.entry_id)

    def _forward(self, host, port):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length < 0:
            length = 0
        if length > runtime.MAX_PROXY_BODY:
            return self._text_error(
                413, "请求体超过 %d MB 上限"
                % (runtime.MAX_PROXY_BODY // (1024 * 1024)))
        body = self.rfile.read(length) if length else None
        host_value, auth = self._upstream_plan(host, port)
        headers = dict(upstream.forward_headers(
            self.headers.items(), self.client_address[0],
            host_value=host_value, auth=auth))
        conn = http.client.HTTPConnection(host, port, timeout=120)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() in ("connection", "keep-alive", "transfer-encoding",
                                 "content-length"):
                    continue
                self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()  # SSE / 流式响应不缓冲
        except (OSError, http.client.HTTPException) as e:
            try:
                self._text_error(502, "应用暂时无响应（%s）" % e)
            except OSError:
                pass
        finally:
            conn.close()

    # ---- WebSocket 透传 ----
    def _forward_websocket(self, host, port):
        try:
            up = socket.create_connection((host, port), timeout=10)
        except OSError as e:
            return self._text_error(502, "应用暂时无响应（%s）" % e)
        try:
            host_value, auth = self._upstream_plan(host, port)
            lines = ["%s %s HTTP/1.1" % (self.command, self.path)]
            for k, v in upstream.forward_headers(
                    self.headers.items(), self.client_address[0],
                    host_value=host_value, auth=auth, websocket=True):
                lines.append("%s: %s" % (k, v))
            up.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1",
                                                               "replace"))
            try:
                head = _read_websocket_head(up)
            except OSError as e:
                return self._text_error(502, "WebSocket 握手失败（%s）" % e)
            self.connection.sendall(head)
            self.close_connection = True
            up.settimeout(None)
            try:
                self.connection.settimeout(None)
            except OSError:
                pass
            duplex(self.connection, up)
        except OSError:
            try:
                up.close()
            except OSError:
                pass

    # ---- 只读静态服务 ----
    def _serve_static(self, root):
        fp, status = resolve_static_file(root, self.path)
        if status == 404 and self.command in ("GET", "HEAD"):
            clean_path = urllib.parse.urlparse(self.path).path
            last = os.path.basename(clean_path.rstrip("/"))
            if last and not last.startswith(".") \
                    and not os.path.splitext(last)[1]:
                fp, status = resolve_static_file(root, "/index.html")
        if not fp:
            msg = "文件不存在" if status == 404 else "禁止访问"
            return self._text_error(status, msg)
        try:
            size = os.path.getsize(fp)
        except OSError:
            return self._text_error(404, "文件不存在")
        start, end, status_code = 0, max(0, size - 1), 200
        range_header = (self.headers.get("Range") or "").strip()
        if range_header.startswith("bytes="):
            m = re.match(r"bytes=(\d*)-(\d*)$", range_header.split(",")[0].strip())
            if m:
                first, last = m.group(1), m.group(2)
                if first:
                    start = int(first)
                    end = int(last) if last else size - 1
                elif last:
                    start = max(0, size - int(last))
                    end = size - 1
                if start > end or start >= size or end < 0 or size == 0:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status_code = 206
        length = max(0, end - start + 1)
        mime = mimetypes.guess_type(fp)[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript",
                                                "application/json"):
            mime += "; charset=utf-8"
        self.send_response(status_code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status_code == 206:
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (start, end, size))
        self.end_headers()
        if self.command == "HEAD" or length == 0:
            return
        try:
            with open(fp, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except OSError:
            pass


def run_internal_proxy(listen_port, target_port, serve_dir, entry_id):
    """代理子进程入口（阻塞）。"""
    ensure_private_dirs()
    server = ThreadingHTTPServer(("127.0.0.1", listen_port), ProxyHandler)
    server.daemon_threads = True
    server.target_port = target_port
    server.target_host = "127.0.0.1"
    server.serve_dir = serve_dir
    server.entry_id = entry_id
    server.entry_cache = None
    server.serve_forever()
