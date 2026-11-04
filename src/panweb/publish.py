"""发布端口、静态文件夹、自动启动项目；以及内置代理子进程。

可独立的部分拆在同目录的 ``publish_defaults`` / ``publish_text`` /
``project`` / ``publish_support``；这里继续 re-export 原有名字，保持
``panweb.publish`` 的导入与 mock 目标不变。
"""
import os
import shutil
import subprocess
import time
import uuid

from . import events, forwarder, healthcheck, runtime
from .entries import replace_entry, register_entry, stop_entry, \
    write_menubar_state
from .errors import PanwebError
from .licensing import require_publish_license
from .lifecycle import parse_expires
from .models import entry_share_url
from .pins import normalize_pin, write_pin
from .processes import (find_cloudflared, free_port, listening_ports,
                        port_listening, stop_process)
from .project import core_detect
from .publish_defaults import load_publish_defaults, remember_publish
from .publish_support import NODE_DEV_PORTS, emit as _emit, \
    ensure_publishable_port as _ensure_publishable_port, \
    is_risky_port, pick_port as _pick_port, sniff_port as _sniff_port
from .publish_text import normalize_desc, normalize_title
from .safety import check_pages_folder
from .share import new_share_token
from .store import load_state, log_activity
from .tunnel import TunnelError, start_tunnel, verify_public


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
                  register=True, progress=None, entry_id=None,
                  keep_secrets=False, title=None, desc=None):
    """发布端口的共用实现（CLI / API / run 共用）。"""
    title = normalize_title(title)
    desc = normalize_desc(desc)
    _emit(progress, "检查发布许可与隧道引擎…")
    require_publish_license()
    cf = find_cloudflared()
    if not cf:
        raise PanwebError(3, "dependency_missing", "未找到 cloudflared",
                          "先安装：brew install cloudflared")
    if not serve_dir and port:
        _ensure_publishable_port(port)
    os.makedirs(runtime.LOG_DIR, exist_ok=True)
    entry_id = entry_id or uuid.uuid4().hex[:6]
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
        if title:
            entry["title"] = title
        if desc:
            entry["desc"] = desc
        if expires_at:
            entry_extra["expires_at"] = expires_at
        if extra:
            entry.update(extra)
        entry.update(entry_extra)
        if register:
            register_entry(entry)
    except BaseException as e:
        events.log_event(entry_id, "error", "发布失败",
                         reason=type(e).__name__, source="publish")
        # 发布没登记成功时，代理/隧道/PIN 都是半成品，必须当场回收，
        # 否则下一次控制台启动前它们会一直占着端口和子进程。
        stop_entry({"id": entry_id, "pid": tunnel_pid,
                    "server_pid": proxy_proc.pid if proxy_proc else None},
                   clear_secrets=not keep_secrets)
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
    events.log_event(entry_id, "publish", "发布了「%s」" % entry["name"],
                     url_after=entry.get("url"),
                     expires_at=entry.get("expires_at"), source="publish")
    if auto_check:
        # 隧道通不代表应用能打开；后台按访客视角再走一遍，结论自己会进控制台。
        result["checking"] = healthcheck.schedule_check(entry_id)
    _emit(progress, "发布完成")
    return result


def core_publish(port=None, name=None, pin=None, expires=None, share=False,
                 auto_check=True, progress=None, title=None, desc=None):
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
                          progress=progress, title=title, desc=desc)
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
                  "desc", "title") if k in entry}
        try:
            new_entry = _publish_port(entry.get("target"), entry.get("name"),
                                      pin=pin, extra=extra,
                                      expires_at=entry.get("expires_at"),
                                      register=False, auto_check=False,
                                      entry_id=entry_id, keep_secrets=True)
        except BaseException:
            # 旧条目本来没有代理（也就没有口令）；把半路写入的 PIN 回滚掉。
            write_pin(entry_id, None)
            raise
        new_entry = dict(new_entry)
        new_entry["id"] = entry_id
        try:
            replace_entry(entry_id, new_entry)
        except BaseException:
            stop_entry(new_entry, keep_app=True, clear_secrets=False)
            raise
        try:
            stop_entry(entry, keep_app=True, clear_secrets=False)
        except Exception as e:
            log_activity(actor, "旧发布清理失败：%s" % e)
        log_activity(actor, "为「%s」设置了访问口令（网址已更新）"
                     % entry.get("name"), new_entry["url"])
        events.log_event(entry_id, "pin_change", "设置了访问口令（网址已更新）",
                         url_before=entry.get("url"),
                         url_after=new_entry.get("url"), source=actor)
        return {"updated": True, "entry": new_entry}
    write_pin(entry_id, pin)
    log_activity(actor, ("为「%s」设置了访问口令" if pin
                         else "「%s」的访问口令已移除") % entry.get("name"))
    events.log_event(entry_id, "pin_change",
                     "设置了访问口令" if pin else "移除了访问口令",
                     url_before=entry.get("url"),
                     url_after=entry.get("url"), source=actor)
    return {"updated": True, "entry": entry}


def core_run(folder=None, name=None, share=False, auto_check=True, pin=None,
             expires=None, progress=None, title=None, desc=None):
    """识别项目类型 → 自动启动 → 等端口就绪 → 发布。"""
    folder = folder or "."
    _emit(progress, "识别项目类型…")
    info = core_detect(folder)
    folder = info["folder"]
    if info["type"] == "static":
        _emit(progress, "静态网页，直接发布…")
        entry = core_pages(folder, name, pin=pin, expires=expires,
                           progress=progress, title=title, desc=desc)
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
            share=share, auto_check=auto_check, progress=progress,
            title=title, desc=desc)
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
               progress=None, title=None, desc=None):
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
                          auto_check=auto_check, progress=progress,
                          title=title, desc=desc)
    remember_publish(last_folder=folder, expires=expires or "")
    log_activity("publish", "发布了网页「%s」%s" % (
        entry["name"], "（已设置访问口令）" if pin else ""), entry["url"])
    return entry
