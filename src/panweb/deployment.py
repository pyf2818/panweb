"""部署详情：把 state 与事件流派生成右栏可展示的字段。

严格只读派生数据：不读口令文件，口令状态只暴露布尔；URL 只来自 state 与
events 的白名单字段，缺字段留 None，由前端显示「未知」。
"""
import time

from .models import entry_public_url, entry_share_url, entry_title

REBUILD_TYPES = ("restart", "url_change")


def remaining_text(expires_at, now=None):
    """有效期文案：永久 / 已到期 / 剩余 N 天 N 小时。"""
    if not expires_at:
        return "永久"
    try:
        sec = int(float(expires_at) - (now if now is not None else time.time()))
    except (TypeError, ValueError):
        return "未知"
    if sec <= 0:
        return "已到期"
    days, rest = divmod(sec, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "剩余 %d 天 %d 小时" % (days, hours)
    if hours:
        return "剩余 %d 小时 %d 分" % (hours, minutes)
    return "剩余 %d 分钟" % max(1, minutes)


def link_history(entry, history, domain=None):
    """当前网址 + url_change 里用过的旧网址，去重并按新旧排序。"""
    if not entry:
        return []
    rows = []
    seen = set()
    current = entry_public_url(entry, domain) or ""
    if current:
        rows.append({"url": current, "status": "current", "ts": None})
        seen.add(current)
    for event in history or []:
        if not isinstance(event, dict) or event.get("type") != "url_change":
            continue
        details = event.get("details") or {}
        if not isinstance(details, dict):
            continue
        for key in ("url_before", "url_after"):
            url = details.get(key)
            if not isinstance(url, str) or not url or url in seen:
                continue
            seen.add(url)
            rows.append({"url": url, "status": "expired", "ts": event.get("ts")})
    return rows


def build_detail(entry, history, domain=None, visits=None, now=None):
    """组装一条部署详情；entry 为空返回 None（前端据此显示空态）。"""
    if not entry or not entry.get("id"):
        return None
    history = [e for e in (history or []) if isinstance(e, dict)]
    rebuilds = [e for e in history if e.get("type") in REBUILD_TYPES]
    last_rebuild = max((e.get("ts") or 0) for e in rebuilds) if rebuilds else None
    kind = entry.get("kind") or ""
    source = ""
    if kind == "port":
        source = "127.0.0.1:%s" % entry.get("port")
    elif kind == "pages":
        source = entry.get("folder") or ""
    stats = visits if isinstance(visits, dict) else {}
    return {
        "id": entry["id"],
        "title": entry_title(entry),
        "kind": kind,
        "source": source,
        "url": entry_public_url(entry, domain),
        "share_url": entry_share_url(entry, domain),
        "pin_required": bool(entry.get("pinned")),
        "expires_at": entry.get("expires_at"),
        "expires_text": remaining_text(entry.get("expires_at"), now),
        "published_at": entry.get("started"),
        "rebuild_count": len(rebuilds),
        "last_rebuild_at": last_rebuild,
        "links": link_history(entry, history, domain),
        "visits": {
            "available": bool(entry.get("proxy_port")),
            "total": stats.get("total"),
            "uv": stats.get("uv"),
            "last": stats.get("last"),
        },
    }
