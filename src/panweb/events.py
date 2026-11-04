"""发布变更事件流：只追加、按天分文件、从文件尾读取。

事件日志是旁路：写入失败只留一条 activity 告警，绝不把异常抛回发布流程。
details 只接受白名单键，未知字段直接丢弃；URL 去掉 query/fragment，
避免 share token 之类的凭据被顺手写进时间线。
"""
import contextlib
import json
import os
import re
import time
import urllib.parse

from . import runtime
from .store import ensure_private_dir, json_lock, log_activity

EVENT_TYPES = frozenset(("publish", "restart", "url_change", "pin_change",
                         "expire", "stop", "error"))
SAFE_DETAIL_KEYS = frozenset(("url_before", "url_after", "expires_at",
                             "reason", "source", "port", "kind", "name"))
READ_BLOCK = 8192
MAX_LIMIT = 200
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SENSITIVE_RE = re.compile(
    r"(?i)(?:pin|token|authorization|password|secret)\s*[=:]\s*\S+"
    r"|bearer\s+\S+")
_DAY_RE = re.compile(r"^\d{8}\.jsonl$")


def _day_name(ts=None):
    return time.strftime("%Y%m%d", time.localtime(ts or time.time()))


def _clean(text, limit=300):
    text = _CONTROL_RE.sub(" ", "" if text is None else str(text)).strip()
    if _SENSITIVE_RE.search(text):
        text = _SENSITIVE_RE.sub("[已隐藏]", text).strip()
    return text[:limit]


def _safe_url(value):
    """只保留 scheme/host/port/path；带凭据或查询串一律剥掉。"""
    try:
        parts = urllib.parse.urlsplit(str(value))
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    if not parts.scheme or not host:
        return ""
    if port:
        host = "%s:%d" % (host, port)
    return "%s://%s%s" % (parts.scheme, host, parts.path)


def _clean_value(key, value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    if key in ("url_before", "url_after"):
        return _safe_url(value)
    return _clean(value)


def _append_line(record):
    ensure_private_dir(runtime.EVENTS_DIR)
    path = os.path.join(runtime.EVENTS_DIR, _day_name() + ".jsonl")
    line = json.dumps(record, ensure_ascii=False,
                      separators=(",", ":")) + "\n"
    with json_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _warn(error):
    try:
        log_activity("system", "事件日志写入失败：%s" % _clean(error, 120))
    except Exception:  # noqa: BLE001 - 告警失败也不能反噬主流程
        pass


def log_event(entry_id, type, summary, **details):
    """记录一条事件；返回是否落盘，任何异常都吞掉并留告警。"""
    try:
        entry_id = _clean(entry_id, 100)
        if not entry_id or type not in EVENT_TYPES:
            return False
        payload = {}
        for key in SAFE_DETAIL_KEYS:
            if key not in details:
                continue
            value = _clean_value(key, details[key])
            if value is not None or details[key] is None:
                payload[key] = value
        record = {"ts": time.time(), "entry_id": entry_id, "type": type,
                  "summary": _clean(summary, 160)}
        if payload:
            record["details"] = payload
        _append_line(record)
        return True
    except Exception as e:  # noqa: BLE001 - 旁路日志不许影响主流程
        _warn(e)
        return False


def _day_files():
    try:
        names = os.listdir(runtime.EVENTS_DIR)
    except OSError:
        return []
    names = [n for n in names if _DAY_RE.match(n)]
    return [os.path.join(runtime.EVENTS_DIR, n)
            for n in sorted(names, reverse=True)]


def _reverse_lines(path, block=READ_BLOCK):
    """从文件尾按块反向读，避免把历史事件全量读进内存。"""
    with open(path, "rb") as f:
        pos = os.path.getsize(path)
        buf = b""
        while pos > 0:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
            lines = buf.split(b"\n")
            if pos > 0:
                buf = lines[0]
                complete = lines[1:]
            else:
                buf = b""
                complete = lines
            for line in reversed(complete):
                if line:
                    yield line
        if buf:
            yield buf


def read_events(entry_id=None, limit=30):
    """返回最新在前的最近事件；limit 夹在 1..200。"""
    try:
        limit = min(max(int(limit), 1), MAX_LIMIT)
    except (TypeError, ValueError):
        limit = 30
    found = []
    for path in _day_files():
        try:
            with contextlib.closing(_reverse_lines(path)) as lines:
                for raw in lines:
                    try:
                        row = json.loads(raw.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(row, dict) or "ts" not in row:
                        continue
                    if entry_id and row.get("entry_id") != entry_id:
                        continue
                    found.append(row)
                    if len(found) >= limit:
                        return found
        except OSError:
            continue
    return found
