"""匿名访问记录、聚合统计与访客到达通知。"""
import collections
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse

from . import runtime
from .store import ensure_private_dir, load_meta, load_state

_VISIT_KEY_CACHE = {"dir": None, "key": None}
_VISIT_KEY_LOCK = threading.Lock()
BOT_UA_RE = re.compile(
    r"(bot|crawler|spider|preview|facebookexternalhit|slack|discord|telegram|"
    r"whatsapp|skype|curl/|wget/|python-requests|headlesschrome|phantomjs)",
    re.I)


def _visit_key():
    """访问指纹密钥：HMAC 后只存短哈希，无法从记录反推原始 IP。"""
    with _VISIT_KEY_LOCK:
        if _VISIT_KEY_CACHE["dir"] == runtime.SECRETS_DIR \
                and _VISIT_KEY_CACHE["key"]:
            return _VISIT_KEY_CACHE["key"]
        ensure_private_dir(runtime.SECRETS_DIR)
        path = os.path.join(runtime.SECRETS_DIR, "visits.key")
        key = None
        try:
            with open(path, "r", encoding="ascii") as f:
                key = bytes.fromhex(f.read().strip())
        except (OSError, ValueError):
            key = None
        if not key:
            key = secrets.token_bytes(32)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="ascii") as f:
                f.write(key.hex())
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, path)
        _VISIT_KEY_CACHE.update(dir=runtime.SECRETS_DIR, key=key)
        return key


def _hash_ip(ip):
    try:
        key = _visit_key()
    except OSError:
        key = b"panweb-visits"
    return hmac.new(key, (ip or "").encode("utf-8", "replace"),
                    hashlib.sha256).hexdigest()[:16]


def _is_bot(ua):
    return bool(BOT_UA_RE.search(ua or ""))


def _visit_browser(ua):
    ua = (ua or "").lower()
    if "micromessenger" in ua:
        return "微信"
    if "edg/" in ua:
        return "Edge"
    if "chrome/" in ua or "crios/" in ua:
        return "Chrome"
    if "firefox/" in ua or "fxios/" in ua:
        return "Firefox"
    if "safari/" in ua or "applewebkit" in ua:
        return "Safari"
    if "curl/" in ua:
        return "命令行"
    return "其他"


def _ua_device(ua):
    ua = (ua or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "平板"
    if "mobile" in ua or "iphone" in ua or "android" in ua:
        return "移动端"
    return "桌面端"


def _clean_country(value):
    value = (value or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}", value) and value not in ("XX", "T1"):
        return value
    return ""


def _clean_referrer(value):
    try:
        host = urllib.parse.urlsplit(value or "").hostname or ""
    except ValueError:
        host = ""
    return host.lower()[:80]


def _visits_path(entry_id, ts=None):
    """按天分文件：目录再多访问量也只增长单日文件，聚合不再按 2MB 截断。"""
    when = time.time() if ts is None else ts
    day = time.strftime("%Y%m%d", time.localtime(when))
    return os.path.join(runtime.VISITS_DIR, "%s-%s.jsonl" % (entry_id, day))


def _iter_records(path):
    """逐行读 JSONL；不把整个文件读进内存（单日文件可能很大）。"""
    try:
        with open(path, "rb") as f:
            for raw in f:
                try:
                    yield json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
    except OSError:
        return


def _visit_files(entry_id, since):
    """挑出窗口可能覆盖的日志：分天文件按日期过滤，旧版单文件继续兼容。"""
    names = []
    try:
        names = os.listdir(runtime.VISITS_DIR)
    except OSError:
        pass
    prefix = "%s-" % entry_id
    files = []
    for name in names:
        if not name.endswith(".jsonl") or name.startswith("._"):
            continue
        if name == "%s.jsonl" % entry_id:
            files.append((float("-inf"), os.path.join(runtime.VISITS_DIR, name)))
            continue
        if not name.startswith(prefix):
            continue
        day = name[len(prefix):-6]
        try:
            day_start = time.mktime(time.strptime(day, "%Y%m%d"))
        except ValueError:
            continue
        if day_start + 86400 > since:
            files.append((day_start, os.path.join(runtime.VISITS_DIR, name)))
    files.sort(key=lambda item: item[0])
    return [path for _, path in files]


def log_visit(entry_id, path, ip, ua, kind="app", referrer="", country=""):
    """记录一次页面访问（JSONL 追加，IP 用 HMAC 匿名化；不存查询串）。

    只记录文档级请求；静态资源/接口/WebSocket/机器人预览不计数。
    """
    ua = ua or ""
    if _is_bot(ua):
        return
    if kind not in ("app", "share"):
        kind = "app"
    try:
        ensure_private_dir(runtime.VISITS_DIR)
        clean = urllib.parse.urlsplit(path).path or "/"
        if clean.startswith(runtime.SHARE_PATH + "/"):
            clean = runtime.SHARE_PATH
        rec = {"ts": round(time.time(), 3), "path": clean[:120],
               "ip": _hash_ip(ip), "kind": kind,
               "device": _ua_device(ua), "browser": _visit_browser(ua)}
        ref = _clean_referrer(referrer)
        if ref:
            rec["ref"] = ref
        ctry = _clean_country(country)
        if ctry:
            rec["country"] = ctry
        fpath = _visits_path(entry_id)
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            os.chmod(fpath, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def aggregate_visits(entry_id, hours=24, recent=15):
    """聚合访问记录 → total/uv/points/last/recent/devices/countries/browsers。"""
    since = time.time() - hours * 3600
    total, ips, points, last, recents = 0, set(), {}, None, []
    devices, browsers, countries, refs = {}, {}, {}, {}
    share_count = app_count = 0
    bucket = 3600 if hours <= 48 else 86400
    n_buckets = int(hours * 3600 // bucket)
    now_bucket = int(time.time() // bucket) * bucket
    start = now_bucket - (n_buckets - 1) * bucket
    recent_items = collections.deque(maxlen=max(1, recent))
    for path in _visit_files(entry_id, since):
        for rec in _iter_records(path):
            ts = rec.get("ts", 0)
            if ts < since:
                continue
            total += 1
            ips.add(rec.get("ip"))
            if (rec.get("kind") or "app") == "share":
                share_count += 1
            else:
                app_count += 1
            key = int(ts // bucket) * bucket
            points[key] = points.get(key, 0) + 1
            last = max(last or 0, ts)
            recent_items.append(rec)
            dev = rec.get("device") or _ua_device(rec.get("ua"))
            devices[dev] = devices.get(dev, 0) + 1
            browser = rec.get("browser") or _visit_browser(rec.get("ua"))
            if browser:
                browsers[browser] = browsers.get(browser, 0) + 1
            country = rec.get("country")
            if country:
                countries[country] = countries.get(country, 0) + 1
            ref = rec.get("ref")
            if ref:
                refs[ref] = refs.get(ref, 0) + 1
    recents = list(recent_items)
    recents.sort(key=lambda r: -r.get("ts", 0))
    for r in recents:
        r["device"] = r.get("device") or _ua_device(r.get("ua"))
        r["browser"] = r.get("browser") or _visit_browser(r.get("ua"))
        r["kind"] = r.get("kind") or "app"
    series = [{"t": start + i * bucket,
               "count": points.get(start + i * bucket, 0)}
              for i in range(n_buckets)]
    return {"total": total, "uv": len(ips), "points": series, "last": last,
            "recent": recents[:recent], "devices": devices,
            "browsers": browsers, "countries": countries, "referrers": refs,
            "share": share_count, "app": app_count, "hours": hours}


def notify_macos(message, subtitle=""):
    """通过 osascript 发系统通知；参数走 argv，避免 AppleScript 注入。"""
    if sys.platform != "darwin":
        return False
    script = ('on run argv\n'
              'display notification (item 1 of argv) with title "panweb" '
              'subtitle (item 2 of argv) sound name "Glass"\n'
              'end run')
    try:
        subprocess.run(["osascript", "-e", script, message or "", subtitle or ""],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5, check=False)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


class VisitNotifier(threading.Thread):
    """监控访问日志，控制台运行时推送访客到达提醒。"""

    def __init__(self, interval=2.0):
        super().__init__(daemon=True, name="panweb-visits")
        self.interval = interval
        self.stop_event = threading.Event()
        self.offsets = {}
        self.recent = collections.deque(maxlen=50)
        self._seen = collections.OrderedDict()
        self._entry_at = {}
        self._last_global = 0.0
        self._lock = threading.Lock()

    def run(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 - 通知失败不影响控制台
                pass

    def stop(self):
        self.stop_event.set()

    def snapshot(self, limit=12):
        with self._lock:
            return list(self.recent)[-limit:][::-1]

    def poll_once(self):
        entries = {e.get("id"): e for e in load_state() if e.get("id")}
        for eid in list(self.offsets):
            if eid not in entries:
                self.offsets.pop(eid, None)
        for eid, entry in entries.items():
            path = _visits_path(eid)
            try:
                size = os.path.getsize(path)
            except OSError:
                self.offsets.setdefault(eid, (path, 0))
                continue
            prev = self.offsets.get(eid)
            if prev is None:
                self.offsets[eid] = (path, size)  # 跳过控制台启动前的历史
                continue
            prev_path, offset = prev
            if prev_path != path:
                offset = 0  # 跨天换了文件，昨天的游标不能套在新文件上
            if size <= offset:
                if size < offset:
                    self.offsets[eid] = (path, size)
                continue
            try:
                with open(path, "rb") as f:
                    f.seek(offset)
                    chunk = f.read()
            except OSError:
                continue
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            data = chunk[:end + 1]
            self.offsets[eid] = (path, offset + len(data))
            for raw in data.splitlines():
                try:
                    rec = json.loads(raw.decode("utf-8", "replace"))
                except ValueError:
                    continue
                kind = rec.get("kind") or "app"
                if kind not in ("share", "app"):
                    continue
                name = entry.get("name") or "应用"
                event = {
                    "id": eid, "name": name, "ts": rec.get("ts"),
                    "kind": kind,
                    "device": rec.get("device") or _ua_device(rec.get("ua")),
                    "browser": rec.get("browser") or _visit_browser(rec.get("ua")),
                    "country": rec.get("country") or "",
                    "path": rec.get("path") or "/",
                }
                with self._lock:
                    self.recent.append(event)
                self._notify(eid, name, event, rec.get("ip") or "")

    def _notify(self, entry_id, name, event, visitor):
        meta = load_meta()
        if meta.get("notify_visits", True) is False:
            return
        grace = (meta.get("owner_grace") or {}).get(entry_id, 0)
        if grace and time.time() < grace:
            return
        now = time.time()
        key = (entry_id, visitor)
        with self._lock:
            last = self._seen.get(key, 0)
            if now - last < 600:
                return
            self._seen[key] = now
            if len(self._seen) > 512:
                for k, ts in list(self._seen.items())[:256]:
                    if now - ts > 600:
                        self._seen.pop(k, None)
            if now - self._entry_at.get(entry_id, 0) < 30:
                return
            if now - self._last_global < 2:
                return
            self._entry_at[entry_id] = now
            self._last_global = now
        if event["kind"] == "share":
            message = "有人打开了「%s」的分享页" % name
        else:
            message = "有人正在看「%s」" % name
        subtitle = " · ".join(x for x in (event.get("device"),
                                          event.get("country"),
                                          event.get("browser")) if x)
        notify_macos(message, subtitle)
