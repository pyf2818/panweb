"""发布后的远程自检：按访客的方式真打开一次，判断会不会只看到一个壳。

隧道通了不等于应用能用。这一层从公网取首页、取首页引用的资源、试一次 WebSocket
握手，把观察结果翻译成能执行的结论；怀疑是 Host 校验挡住时，先拿本机上游取证，
证据够了才改 host_mode——不靠猜，也不会把已经能用应用改坏。
"""
import base64
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import runtime, upstream
from .entries import find_entry
from .errors import PanwebError
from .models import entry_port, entry_public_url
from .store import load_domain, load_state, log_activity, save_state, state_lock
from .tunnel import pinned_status

CHECK_TIMEOUT = 5.0
CHECK_BUDGET = 20.0
MAX_ASSETS = 4
MAX_BODY = 64 * 1024
# 内置代理缓存条目 2 秒，改完 host_mode 要等它过期才能看到新行为。
ENTRY_CACHE_WAIT = 2.6

ASSET_RE = re.compile(r"""(?:src|href)\s*=\s*['"]([^'"]+)['"]""", re.I)
SOURCE_SUFFIXES = (".ts", ".tsx", ".jsx", ".vue", ".svelte",
                   ".scss", ".sass", ".less", ".coffee")
CSS_JS_SUFFIXES = (".js", ".mjs", ".cjs", ".css")

SIGNALS = {
    "unreachable": ("公网没有响应", "隧道可能还在启动；稍等几秒点「重新自检」，"
                                   "仍不行就用「恢复通道」或重新发布"),
    "dns_slow": ("本机解析不到这个网址，但隧道在响应",
                 "这台机器的 DNS 对新子域名还没跟上（或被污染）。已用 Cloudflare 边缘 "
                 "IP 直连确认有响应，访客侧多半能打开；等几分钟再自检，"
                 "或直接让访客试网址"),
    "host_rejected": ("应用拒绝本机地址的 Host", "已可自动改为「公网域名」模式；"
                                                 "改完访客能打开就保留"),
    "auth_required": ("应用自己要凭据（HTTP %s）", "在「上游兼容」里替访客补上应用的"
                                                  "凭据，panweb 口令管不到它内部"),
    "server_error": ("应用返回 HTTP %s", "打开「运行日志」看报错；应用本身没跑起来时"
                                         "公网只会显示这个"),
    "tunnel_down": ("Cloudflare 说这台机器没连上来（HTTP %s）",
                    "隧道进程掉线，多半是本机到 Cloudflare 的网络抖动，不是应用的错。"
                    "等几十秒点「重新自检」，或在控制台「恢复通道」/重新发布"),
    "not_found": ("首页就是 404", "端口上没有这个路径；确认应用监听的路径，"
                                  "或发布构建产物目录"),
    "redirect_out": ("首页跳到了公网地址之外（%s）", "应用把访客指向了别的域名，"
                                             "公网访问会断在这里"),
    "own_pin_gate": ("先撞上 panweb 的口令页", "正常：访客输完口令才会进入应用"),
    "app_login": ("应用要求登录它自己的账号", "panweb 口令不等于应用登录；"
                                             "要么让访客自己登录，要么在「上游兼容」补凭据"),
    "blank_page": ("首页几乎是空的", "多半是发布了未编译的源码目录，"
                                     "或应用要 JS 构建产物才有内容"),
    "asset_404": ("%d 个页面资源打不开", "路径写死或没构建；构建后再发布 dist/ 目录"),
    "uncompiled_source": ("页面引用了源码文件", "这是源码目录，浏览器看不懂；"
                                               "先 npm run build，再发布 dist/"),
    "ws_blocked": ("WebSocket 握手在公网没通过", "实时功能（对话、进度、协同）"
                                                "在公网会连不上；若它要求自带令牌，"
                                                "在「上游兼容」里补上"),
    "direct_403": ("应用自己拒绝了公网域名", "直连发布已经把公网域名原样交给应用，"
                                            "403 来自应用的规则（如 Vite allowedHosts），"
                                            "需要项目侧放开"),
    "looks_good": ("首页正常返回", ""),
}

_SEVERITY = {"unreachable": "bad", "host_rejected": "bad", "server_error": "bad",
             "tunnel_down": "bad",
             "not_found": "bad", "asset_404": "bad", "uncompiled_source": "bad",
             "redirect_out": "bad", "auth_required": "warn", "app_login": "warn",
             "blank_page": "warn", "ws_blocked": "warn", "direct_403": "warn",
             "dns_slow": "warn",
             "own_pin_gate": "info", "looks_good": "info"}


def _sig(code, detail=""):
    label, advice = SIGNALS.get(code, (code, ""))
    detail = str(detail or "")
    if "%s" in label or "%d" in label:
        label = label.replace("%d", "%s") % detail
    elif "%s" in advice or "%d" in advice:
        advice = advice.replace("%d", "%s") % detail
    return {"code": code, "label": label, "severity": _SEVERITY.get(code, "info"),
            "detail": detail, "advice": advice}


def _entry_name(entry_id):
    for e in load_state():
        if e.get("id") == entry_id:
            return e.get("name") or entry_id
    return entry_id


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _result(status, headers, body, final_url):
    text = body.decode("utf-8", "replace") if body else ""
    return {"status": status, "headers": dict(headers or {}), "body": text,
            "length": len(body or b""), "final_url": final_url, "error": None}


def probe(url, host=None, timeout=CHECK_TIMEOUT, hops=3, headers=None):
    """GET 一次，只跟同源重定向；返回 {status, body, headers, error, final_url}。

    404、403、500 都是结论而不是异常，必须带 body 回去 —— 应用往往就在这些响应里
    写着"请登录"。真正的网络故障才有 error。
    """
    opener = urllib.request.build_opener(_NoRedirect())
    sent = dict(headers or {})
    if host:
        sent["Host"] = host
    sent.setdefault("User-Agent", "panweb-check/%s" % runtime.PANWEB_VERSION)
    sent.setdefault("Accept", "text/html,application/json,*/*")
    current = url
    left = max(0, int(hops))
    for _ in range(left + 1):
        req = urllib.request.Request(current, headers=sent)
        try:
            with opener.open(req, timeout=timeout) as resp:
                return _result(resp.status, resp.getheaders(),
                               resp.read(MAX_BODY), current)
        except urllib.error.HTTPError as e:
            try:
                body = e.read(MAX_BODY)
            except Exception:  # noqa: BLE001 - 读不到 body 也不影响状态码结论
                body = b""
            nxt = _same_origin_hop(e, current)
            if nxt and left:
                left -= 1
                current = nxt
                continue
            return _result(e.code, e.headers, body, current)
        except OSError as e:
            return {"status": None, "headers": {}, "body": "", "length": 0,
                    "final_url": current,
                    "error": "%s: %s" % (type(e).__name__, e)}
    return {"status": None, "headers": {}, "body": "", "length": 0,
            "final_url": current, "error": "重定向次数过多"}


def _same_origin_hop(err, current):
    """3xx 的下一跳；跨域就当作没有，公网访问到这里为止。"""
    if err.code not in (301, 302, 303, 307, 308):
        return None
    location = err.headers.get("Location") if err.headers else None
    if not location:
        return None
    nxt = urllib.parse.urljoin(current, location)
    if urllib.parse.urlsplit(nxt).netloc != urllib.parse.urlsplit(current).netloc:
        return None
    return nxt


def asset_paths(body):
    """首页引用的本站 js/css；外部链接与 data URI 不算。"""
    out = []
    for raw in ASSET_RE.findall(body or ""):
        ref = raw.strip()
        if not ref or ref.startswith(("data:", "blob:", "//", "#")):
            continue
        parts = urllib.parse.urlsplit(ref)
        if parts.scheme and parts.scheme not in ("http", "https"):
            continue
        if parts.scheme and parts.netloc:
            continue
        path = parts.path
        if not path.lower().endswith(CSS_JS_SUFFIXES) or path.lower().endswith(
                SOURCE_SUFFIXES):
            continue
        if path not in out:
            out.append(path)
    return out[:MAX_ASSETS]


def source_refs(body):
    """页面引用了源码文件（浏览器看不懂的那些）——源码目录被当成产物发布了。"""
    out = []
    for raw in ASSET_RE.findall(body or ""):
        path = urllib.parse.urlsplit(raw.strip()).path.lower()
        if path.endswith(SOURCE_SUFFIXES) or path.startswith("/src/"):
            if raw not in out:
                out.append(raw.strip())
    return out[:4]


def diagnose_root(root, entry):
    """首页观察结果 → 信号列表（纯函数，不碰网络）。"""
    if root.get("error"):
        # 本机解析器跟不上，不代表访客打不开：边缘 IP 直连有响应就不该报"死"
        if root.get("edge_status"):
            return [_sig("dns_slow", "边缘直连返回 HTTP %d" % root["edge_status"])]
        return [_sig("unreachable", root["error"])]
    status = root.get("status") or 0
    body = (root.get("body") or "")
    low = body.lower()
    out = []
    if status in (401, 403):
        if entry.get("proxy_port") and upstream.host_mode(entry) == "loopback":
            out.append(_sig("host_rejected", detail=str(status)))
        elif entry.get("proxy_port"):
            out.append(_sig("auth_required", str(status)))
        else:
            out.append(_sig("direct_403", str(status)))
    elif status == 530:
        # 530 是 Cloudflare 边缘自己造的：这台机器上没有活着的服务端连上来
        out.append(_sig("tunnel_down", str(status)))
    elif status >= 500:
        out.append(_sig("server_error", str(status)))
    elif status == 404:
        out.append(_sig("not_found", str(status)))
    elif status in (301, 302, 303, 307, 308):
        out.append(_sig("redirect_out",
                        _header(root, "Location") or ("HTTP %d" % status)))
    if "/__panweb/login" in low:
        out.append(_sig("own_pin_gate"))
    elif 'type="password"' in low or "type='password'" in low:
        out.append(_sig("app_login"))
    if 200 <= status < 300 and root.get("length", 0) < 120 \
            and "json" not in (_header(root, "Content-Type") or "").lower():
        out.append(_sig("blank_page"))
    if not out:
        out.append(_sig("looks_good", str(status)))
    return out


def check_assets(url, body, timeout=CHECK_TIMEOUT, host=None):
    """首页引用的 js/css 逐个探一下——壳页最常见的死法就是资源 404。"""
    base = urllib.parse.urlsplit(url)
    missing = []
    for path in asset_paths(body):
        target = "%s://%s%s" % (base.scheme, base.netloc,
                                path if path.startswith("/") else "/" + path)
        res = probe(target, host=host, timeout=min(timeout, 4), hops=0)
        if res.get("status") and res["status"] >= 400:
            missing.append(path)
    return missing


def ws_probe(url, host=None, timeout=CHECK_TIMEOUT, path="/"):
    """按访客视角做一次 WebSocket 握手；只看 101，不搬数据。"""
    parts = urllib.parse.urlsplit(url)
    tls = parts.scheme == "https"
    port = parts.port or (443 if tls else 80)
    hostname = parts.hostname or "127.0.0.1"
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = ["GET %s HTTP/1.1" % path,
             "Host: %s" % (host or parts.netloc or hostname),
             "Upgrade: websocket", "Connection: Upgrade",
             "Sec-WebSocket-Version: 13", "Sec-WebSocket-Key: %s" % key]
    sock = None
    try:
        sock = socket.create_connection((hostname, port), timeout)
        if tls:
            sock = ssl.create_default_context().wrap_socket(
                sock, server_hostname=hostname)
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1", "replace"))
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(512)
            if not chunk:
                break
            head += chunk
    except OSError as e:
        return {"ok": False, "status": None,
                "error": "%s: %s" % (type(e).__name__, e)}
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    m = re.match(rb"HTTP/[\d.]+ (\d{3})", head)
    return {"ok": bool(m) and int(m.group(1)) == 101,
            "status": int(m.group(1)) if m else None, "error": None}


def host_evidence(entry, url, visitor_host=None, timeout=4.0):
    """本机上游分别收两种 Host：只有"本机被拒、公网能过"才算证据。

    这一步绕开代理直接问应用，是为了把"应用拒绝本机 Host"和"应用本来就要登录"
    分开——只有前者改成 tunnel 模式才有救，后者改了也是 403。
    """
    if entry.get("kind") == "pages":
        return None
    port = entry_port(entry) or 0
    public_host = visitor_host or urllib.parse.urlsplit(url).netloc
    if not port or not public_host:
        return None
    root = urllib.parse.urlsplit(url)
    base = "http://127.0.0.1:%d%s" % (port, root.path or "/")
    local = probe(base, host="127.0.0.1:%d" % port, timeout=timeout, hops=0)
    public = probe(base, host=public_host, timeout=timeout, hops=0)
    if local.get("error") or public.get("error"):
        return None
    if public["status"] and local["status"] and public["status"] < 400 \
            and local["status"] >= 400:
        return {"local": local["status"], "public": public["status"]}
    return None


def _save_check(entry_id, check):
    with state_lock():
        entries = load_state()
        for e in entries:
            if e.get("id") == entry_id:
                e["check"] = check
                save_state(entries)
                return True
        return False


def _header(root, name):
    for k, v in (root.get("headers") or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _verdict(signals):
    bad = [s for s in signals if s["severity"] == "bad"]
    if bad:
        return "blocked", bad[0]["label"]
    warn = [s for s in signals if s["severity"] == "warn"]
    if warn:
        return "warn", "、".join(s["label"] for s in warn)[:80]
    return "ok", "访客现在能正常打开"


def core_check(entry_id, auto_fix=True, visitor_host=None,
               timeout=CHECK_TIMEOUT, budget=CHECK_BUDGET):
    """自检一个发布；结论存进条目的 check 字段，控制台和分享页都用它。"""
    entry = find_entry(entry_id)
    entry_id = entry["id"]
    url = entry_public_url(entry, load_domain() or {}) or entry.get("url") or ""
    if not url:
        raise PanwebError(2, "invalid_argument", "这个发布还没有公网网址")
    deadline = time.time() + budget
    host = visitor_host or urllib.parse.urlsplit(url).netloc
    fixes = []
    root = probe(url, host=host, timeout=timeout)
    if root.get("error"):
        root["edge_status"] = pinned_status(url, timeout=min(timeout, 8))
    signals = diagnose_root(root, entry)

    if (auto_fix and any(s["code"] == "host_rejected" for s in signals)
            and time.time() < deadline):
        evidence = host_evidence(entry, url, visitor_host=host,
                                 timeout=min(timeout, 4))
        if evidence:
            upstream.set_host_mode(entry_id, "tunnel")
            entry["host_mode"] = "tunnel"
            fixes.append("Host 模式已改为「公网域名」（本机上游对本机 Host 返回 %d，"
                         "对公网域名返回 %d）"
                         % (evidence["local"], evidence["public"]))
            time.sleep(ENTRY_CACHE_WAIT)
            root = probe(url, host=host, timeout=timeout)
            signals = diagnose_root(root, entry)
            if root.get("status") in (401, 403):
                upstream.set_host_mode(entry_id, "loopback")
                entry["host_mode"] = "loopback"
                fixes.append("试过公网域名 Host，应用仍然拒绝；已退回默认模式"
                             "（403 来自应用自己的规则）")
                signals = [s for s in signals if s["code"] != "host_rejected"]
                signals.insert(0, _sig("auth_required", str(root["status"])))

    if time.time() < deadline and 200 <= (root.get("status") or 0) < 300:
        missing = check_assets(url, root["body"], host=host,
                               timeout=min(timeout, 4))
        srcs = source_refs(root["body"])
        if srcs:
            signals.append(_sig("uncompiled_source", srcs[0]))
        if missing:
            signals.append(_sig("asset_404", str(len(missing))))
            signals[-1]["detail"] = "、".join(missing[:3])
        if time.time() < deadline and "new websocket(" in root["body"].lower():
            ws = ws_probe(url, host=host, timeout=min(timeout, 4))
            if not ws["ok"]:
                signals.append(_sig("ws_blocked",
                                    str(ws.get("status") or ws.get("error") or "")))

    verdict, summary = _verdict(signals)
    check = {"ts": time.time(), "verdict": verdict, "summary": summary,
             "status": root.get("status"), "signals": signals, "fixes": fixes,
             "url": url}
    _save_check(entry_id, check)
    if fixes or verdict == "blocked":
        log_activity("check", "自检「%s」：%s" % (_entry_name(entry_id), summary),
                     url)
    return check


_RUNNING = set()
_RUNNING_LOCK = threading.Lock()


def schedule_check(entry_id, delay=1.2):
    """发布后在后台自检；同一时刻一个条目只跑一次，控制台 4 秒刷新会自己拿到结论。"""
    with _RUNNING_LOCK:
        if entry_id in _RUNNING:
            return False
        _RUNNING.add(entry_id)

    def run():
        try:
            time.sleep(delay)
            core_check(entry_id)
        except Exception as e:  # noqa: BLE001 - 后台自检不能拖垮发布者
            log_activity("check", "自检「%s」失败：%s" % (entry_id, e))
        finally:
            with _RUNNING_LOCK:
                _RUNNING.discard(entry_id)

    threading.Thread(target=run, daemon=True).start()
    return True


def _fresh_check(entry_id, since):
    for entry in load_state():
        if entry.get("id") != entry_id:
            continue
        check = entry.get("check") or {}
        try:
            stamp = float(check.get("ts") or 0.0)
        except (TypeError, ValueError):
            return None
        return check if stamp >= since else None
    return None


def await_check(entry_id, since=0.0, timeout=CHECK_BUDGET + ENTRY_CACHE_WAIT):
    """等后台自检把结论落进 state；拿不到就自己跑一次，命令行一定有话说。

    ``since`` 传发布前的时刻可以只认这次发布写出的结论。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        check = _fresh_check(entry_id, since)
        if check:
            return check
        time.sleep(0.2)
    return core_check(entry_id)
