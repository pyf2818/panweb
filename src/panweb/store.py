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
              runtime.SECRETS_DIR):
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


def load_state():
    return _load_json(runtime.STATE_FILE, [])


def save_state(entries):
    save_json(runtime.STATE_FILE, entries)


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
