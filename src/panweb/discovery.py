"""发现本机可发布应用与环境自检。"""
import os
import shutil
import subprocess
import time

from . import runtime
from .entries import core_list
from .processes import (find_cloudflared, internal_ports, listening_ports,
                        probe_http)
from .store import ensure_private_dirs


def core_discover():
    results = []
    published_ports = {}
    for e in core_list():
        if e.get("kind") == "port":
            published_ports[e.get("target")] = e.get("id")
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
    data = {"ready": bool(cf), "cloudflared": cf,
            "cloudflared_version": version, "state_dir": runtime.HOME_DIR,
            "tools": tools}
    _DOCTOR_CACHE["data"] = data
    _DOCTOR_CACHE["ts"] = now
    return dict(data)
