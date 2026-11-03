"""发布端口、静态文件夹、自动启动项目；以及内置代理子进程。"""
import json
import os
import re
import shutil
import subprocess
import time
import uuid

from . import forwarder, healthcheck, runtime
from .entries import replace_entry, register_entry, stop_entry, \
    write_menubar_state
from .errors import PanwebError
from .licensing import require_publish_license
from .lifecycle import parse_expires
from .models import entry_share_url
from .pins import normalize_pin, write_pin
from .processes import (find_cloudflared, free_port, internal_ports,
                        is_panweb_service, listening_ports,
                        port_listening, stop_process)
from .safety import check_pages_folder
from .share import new_share_token
from .store import json_lock, load_meta, load_state, log_activity, save_meta
from .tunnel import TunnelError, start_tunnel, verify_public

NODE_DEV_PORTS = [3000, 3001, 5173, 5174, 4321, 1420, 8000, 8080, 8888]
PORT_HINT_RE = re.compile(
    r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|::1?|\[[^\]]+\]):(\d{2,5})", re.I)
DEFAULTS_KEY = "publish_defaults"


def _emit(progress, message):
    if progress:
        progress(message)


def load_publish_defaults():
    """上次发布用的有效期/分享选项与最近端口、文件夹；口令不落盘。"""
    meta = load_meta()
    saved = meta.get(DEFAULTS_KEY)
    saved = saved if isinstance(saved, dict) else {}
    return {
        "expires": saved.get("expires") or "",
        "share": bool(saved.get("share", True)),
        "last_port": saved.get("last_port"),
        "last_folder": saved.get("last_folder"),
        "last_project": saved.get("last_project"),
    }


def remember_publish(**values):
    """记住选项供下次预填；失败只记日志，不能因为偏好写不进去而毁掉发布。"""
    try:
        with json_lock(runtime.META_FILE):
            meta = load_meta()
            saved = meta.get(DEFAULTS_KEY)
            saved = dict(saved) if isinstance(saved, dict) else {}
            for key, value in values.items():
                if value is not None:
                    saved[key] = value
            meta[DEFAULTS_KEY] = saved
            save_meta(meta)
    except OSError as e:
        log_activity("system", "保存发布偏好失败：%s" % e)


def _pick_port(progress=None):
    """没给端口时替主人挑一个：优先上次用的，其次唯一候选。"""
    from .discovery import core_discover

    _emit(progress, "自动探测本机正在运行的应用…")
    candidates = core_discover()
    if not candidates:
        raise PanwebError(
            2, "invalid_argument", "没有发现可发布的应用",
            "先在本地启动应用，再运行 panweb discover 查看端口；"
            "也可以直接 panweb publish <端口>")
    last = load_publish_defaults().get("last_port")
    if last and any(c["port"] == last for c in candidates):
        return int(last)
    fresh = [c for c in candidates if not c.get("published")] or candidates
    if len(fresh) == 1:
        return int(fresh[0]["port"])
    ports = "、".join(str(c["port"]) for c in fresh[:6])
    raise PanwebError(
        2, "ambiguous_port", "发现多个可发布端口：%s" % ports,
        "指定其中一个：panweb publish %d" % fresh[0]["port"])


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
                  expires_at=None, share=False, auto_check=True,
                  register=True, progress=None):
    """发布端口的共用实现（CLI / API / run 共用）。"""
    _emit(progress, "检查发布许可与隧道引擎…")
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

    proxy_proc = None
    tunnel_pid = None
    try:
        if pin or serve_dir or share:
            _emit(progress, "启动内置代理与分享页…")
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
                raise PanwebError(9, "server_failed", "内置代理启动失败",
                                  "查看日志：%s" % os.path.join(
                                      runtime.LOG_DIR,
                                      "%s-proxy.log" % entry_id))
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
            url, tunnel_pid = item["url"], item["pid"]
            entry_extra["pooled"] = True
            _emit(progress, "复用预热隧道…")
        else:
            _emit(progress, "建立公网隧道（通常需要数秒）…")
            log_path = os.path.join(runtime.LOG_DIR, "%s.log" % entry_id)
            try:
                url, proc = start_tunnel(cf, tunnel_target, log_path)
            except TunnelError as e:
                raise PanwebError(9, "tunnel_failed", str(e),
                                  "查看日志：%s" % log_path)
            tunnel_pid = proc.pid

        entry = {
            "id": entry_id,
            "name": name or ("port-%d" % port),
            "kind": "port",
            "target": port,
            "url": url,
            "pid": tunnel_pid,
            "risky": is_risky_port(port),
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        if expires_at:
            entry_extra["expires_at"] = expires_at
        if extra:
            entry.update(extra)
        entry.update(entry_extra)
        if register:
            register_entry(entry)
    except BaseException:
        # 发布没登记成功时，代理/隧道/PIN 都是半成品，必须当场回收，
        # 否则下一次控制台启动前它们会一直占着端口和子进程。
        stop_entry({"id": entry_id, "pid": tunnel_pid,
                    "server_pid": proxy_proc.pid if proxy_proc else None})
        raise
    if not register:
        # 供改 PIN 等“先建新、再换旧”的调用方使用；此时还没写进 state，
        # 不能刷新菜单栏或把临时检查结果混进条目。
        return entry
    write_menubar_state()
    _emit(progress, "验证公网可达…")
    reachable, dns_slow = verify_public(
        url, initial_wait=0 if entry_extra.get("pooled") else 3)
    result = dict(entry, reachable=reachable, dns_slow=dns_slow,
                  share_url=entry_share_url(entry))
    if auto_check:
        # 隧道通不代表应用能打开；后台按访客视角再走一遍，结论自己会进控制台。
        result["checking"] = healthcheck.schedule_check(entry_id)
    _emit(progress, "发布完成")
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


def core_publish(port=None, name=None, pin=None, expires=None, share=False,
                 auto_check=True, progress=None):
    if port is None:
        port = _pick_port(progress)
    else:
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise PanwebError(2, "invalid_argument", "端口必须是数字")
    if not (1 <= port <= 65535):
        raise PanwebError(2, "invalid_argument", "端口必须在 1-65535 之间")
    pin = normalize_pin(pin)
    _emit(progress, "确认端口 %d 有服务响应…" % port)
    if not port_listening(port):
        raise PanwebError(
            8, "port_not_serving", "端口 %d 上没有正在运行的程序" % port,
            "先启动应用；也可以运行 panweb discover 看本机在监听哪些端口，"
            "或到「启动项目」让 panweb 替你启动")
    entry = _publish_port(port, name, pin=pin, expires_at=parse_expires(expires),
                          share=share, auto_check=auto_check,
                          progress=progress)
    remember_publish(last_port=port, expires=expires or "",
                     share=bool(share))
    log_activity("publish", "发布了应用「%s」%s%s" % (
        entry["name"],
        "（已设置访问口令）" if pin else "",
        "（含分享页与访问统计）" if entry.get("share_url") else ""), entry["url"])
    return entry


def core_set_pin(entry_id, pin, actor="ui"):
    """改/移除访问口令：需要新建代理时按“先建新、换 state、再停旧”收尾。

    失败时保留旧条目与本地应用；只有新发布已就绪并成功换入 state，才停旧隧道。
    """
    hits = [e for e in load_state() if e.get("id") == entry_id]
    if not hits:
        raise PanwebError(4, "not_found", "应用不存在")
    entry = hits[0]
    pin = normalize_pin(pin) if pin else None
    if not entry.get("proxy_port") and pin:
        require_publish_license()
        extra = {k: entry[k] for k in
                 ("app_pid", "app_log", "launched", "risky", "host_mode",
                  "desc") if k in entry}
        new_entry = _publish_port(entry.get("target"), entry.get("name"),
                                  pin=pin, extra=extra,
                                  expires_at=entry.get("expires_at"),
                                  register=False, auto_check=False)
        try:
            replace_entry(entry_id, new_entry)
        except BaseException:
            stop_entry(new_entry, keep_app=True)
            raise
        try:
            stop_entry(entry, keep_app=True)
        except Exception as e:
            log_activity(actor, "旧发布清理失败：%s" % e)
        log_activity(actor, "为「%s」设置了访问口令（网址已更新）"
                     % entry.get("name"), new_entry["url"])
        return {"updated": True, "entry": new_entry}
    write_pin(entry_id, pin)
    log_activity(actor, ("为「%s」设置了访问口令" if pin
                         else "「%s」的访问口令已移除") % entry.get("name"))
    return {"updated": True, "entry": entry}


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


def core_run(folder=None, name=None, share=False, auto_check=True, pin=None,
             expires=None, progress=None):
    """识别项目类型 → 自动启动 → 等端口就绪 → 发布。"""
    folder = folder or "."
    _emit(progress, "识别项目类型…")
    info = core_detect(folder)
    folder = info["folder"]
    if info["type"] == "static":
        _emit(progress, "静态网页，直接发布…")
        entry = core_pages(folder, name, pin=pin, expires=expires,
                           progress=progress)
        log_activity("publish", "识别为静态网页，直接发布了「%s」"
                     % entry["name"], entry["url"])
        remember_publish(last_project=folder)
        return entry
    if info["type"] != "node" or not info.get("script"):
        raise PanwebError(2, "unsupported", info["detail"],
                          "可手动启动应用后用「发布端口」发布，"
                          "或先运行 panweb discover 确认端口")
    npm = shutil.which("npm")
    if not npm:
        raise PanwebError(3, "dependency_missing", "未找到 npm",
                          "安装 Node.js 后重试")

    os.makedirs(runtime.LOG_DIR, exist_ok=True)
    app_log = os.path.join(runtime.LOG_DIR,
                           "run-%s.log" % uuid.uuid4().hex[:6])
    baseline_ports = ({p for p, _ in listening_ports()}
                      if shutil.which("lsof") else set())
    _emit(progress, "启动项目（npm run %s）…" % info["script"])
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
    try:
        _emit(progress, "等待项目监听端口（最多 120 秒）…")
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
            raise PanwebError(9, "app_start_failed",
                              "120 秒内没有检测到项目监听的端口",
                              "查看日志：%s；也可手动启动后用「发布端口」"
                              % app_log)

        entry = _publish_port(
            port, name or os.path.basename(folder),
            extra={"app_pid": proc.pid, "app_log": app_log, "launched": True},
            pin=normalize_pin(pin), expires_at=parse_expires(expires),
            share=share, auto_check=auto_check, progress=progress)
    except BaseException:
        # 发布失败就回收刚拉起的项目进程；否则用户只能看到一个不知从哪来的
        # npm/node 进程继续占着端口，重试还会撞端口。
        stop_process(proc, ("npm", "node", "pnpm", "yarn", "bun"))
        raise
    remember_publish(last_project=folder, last_port=port,
                     expires=expires or "", share=bool(share))
    log_activity("publish", "启动并发布了「%s」（npm run %s，端口 %d）"
                 % (entry["name"], info["script"], port), entry["url"])
    return entry


def core_pages(folder=None, name=None, pin=None, expires=None, auto_check=True,
               progress=None):
    folder = os.path.abspath(os.path.expanduser(folder or "."))
    if not os.path.isdir(folder):
        raise PanwebError(2, "invalid_argument", "文件夹不存在：%s" % folder)
    _emit(progress, "检查网页文件夹…")
    check_pages_folder(folder)
    pin = normalize_pin(pin)
    entry = _publish_port(0, name or os.path.basename(folder),
                          extra={"kind": "pages", "target": folder},
                          pin=pin, serve_dir=folder,
                          expires_at=parse_expires(expires),
                          auto_check=auto_check, progress=progress)
    remember_publish(last_folder=folder, expires=expires or "")
    log_activity("publish", "发布了网页「%s」%s" % (
        entry["name"], "（已设置访问口令）" if pin else ""), entry["url"])
    return entry
