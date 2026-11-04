"""访问口令：随机盐 + SHA-256、旧格式迁移、失败限流。"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from . import runtime
from .errors import PanwebError
from .store import (ensure_private_dir, load_state, save_json, save_state,
                    state_lock)


def normalize_pin(pin):
    pin = (pin or "").strip()
    if not pin:
        return None
    if len(pin) < 4:
        raise PanwebError(2, "invalid_argument", "访问口令至少 4 位")
    if len(pin) > 32:
        raise PanwebError(2, "invalid_argument", "访问口令最多 32 位")
    return pin


def pin_file_path(entry_id):
    return os.path.join(runtime.SECRETS_DIR, "%s.pin" % entry_id)


def read_pin_record(entry_id):
    """新格式 {salt,hash,session}；旧格式返回 {"legacy": 明文}。"""
    try:
        with open(pin_file_path(entry_id), "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        rec = json.loads(raw)
        if isinstance(rec, dict) and rec.get("salt") and rec.get("hash") \
                and rec.get("session"):
            return {"salt": str(rec["salt"]), "hash": str(rec["hash"]),
                    "session": str(rec["session"])}
    except ValueError:
        pass
    return {"legacy": raw}


def write_pin(entry_id, pin):
    ensure_private_dir(runtime.SECRETS_DIR)
    if not pin:
        try:
            os.remove(pin_file_path(entry_id))
        except OSError:
            if os.path.exists(pin_file_path(entry_id)):
                return
        _sync_pinned(entry_id, False)
        return
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()
    session = secrets.token_hex(24)
    save_json(pin_file_path(entry_id),
              {"salt": salt, "hash": digest, "session": session})
    _sync_pinned(entry_id, True)


def _sync_pinned(entry_id, pinned):
    """口令文件和状态里的 pinned 徽标必须同时改，否则卡片会长期说谎。"""
    with state_lock():
        entries = load_state()
        changed = False
        for entry in entries:
            if entry.get("id") == entry_id and bool(entry.get("pinned")) != pinned:
                entry["pinned"] = pinned
                changed = True
        if changed:
            save_state(entries)


def legacy_pin_token(entry_id, pin):
    return hashlib.sha256(("%s:%s" % (entry_id, pin)).encode()).hexdigest()[:32]


def pin_session(entry_id):
    rec = read_pin_record(entry_id)
    if not rec:
        return None
    if "legacy" in rec:
        return legacy_pin_token(entry_id, rec["legacy"])
    return rec["session"]


def verify_pin(entry_id, candidate):
    """校验口令；旧格式校验成功后自动升级为加盐哈希。"""
    rec = read_pin_record(entry_id)
    if not rec:
        return True
    if "legacy" in rec:
        ok = hmac.compare_digest(rec["legacy"], candidate)
        if ok:
            write_pin(entry_id, candidate)
        return ok
    digest = hashlib.sha256((rec["salt"] + candidate).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, rec["hash"])


def migrate_legacy_pins():
    """升级旧明文口令；清理已停止应用遗留的口令文件（保留 1 小时宽限）。"""
    if not os.path.isdir(runtime.SECRETS_DIR):
        return
    state_ids = {e.get("id") for e in load_state()}
    now = time.time()
    try:
        names = os.listdir(runtime.SECRETS_DIR)
    except OSError:
        return
    for name in names:
        if not name.endswith(".pin"):
            continue
        entry_id = name[:-4]
        path = os.path.join(runtime.SECRETS_DIR, name)
        rec = read_pin_record(entry_id)
        if entry_id not in state_ids:
            try:
                old = now - os.path.getmtime(path) > 3600
            except OSError:
                old = True
            if old or not rec:
                try:
                    os.remove(path)
                except OSError:
                    pass
        elif rec and "legacy" in rec:
            write_pin(entry_id, rec["legacy"])


PIN_FAILS = {}
PIN_LOCK = threading.Lock()


def pin_retry_after(entry_id):
    now = time.time()
    with PIN_LOCK:
        fails = [t for t in PIN_FAILS.get(entry_id, []) if now - t < 600]
        PIN_FAILS[entry_id] = fails
        if len(fails) >= 8:
            return max(1, int(600 - (now - fails[0])))
        return 0


def pin_record_fail(entry_id):
    with PIN_LOCK:
        PIN_FAILS.setdefault(entry_id, []).append(time.time())


def pin_clear_fail(entry_id):
    with PIN_LOCK:
        PIN_FAILS.pop(entry_id, None)
