"""私有目录、原子 JSON、跨进程状态锁与状态/元数据读写。"""
import contextlib
import json
import os
import tempfile
import threading
import time

from . import runtime

try:
    import fcntl
except ImportError:  # pragma: no cover - panweb 只支持 macOS/Linux
    fcntl = None


def ensure_private_dir(path):
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def ensure_private_dirs():
    for d in (runtime.HOME_DIR, runtime.LOG_DIR, runtime.VISITS_DIR,
              runtime.SECRETS_DIR, runtime.FORWARDERS_DIR):
        ensure_private_dir(d)


_STATE_THREAD_LOCK = threading.RLock()
_STATE_LOCAL = threading.local()


@contextlib.contextmanager
def state_lock():
    """跨线程/跨进程互斥，保护 state.json 的读-改-写（同线程可重入）。"""
    _STATE_THREAD_LOCK.acquire()
    depth = getattr(_STATE_LOCAL, "depth", 0)
    if depth:
        _STATE_LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _STATE_LOCAL.depth = depth
            _STATE_THREAD_LOCK.release()
        return
    lockf = None
    try:
        ensure_private_dir(runtime.HOME_DIR)
        lockf = open(runtime.STATE_LOCK_FILE, "a+", encoding="utf-8")
        if fcntl:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        _STATE_LOCAL.depth = 1
        yield
    finally:
        _STATE_LOCAL.depth = 0
        if lockf:
            if fcntl:
                try:
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            lockf.close()
        _STATE_THREAD_LOCK.release()


_JSON_LOCKS = {}
_JSON_LOCKS_GUARD = threading.Lock()


@contextlib.contextmanager
def json_lock(path):
    """跨线程/跨进程互斥，保护任意 JSON 文件的读-改-写。

    state.json 用 state_lock；activity/meta 这类非 state 文件也有人在
    CLI、控制台和菜单栏之间并发读写，同样需要一把锁。
    """
    path = os.path.abspath(path)
    with _JSON_LOCKS_GUARD:
        lock = _JSON_LOCKS.setdefault(path, threading.RLock())
    lock.acquire()
    lockf = None
    try:
        ensure_private_dir(os.path.dirname(path))
        lockf = open(path + ".lock", "a+", encoding="utf-8")
        if fcntl:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if lockf:
            if fcntl:
                try:
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            lockf.close()
        lock.release()


def save_json(path, data):
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".%s." % os.path.basename(path),
                               suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return default


_STATE_ISSUE = None
STATE_SCHEMA_VERSION = 2
_STATE_TOP_KEYS = ("schema_version", "entries")


def _entries_from_raw(data):
    """兼容 v1（顶层数组）与 v2（{"schema_version", "entries"}）。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return data["entries"]
    return None


def _top_extras(data):
    """未知顶层字段原样保留，不顺手清理用户数据。"""
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k not in _STATE_TOP_KEYS}


def _as_source_port(value):
    if isinstance(value, bool):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _migrate_entry(entry):
    if not isinstance(entry, dict) or "target" not in entry:
        return entry
    out = {k: v for k, v in entry.items() if k != "target"}
    target = entry["target"]
    if out.get("kind") == "pages":
        if "folder" not in out and isinstance(target, str) and target:
            out["folder"] = target
        return out
    port = _as_source_port(target)
    if port is not None:
        out.setdefault("port", port)
    elif isinstance(target, str) and target:
        # 历史 run 条目可能把目录放在 target 里；其余脏数据直接丢弃。
        out.setdefault("folder", target)
    return out


def migrate_entries(entries):
    """v1 的 target 转成 v2 的 port/folder；纯函数，反复执行无副作用。"""
    if not isinstance(entries, list):
        return []
    return [_migrate_entry(e) for e in entries if isinstance(e, dict)]


def _backup_legacy_state(data):
    """旧格式首次被覆盖前留一份；已存在则不覆盖，失败不阻断读取。"""
    backup = runtime.STATE_FILE + ".v1-backup"
    if os.path.exists(backup):
        return backup
    entries = _entries_from_raw(data) or []
    legacy = isinstance(data, list) or (
        isinstance(data, dict)
        and data.get("schema_version") != STATE_SCHEMA_VERSION)
    if not legacy and not any(isinstance(e, dict) and "target" in e
                              for e in entries):
        return ""
    try:
        save_json(backup, data)
    except OSError:
        return ""
    return backup


def scan_legacy_target():
    """检查磁盘上的原始 state 是否还有遗留 target 字段（doctor 用）。"""
    try:
        with open(runtime.STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [e.get("id") or e.get("name") or "?"
            for e in (_entries_from_raw(data) or [])
            if isinstance(e, dict) and "target" in e]


def state_issue():
    """当前状态文件的损坏事件；换到别的 HOME 时自动失效。"""
    if _STATE_ISSUE and _STATE_ISSUE.get("home") == runtime.HOME_DIR:
        return {k: v for k, v in _STATE_ISSUE.items() if k != "home"}
    return None


def load_state():
    global _STATE_ISSUE
    try:
        with open(runtime.STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except ValueError as e:
        return _quarantine_state(e)
    except OSError as e:
        _STATE_ISSUE = {"home": runtime.HOME_DIR, "path": runtime.STATE_FILE,
                        "message": "状态文件无法读取：%s" % e}
        return []
    entries = _entries_from_raw(data)
    if entries is None:
        return []
    _backup_legacy_state(data)
    return migrate_entries(entries)


def _quarantine_state(error):
    global _STATE_ISSUE
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = "%s.corrupt-%s" % (runtime.STATE_FILE, stamp)
    try:
        os.replace(runtime.STATE_FILE, backup)
    except OSError:
        backup = ""
    message = "状态文件损坏（%s）" % error
    if backup:
        message += "，已备份到 %s" % backup
    _STATE_ISSUE = {"home": runtime.HOME_DIR, "path": runtime.STATE_FILE,
                    "message": message}
    try:
        log_activity("system", message +
                     "；发布进程可能仍在运行，确认后可用 panweb stop all 清理")
    except (OSError, ValueError):
        pass
    return []


def save_state(entries):
    extras = {}
    try:
        with open(runtime.STATE_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        existing = None
    if existing is not None:
        extras = _top_extras(existing)
        _backup_legacy_state(existing)
    payload = dict(extras)
    payload["schema_version"] = STATE_SCHEMA_VERSION
    payload["entries"] = list(entries)
    save_json(runtime.STATE_FILE, payload)


def load_activity():
    return _load_json(runtime.ACTIVITY_FILE, [])


def log_activity(kind, text, detail=None):
    with json_lock(runtime.ACTIVITY_FILE):
        items = load_activity()
        items.append({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                      "kind": kind, "text": text, "detail": detail})
        save_json(runtime.ACTIVITY_FILE, items[-200:])


def load_meta():
    return _load_json(runtime.META_FILE, {})


def save_meta(meta):
    save_json(runtime.META_FILE, meta)


def bump_stopped(count):
    if not count:
        return
    with json_lock(runtime.META_FILE):
        meta = load_meta()
        meta["stopped_total"] = meta.get("stopped_total", 0) + count
        save_meta(meta)


def load_domain():
    return _load_json(runtime.DOMAIN_FILE, None)


def save_domain(data):
    save_json(runtime.DOMAIN_FILE, data)
