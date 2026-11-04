"""发布条目的纯数据辅助函数（不读写文件、不启动进程）。"""


def entry_local_port(entry):
    """隧道回源指向的本地端口（代理端口或应用端口）。"""
    return entry.get("proxy_port") or entry.get("local_port") or entry.get("target")


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
