"""上游兼容层：Host 透传模式与访问上游所需的鉴权头。

panweb 的口令只守着公网入口；被发布的应用如果自己还要登录，就得由这一层把凭据
补上。密钥和访问口令一样存在 ``secrets/``（0600），绝不写进 ``state.json`` ——
状态会被控制台、CLI 和菜单栏原样带出，密钥一旦进去就藏不住。
"""
import base64
import ipaddress
import json
import os
import re

from . import runtime
from .errors import PanwebError
from .store import (ensure_private_dir, load_state, save_json, save_state,
                    state_lock)

HOST_MODES = ("loopback", "tunnel")
HOST_MODE_LABELS = {
    "loopback": "本机地址（默认）",
    "tunnel": "公网域名（应用校验 Host 时用）",
}
AUTH_KINDS = ("bearer", "basic", "header")
AUTH_LABELS = {"bearer": "Bearer 令牌", "basic": "Basic 用户名/密码",
               "header": "自定义请求头"}

# 逐跳头不能透传：连接由代理自己终结。
DROP_HEADERS = frozenset(("host", "connection", "keep-alive", "proxy-connection",
                          "transfer-encoding", "upgrade"))
WS_KEEP = frozenset(("connection", "upgrade"))
# 访客可以随手伪造这些头；代理必须丢掉入站值再写自己的，否则日志里的 IP
# 和上游看到的来源都不可信，还会出现一个头里两份值的歧义。
CLIENT_HEADERS = frozenset(("x-forwarded-for", "x-forwarded-proto",
                            "x-forwarded-host", "x-real-ip", "forwarded",
                            "cf-connecting-ip", "true-client-ip"))
# 注入的鉴权头也不能碰这些：Content-Length 由代理按实际请求体生成，
# 被固定值覆盖会让请求帧错开，后面的头就会被当成 body。
AUTH_FORBIDDEN_HEADERS = DROP_HEADERS | frozenset(("content-length",))
_TOKEN_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def auth_file_path(entry_id):
    return os.path.join(runtime.SECRETS_DIR, "%s.auth.json" % entry_id)


def host_mode(entry):
    mode = (entry or {}).get("host_mode")
    return mode if mode in HOST_MODES else "loopback"


def _clean(value, label, limit, ascii_only=True):
    text = str(value or "").strip()
    if not text:
        raise PanwebError(2, "invalid_argument", "%s不能为空" % label)
    if len(text) > limit:
        raise PanwebError(2, "invalid_argument",
                          "%s太长了（最多 %d 个字符）" % (label, limit))
    # 换行与控制字符能把一个值变成多条头，注入的正是这条路径。
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        raise PanwebError(2, "invalid_argument",
                          "%s不能包含换行或控制字符" % label)
    if ascii_only and any(ord(c) > 126 for c in text):
        raise PanwebError(2, "invalid_argument", "%s只能用可见 ASCII 字符" % label)
    return text


def normalize_host_mode(mode):
    mode = str(mode or "").strip().lower()
    if mode not in HOST_MODES:
        raise PanwebError(2, "invalid_argument",
                          "Host 模式只有 loopback 和 tunnel 两种")
    return mode


def normalize_auth(kind, token="", user="", password="", name="", value=""):
    kind = str(kind or "").strip().lower()
    if kind not in AUTH_KINDS:
        raise PanwebError(2, "invalid_argument",
                          "上游鉴权类型只支持 bearer、basic、header")
    if kind == "bearer":
        return {"kind": "bearer", "token": _clean(token, "令牌", 512)}
    if kind == "basic":
        # Basic 走 base64，用户名/密码允许非 ASCII；其余头值必须 ASCII 可见。
        return {"kind": "basic",
                "user": _clean(user, "用户名", 128, ascii_only=False),
                "password": _clean(password, "密码", 256, ascii_only=False)}
    header_name = _clean(name, "头名称", 128)
    if not _TOKEN_RE.match(header_name):
        raise PanwebError(2, "invalid_argument",
                          "头名称只能由字母、数字和 - _ . + 等字符组成")
    if header_name.lower() in AUTH_FORBIDDEN_HEADERS:
        raise PanwebError(2, "invalid_argument",
                          "「%s」是连接层请求头，不能由 panweb 覆盖" % header_name)
    return {"kind": "header", "name": header_name,
            "value": _clean(value, "头值", 512)}


def auth_header_of(rec):
    """记录 → (头名, 头值)；记录不合法时返回 None 而不是抛错。"""
    kind = (rec or {}).get("kind")
    if kind == "bearer":
        token = rec.get("token") or ""
        return ("Authorization", "Bearer %s" % token) if token else None
    if kind == "basic":
        raw = ("%s:%s" % (rec.get("user") or "", rec.get("password") or ""))
        pair = ("Authorization",
                "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii"))
        return pair if rec.get("user") else None
    if kind == "header":
        name = rec.get("name") or ""
        value = rec.get("value") or ""
        if not value or name.lower() in AUTH_FORBIDDEN_HEADERS \
                or not _TOKEN_RE.match(name):
            return None
        return (name, value)
    return None


def read_auth(entry_id):
    """读取上游凭据；文件缺失或格式不对都当作没有配置。"""
    if not entry_id:
        return None
    try:
        with open(auth_file_path(entry_id), "r", encoding="utf-8") as f:
            rec = json.load(f)
    except (ValueError, OSError):
        return None
    return rec if isinstance(rec, dict) and rec.get("kind") in AUTH_KINDS else None


def auth_header(entry_id):
    return auth_header_of(read_auth(entry_id))


def describe_auth(entry_id):
    """给界面看的脱敏描述——只有种类，没有密钥。"""
    rec = read_auth(entry_id)
    if not rec:
        return None
    info = {"kind": rec["kind"], "label": AUTH_LABELS.get(rec["kind"], rec["kind"])}
    if rec["kind"] == "basic":
        info["user"] = rec.get("user") or ""
    elif rec["kind"] == "header":
        info["name"] = rec.get("name") or ""
    return info


def _tag_entry(entry_id, kind):
    with state_lock():
        entries = load_state()
        for e in entries:
            if e.get("id") != entry_id:
                continue
            if kind:
                e["auth_kind"] = kind
            else:
                e.pop("auth_kind", None)
            save_state(entries)
            return e.get("name")
    return None


def set_host_mode(entry_id, mode):
    mode = normalize_host_mode(mode)
    with state_lock():
        entries = load_state()
        for e in entries:
            if e.get("id") != entry_id:
                continue
            e["host_mode"] = mode
            save_state(entries)
            return e.get("name")
    raise PanwebError(2, "not_found", "没有找到匹配「%s」的发布" % entry_id)


def set_auth(entry_id, rec):
    ensure_private_dir(runtime.SECRETS_DIR)
    save_json(auth_file_path(entry_id), rec)
    return _tag_entry(entry_id, rec["kind"])


def clear_auth(entry_id):
    remove_auth_file(entry_id)
    return _tag_entry(entry_id, None)


def remove_auth_file(entry_id):
    try:
        os.remove(auth_file_path(entry_id))
    except OSError:
        pass


def forward_headers(items, client_ip, host_value=None, public_host=None,
                   auth=None, websocket=False):
    """浏览器请求头 → 上游请求头，返回 (名, 值) 列表。

    ``host_value`` 是上游应该看到的 Host——tunnel 模式下就是访客正在用的公网域名
    （校验 Host 做 CSRF/重绑定防护的应用只认这个），否则退回本机地址，兼容只肯
    服务 localhost 的开发服务器。公网域名同时记进 ``X-Forwarded-Host``。

    ``websocket=True`` 时留下 Upgrade/Connection：握手头说的就是"这一跳要升级"，
    滤掉它上游永远不会回 101。
    """
    drop = set(DROP_HEADERS - WS_KEEP if websocket else DROP_HEADERS)
    drop |= CLIENT_HEADERS
    if auth:
        # 配了上游凭据时必须由 panweb 说了算，访客带来的同名头不能留下。
        drop.add(auth[0].lower())
    pairs = [(k, v) for k, v in items if k.lower() not in drop]
    origin = public_host or _first_value(items, "host")
    if origin:
        pairs.append(("X-Forwarded-Host", origin))
    if host_value:
        pairs.append(("Host", host_value))
    pairs.append(("X-Forwarded-For", client_ip or ""))
    pairs.append(("X-Real-IP", client_ip or ""))
    pairs.append(("X-Forwarded-Proto", "https"))
    if auth:
        pairs.append(auth)
    return pairs


def _valid_ip(raw):
    text = (raw or "").strip().strip('"')
    if not text or len(text) > 64:
        return ""
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return ""
    return text


def client_ip(headers, peer=""):
    """从一串可能被伪造的头里取真实访客 IP，失败就退回对端地址。

    优先 Cloudflare 注入的 CF-Connecting-IP（公网流量一定有），但不只认它：
    其它入口/代理给出的头也接受；所有候选都要通过 IP 语法校验才算数。
    """
    for name in ("CF-Connecting-IP", "True-Client-IP", "X-Real-IP"):
        value = _valid_ip(headers.get(name) or "")
        if value:
            return value
    for candidate in (headers.get("X-Forwarded-For") or "").split(","):
        value = _valid_ip(candidate)
        if value:
            return value
    return _valid_ip(peer) or peer or ""


def _first_value(items, name):
    for k, v in items:
        if k.lower() == name:
            return v
    return None
