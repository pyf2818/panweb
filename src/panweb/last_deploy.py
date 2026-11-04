"""停止/到期后的「上次发布」快照：只留展示字段，口令只存布尔，不留密钥。"""
import time

from . import runtime
from .deployment import remaining_text
from .models import (entry_folder, entry_port, entry_public_url,
                     entry_share_url, entry_title)
from .store import json_lock, load_meta, save_meta

SNAPSHOT_KEY = "last_deployments"
MAX_SNAPSHOTS = 5
REASONS = ("user", "expired", "invalid_expires_at", "cleanup")


def target_key(data):
    """同一发布目标的签名：port:3000 / pages:/dir；未知类型返回空串。"""
    if not isinstance(data, dict):
        return ""
    kind = data.get("kind") or ""
    if kind == "port":
        port = entry_port(data)
        return "port:%s" % port if port is not None else ""
    if kind == "pages":
        folder = entry_folder(data)
        return "pages:%s" % folder if folder else ""
    return ""


def _pv(visits):
    if not isinstance(visits, dict):
        return None
    pv = {"total": visits.get("total"), "uv": visits.get("uv"),
          "last": visits.get("last")}
    return pv if pv["total"] is not None or pv["uv"] is not None else None


def snapshot_entry(entry, reason="user", now=None, domain=None, visits=None):
    """把一条已停止条目压成可展示快照；不复制 pin / share_token / 进程号。"""
    if not isinstance(entry, dict) or not entry.get("id"):
        return None
    now = time.time() if now is None else now
    return {
        "id": entry["id"],
        "name": entry.get("name") or "",
        "title": entry_title(entry),
        "kind": entry.get("kind") or "",
        "port": entry_port(entry),
        "folder": entry_folder(entry),
        "url": entry_public_url(entry, domain) or "",
        "share_url": entry_share_url(entry, domain),
        "pinned": bool(entry.get("pinned")),
        "expires_at": entry.get("expires_at"),
        "expires_text": remaining_text(entry.get("expires_at"), now),
        "started": entry.get("started"),
        "stopped_at": now,
        "stop_reason": reason if reason in REASONS else "user",
        "pv": _pv(visits),
        "from_snapshot": True,
    }


def remember_last(entry, reason="user", visits=None, domain=None, now=None):
    """停止/到期时记一条快照；同目标覆盖，最多 MAX_SNAPSHOTS 条，新的在前。"""
    snap = snapshot_entry(entry, reason, now=now, domain=domain, visits=visits)
    if not snap:
        return None
    key = target_key(snap)
    with json_lock(runtime.META_FILE):
        meta = load_meta()
        items = [s for s in meta.get(SNAPSHOT_KEY, []) if isinstance(s, dict)]
        if key:
            items = [s for s in items if target_key(s) != key]
        items = [s for s in items if s.get("id") != snap["id"]]
        items.insert(0, snap)
        meta[SNAPSHOT_KEY] = items[:MAX_SNAPSHOTS]
        save_meta(meta)
    return snap


def load_snapshots(active_entries=None):
    """读快照；已被同目标的新条目顶替时不重复展示。"""
    items = [s for s in load_meta().get(SNAPSHOT_KEY, []) if isinstance(s, dict)]
    active = {target_key(e) for e in (active_entries or []) if isinstance(e, dict)}
    active.discard("")
    return [s for s in items if target_key(s) not in active]


def find_snapshot(entry_id):
    for snap in load_snapshots():
        if snap.get("id") == entry_id:
            return snap
    return None
