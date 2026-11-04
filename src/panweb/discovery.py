"""发现本机可发布应用与环境自检。"""
import os
import shutil
import subprocess
import sys
import time

from . import runtime
from .entries import core_list
from .models import entry_port
from .processes import (find_cloudflared, internal_ports, listening_ports,
                        probe_http)
from .project_config import inspect_project_config
from .store import ensure_private_dirs, scan_legacy_target


def core_discover():
    results = []
    published_ports = {}
    for e in core_list():
        if e.get("kind") == "port":
            published_ports[entry_port(e)] = e.get("id")
        elif e.get("kind") == "pages":
            published_ports[e.get("proxy_port") or e.get("local_port")] = \
                e.get("id")
    internal = internal_ports()
    for port, pid in listening_ports():
        if port in internal:
            continue  # panweb 自己的代理/固定域名转发端口
        title, server = probe_http(port)
        if server.lower().startswith("panweb-"):
            continue  # 控制台或代理，绝不能把自己发布出去
        proc_name = None
        if pid:
            try:
                proc_name = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "comm="],
                    capture_output=True, text=True, timeout=5).stdout.strip()
                proc_name = os.path.basename(proc_name) if proc_name else None
            except Exception:  # noqa: BLE001
                pass
        if title is None and port not in runtime.KNOWN_PORTS:
            continue
        results.append({
            "port": port,
            "process": proc_name,
            "title": title or runtime.KNOWN_PORTS.get(port, "HTTP 服务"),
            "published": published_ports.get(port),
            "risky": runtime.RISKY_PORTS.get(port),
        })
    return results


_DOCTOR_CACHE = {"ts": 0.0, "data": None}


def core_doctor(force=False):
    now = time.time()
    if not force and _DOCTOR_CACHE["data"] and now - _DOCTOR_CACHE["ts"] < 5:
        return dict(_DOCTOR_CACHE["data"])
    cf = find_cloudflared()
    version = None
    if cf:
        try:
            version = subprocess.run([cf, "--version"], capture_output=True,
                                     text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            version = "unknown"
    ensure_private_dirs()
    tools = {name: shutil.which(name) for name in
             ("curl", "lsof", "ps", "git", "npm", "gh", "swiftc")}
    py_ok = sys.version_info >= (3, 9)
    legacy = scan_legacy_target()
    data = {"ready": bool(cf) and py_ok, "cloudflared": cf,
            "cloudflared_version": version, "state_dir": runtime.HOME_DIR,
            "python": {"path": sys.executable,
                       "version": "%d.%d.%d" % sys.version_info[:3],
                       "ok": py_ok},
            "tools": tools,
            "project_config": inspect_project_config(os.getcwd()),
            "legacy_target": {
                "ok": not legacy,
                "count": len(legacy),
                "ids": legacy[:10],
                "message": ("检测到 %d 条旧版 target 字段；读取时会自动迁移为 "
                            "port/folder" % len(legacy)) if legacy else
                           "无遗留 target 字段",
                "hint": ("无需手工处理；下次写入后 state.json 即为 "
                         "schema_version 2") if legacy else "",
            }}
    _DOCTOR_CACHE["data"] = data
    _DOCTOR_CACHE["ts"] = now
    return dict(data)
