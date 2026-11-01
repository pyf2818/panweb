"""系统全景与离线打包。"""
import os
import time
import zipfile

from . import forwarder, runtime
from .agents import core_agents
from .console import daemon_pid
from .discovery import core_doctor
from .entries import core_list
from .errors import PanwebError
from .safety import check_pages_folder
from .store import load_meta


def dir_size(path):
    total = 0
    for r, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(r, name))
            except OSError:
                pass
    return total


def core_system():
    """管理后台的系统与数据全景。"""
    daemon = daemon_pid()
    apps = core_list()
    visits_total = 0
    if os.path.isdir(runtime.VISITS_DIR):
        for name in os.listdir(runtime.VISITS_DIR):
            try:
                with open(os.path.join(runtime.VISITS_DIR, name),
                          encoding="utf-8") as f:
                    visits_total += sum(1 for _ in f)
            except OSError:
                pass
    raw_version = core_doctor()["cloudflared_version"] or ""
    return {
        "panweb_version": runtime.PANWEB_VERSION,
        "cloudflared_version": raw_version.replace(
            "cloudflared version ", "").split(" (")[0],
        "console_pid": daemon,
        "uptime_min": int((time.time() - runtime.STARTED_AT) // 60),
        "data_dir": runtime.HOME_DIR,
        "data_size": dir_size(runtime.HOME_DIR),
        "visits_total": visits_total,
        "apps_total": len(apps),
        "apps_online": sum(1 for a in apps if a.get("alive")),
        "agents_connected": sum(1 for a in core_agents() if a["connected"]),
        "pool_ready": bool(forwarder.CURRENT_POOL
                           and forwarder.CURRENT_POOL.items),
        "notify_visits": load_meta().get("notify_visits", True),
    }


def core_pack(folder):
    """把静态文件夹打包成 zip（可上传到任意免费静态托管，关机也能访问）。"""
    folder = os.path.abspath(os.path.expanduser(folder or ""))
    if not os.path.isdir(folder):
        raise PanwebError(2, "invalid_argument", "文件夹不存在：%s" % folder)
    check_pages_folder(folder)
    name = os.path.basename(folder) or "panweb-site"
    out_dir = os.path.join(runtime.HOME_DIR, "packs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "%s-%s.zip"
                       % (name, time.strftime("%m%d%H%M")))
    excluded = {"node_modules", "__pycache__", "venv"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs
                       if not d.startswith(".") and d not in excluded]
            for name_f in files:
                if name_f.startswith("."):
                    continue
                fp = os.path.join(root, name_f)
                if os.path.islink(fp):
                    continue
                z.write(fp, os.path.relpath(fp, folder))
    return {"zip": out, "size": os.path.getsize(out)}
