"""发布端口、静态文件夹、自动启动项目；以及内置代理子进程。"""
import json
import os
import re
import shutil
import subprocess
import time
import uuid

from . import forwarder, healthcheck, runtime
from .entries import register_entry, write_menubar_state
from .errors import PanwebError
from .licensing import require_publish_license
from .lifecycle import parse_expires
from .models import entry_share_url
from .pins import normalize_pin, write_pin
from .processes import (find_cloudflared, free_port, internal_ports,
                        is_panweb_service, kill_process, listening_ports,
                        port_listening, stop_process)
from .safety import check_pages_folder
from .share import new_share_token
from .store import log_activity
from .tunnel import TunnelError, start_tunnel, verify_public

NODE_DEV_PORTS = [3000, 3001, 5173, 5174, 4321, 1420, 8000, 8080, 8888]
PORT_HINT_RE = re.compile(
    r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|::1?|\[[^\]]+\]):(\d{2,5})", re.I)


def is_risky_port(port):
    return runtime.RISKY_PORTS.get(port)


def _spawn_proxy(listen_port, entry_id, target_port=None, serve_dir=None,
                 pin=None, set_pin=True):
    """启动内置代理子进程（pin 校验 + 访问统计 + 静态/转发），返回进程。"""
    if set_pin:
        write_pin(entry_id, pin)
    log_path = os.path.join(runtime.LOG_DIR, "%s-proxy.log" % entry_id)
    logf = open(log_path, "ab", buffering=0)
    cmd = runtime.self_command("--internal-proxy",
                               "--listen-port", str(listen_port),
                               "--entry-id", entry_id)
    if serve_dir:
        cmd += ["--serve-dir", serve_dir]
    else:
        cmd += ["--target-port", str(target_port)]
    try:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True,
                                env=runtime.self_env())
    except OSError:
        proc = None
    logf.close()
    if proc is None and set_pin:
        write_pin(entry_id, None)
    return proc


def _publish_port(port, name, extra=None, pin=None, serve_dir=None,
                  expires_at=None, share=False, auto_check=True):
    """发布端口的共用实现（CLI / API / run 共用）。"""
    require_publish_license()
    cf = find_cloudflared()
    if not cf:
        raise PanwebError(3, "dependency_missing", "未找到 cloudflared",
                          "先安装：brew install cloudflared")
    if not serve_dir and port:
        _ensure_publishable_port(port)
    os.makedirs(runtime.LOG_DIR, exist_ok=True)
    entry_id = uuid.uuid4().hex[:6]
    entry_extra = {"pinned": bool(pin)}

    if pin or serve_dir or share:
        proxy_port = free_port()
        proxy_proc = _spawn_proxy(proxy_port, entry_id,
                                  target_port=None if serve_dir else port,
                                  serve_dir=serve_dir, pin=pin)
        if not proxy_proc:
            raise PanwebError(9, "server_failed", "无法启动内置代理进程")
        deadline = time.time() + 6
        while time.time() < deadline and not port_listening(proxy_port):
            time.sleep(0.2)
        if not port_listening(proxy_port):
            stop_process(proxy_proc, ("--internal-proxy",))
            raise PanwebError(9, "server_failed", "内置代理启动失败",
                              "查看日志：%s" % os.path.join(
                                  runtime.LOG_DIR, "%s-proxy.log" % entry_id))
        entry_extra["proxy_port"] = proxy_port
        entry_extra["server_pid"] = proxy_proc.pid
        if share or serve_dir:
            entry_extra["share_token"] = new_share_token()
        tunnel_target = proxy_port
    else:
        tunnel_target = port

    item = (forwarder.acquire_pooled_tunnel(tunnel_target, entry_id)
            if forwarder.CURRENT_POOL else None)
    if item:
        url, pid = item["url"], item["pid"]
        entry_extra["pooled"] = True
    else:
        log_path = os.path.join(runtime.LOG_DIR, "%s.log" % entry_id)
        try:
            url, proc = start_tunnel(cf, tunnel_target, log_path)
        except TunnelError as e:
            raise PanwebError(9, "tunnel_failed", str(e),
                              "查看日志：%s" % log_path)
        pid = proc.pid

    entry = {
        "id": entry_id,
        "name": name or ("port-%d" % port),
        "kind": "port",
        "target": port,
        "url": url,
        "pid": pid,
        "risky": is_risky_port(port),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if expires_at:
        entry_extra["expires_at"] = expires_at
    if extra:
        entry.update(extra)
    entry.update(entry_extra)
    register_entry(entry)
    write_menubar_state()
    reachable, dns_slow = verify_public(
        url, initial_wait=0 if entry_extra.get("pooled") else 3)
    result = dict(entry, reachable=reachable, dns_slow=dns_slow,
                  share_url=entry_share_url(entry))
    if auto_check:
        # 隧道通不代表应用能打开；后台按访客视角再走一遍，结论自己会进控制台。
        result["checking"] = healthcheck.schedule_check(entry_id)
    return result


def _ensure_publishable_port(port):
    if port in internal_ports():
        raise PanwebError(2, "internal_port",
                          "端口 %d 是 panweb 的内部服务端口" % port,
                          "控制台/代理端口不能发布；请选择你的应用端口")
    if is_panweb_service(port):
        raise PanwebError(2, "internal_port",
                          "端口 %d 是 panweb 控制台或代理" % port,
                          "发布它会把本机管理权限暴露到公网；请选择你的应用端口")


def core_publish(port, name=None, pin=None, expires=None, share=False,
                 auto_check=True):
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise PanwebError(2, "invalid_argument", "端口必须是数字")
    if not (1 <= port <= 65535):
        raise PanwebError(2, "invalid_argument", "端口必须在 1-65535 之间")
    pin = normalize_pin(pin)
    if not port_listening(port):
        raise PanwebError(8, "port_not_serving",
                          "端口 %d 上没有正在运行的程序" % port,
                          "先在本地启动应用（或到「启动项目」让 panweb 替你启动），再发布")
    entry = _publish_port(port, name, pin=pin, expires_at=parse_expires(expires),
                          share=share, auto_check=auto_check)
    log_activity("publish", "发布了应用「%s」%s%s" % (
        entry["name"],
        "（已设置访问口令）" if pin else "",
        "（含分享页与访问统计）" if entry.get("share_url") else ""), entry["url"])
    return entry


def core_detect(folder):
    folder = os.path.abspath(os.path.expanduser(folder or ""))
    if not os.path.isdir(folder):
        raise PanwebError(2, "invalid_argument", "文件夹不存在：%s" % folder)
    pkg_path = os.path.join(folder, "package.json")
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts") or {}
            script = ("dev" if "dev" in scripts
                      else ("start" if "start" in scripts else None))
            if script:
                return {"type": "node", "script": script, "folder": folder,
                        "detail": "识别到 Node 项目（npm run %s）" % script}
            return {"type": "node", "script": None, "folder": folder,
                    "detail": "Node 项目缺少 dev/start 脚本，无法自动启动"}
        except ValueError:
            pass
    if os.path.isfile(os.path.join(folder, "index.html")):
        return {"type": "static", "folder": folder,
                "detail": "识别到静态网页（直接发布）"}
    try:
        if any(f.endswith(".py") for f in os.listdir(folder)):
            return {"type": "python", "folder": folder,
                    "detail": "Python 项目：请手动启动后到「发布端口」选择"}
    except OSError:
        pass
    return {"type": "unknown", "folder": folder,
            "detail": "未识别的项目类型：可手动启动后到「发布端口」选择"}


def _sniff_port(log_path):
    """从项目启动日志里嗅探监听端口（必须是当前确实在监听的）。"""
    try:
        with open(log_path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    for m in PORT_HINT_RE.finditer(text):
        try:
            p = int(m.group(1))
        except ValueError:
            continue
        if 1024 <= p <= 65535 and port_listening(p):
            return p
    return None


def core_run(folder, name=None, share=False, auto_check=True):
    """识别项目类型 → 自动启动 → 等端口就绪 → 发布。"""
    info = core_detect(folder)
    folder = info["folder"]
    if info["type"] == "static":
        entry = core_pages(folder, name)
        log_activity("publish", "识别为静态网页，直接发布了「%s」"
                     % entry["name"], entry["url"])
        return entry
    if info["type"] != "node" or not info.get("script"):
        raise PanwebError(2, "unsupported", info["detail"],
                          "可手动启动应用后用「发布端口」发布")
    npm = shutil.which("npm")
    if not npm:
        raise PanwebError(3, "dependency_missing", "未找到 npm",
                          "安装 Node.js 后重试")

    os.makedirs(runtime.LOG_DIR, exist_ok=True)
    app_log = os.path.join(runtime.LOG_DIR,
                           "run-%s.log" % uuid.uuid4().hex[:6])
    baseline_ports = ({p for p, _ in listening_ports()}
                      if shutil.which("lsof") else set())
    logf = open(app_log, "ab", buffering=0)
    try:
        proc = subprocess.Popen([npm, "run", info["script"]], cwd=folder,
                                stdout=logf, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        logf.close()
        raise PanwebError(9, "app_start_failed", "无法启动项目：%s" % e)
    logf.close()

    port = None
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            raise PanwebError(9, "app_start_failed",
                              "项目进程提前退出（码 %s）" % proc.returncode,
                              "查看日志：%s" % app_log)
        port = _sniff_port(app_log)
        if not port and shutil.which("lsof"):
            new_ports = [p for p, _ in listening_ports()
                         if p not in baseline_ports]
            port = next((p for p in NODE_DEV_PORTS if p in new_ports), None)
            if not port and new_ports:
                port = new_ports[0]
        if port:
            break
        time.sleep(1)
    if not port:
        kill_process(proc.pid, ("npm", "node", "pnpm", "yarn", "bun"))
        raise PanwebError(9, "app_start_failed",
                          "120 秒内没有检测到项目监听的端口",
                          "查看日志：%s；也可手动启动后用「发布端口」" % app_log)

    entry = _publish_port(
        port, name or os.path.basename(folder),
        extra={"app_pid": proc.pid, "app_log": app_log, "launched": True},
        share=share, auto_check=auto_check)
    log_activity("publish", "启动并发布了「%s」（npm run %s，端口 %d）"
                 % (entry["name"], info["script"], port), entry["url"])
    return entry


def core_pages(folder, name=None, pin=None, expires=None, auto_check=True):
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        raise PanwebError(2, "invalid_argument", "文件夹不存在：%s" % folder)
    check_pages_folder(folder)
    pin = normalize_pin(pin)
    entry = _publish_port(0, name or os.path.basename(folder),
                          extra={"kind": "pages", "target": folder},
                          pin=pin, serve_dir=folder,
                          expires_at=parse_expires(expires),
                          auto_check=auto_check)
    log_activity("publish", "发布了网页「%s」%s" % (
        entry["name"], "（已设置访问口令）" if pin else ""), entry["url"])
    return entry
