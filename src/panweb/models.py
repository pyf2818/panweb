"""发布条目的纯数据辅助函数（不读写文件、不启动进程）。"""


def entry_port(entry):
    """端口条目的源端口；非端口条目或脏数据返回 None。"""
    if entry.get("kind") != "port":
        return None
    raw = entry.get("port")
    if isinstance(raw, bool):
        return None
    try:
        port = int(raw)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def entry_folder(entry):
    """静态文件夹条目的发布目录；非 pages 条目或脏数据返回 None。"""
    if entry.get("kind") != "pages":
        return None
    folder = entry.get("folder")
    return folder if isinstance(folder, str) and folder else None


def entry_local_port(entry):
    """隧道回源指向的本地端口（代理端口或应用端口）。"""
    return (entry.get("proxy_port") or entry.get("local_port")
            or entry_port(entry))


def entry_public_url(entry, domain=None):
    """固定域名已绑定该应用时优先返回固定域名。"""
    d = domain or {}
    if d.get("configured") and d.get("domain") and d.get("bound_id") == entry.get("id"):
        return "https://" + d["domain"]
    return entry.get("url") or ""


def entry_share_url(entry, domain=None):
    base = entry_public_url(entry, domain).rstrip("/")
    token = entry.get("share_token")
    if not base or not token or not entry.get("proxy_port"):
        return None
    return base + "/__panweb/share/" + token


def entry_title(entry):
    """分享页与卡片展示的标题：自定义 title 优先，退回应用名。"""
    return ((entry.get("title") or "").strip()
            or (entry.get("name") or "").strip()
            or "panweb")
