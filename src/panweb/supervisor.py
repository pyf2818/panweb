"""健康巡检、隧道/代理自愈、启动清理与恢复。"""
import os
import threading
import time

from . import domain, events, forwarder, runtime
from .entries import entry_alive, write_menubar_state
from .errors import PanwebError, TunnelError
from .lifecycle import prune_dead_entries, sweep_expired
from .models import entry_local_port
from .pins import migrate_legacy_pins
from .processes import (cleanup_orphan_proxies, cleanup_orphan_tunnels,
                        find_cloudflared, kill_process, pid_alive,
                        port_listening, stop_process)
from .publish import _spawn_proxy
from .store import (ensure_private_dirs, load_domain, load_state, log_activity,
                    save_state, state_lock)
from .tunnel import pinned_status, public_status, start_tunnel

RESTART_LOCK = threading.Lock()
HEALTH_FAILS = {}
RETRY_WAIT = 2.0
HEALTH_FAILS_LIMIT = 3


def _tunnel_serving(url, tries=3):
    """这条隧道真的在响应吗。

    只看"进程还活着"不够：网络吃掉 QUIC 时 cloudflared 会连着又断，池里那些网址
    全都是死隧道。恢复前先按边缘 IP 直连问一次，问不通就别宣称"已自动恢复"。
    """
    for attempt in range(tries):
        if pinned_status(url, 6) not in (0, 530):
            return True
        if attempt + 1 < tries:
            time.sleep(RETRY_WAIT)
    return False


def restart_entry_tunnel(entry, reason="auto"):
    with RESTART_LOCK:
        return _restart_entry_tunnel(entry, reason)


def _restart_entry_tunnel(entry, reason="auto"):
    """重启一条发布的隧道（健康监控自愈用），返回新 url。"""
    old_url = entry.get("url")
    cf = find_cloudflared()
    if not cf:
        raise PanwebError(3, "dependency_missing", "未找到 cloudflared")
    with state_lock():
        if not any(e.get("id") == entry["id"] for e in load_state()):
            raise PanwebError(2, "not_found", "发布已停止")
    kill_process(entry.get("pid"), ("cloudflared",))
    old_fw = forwarder.FORWARDERS.pop(entry["id"], None)
    if old_fw:
        old_fw.stop()
    port = entry_local_port(entry)
    item = (forwarder.acquire_pooled_tunnel(port, entry["id"])
            if forwarder.CURRENT_POOL else None)
    if item:
        url, pid = item["url"], item["pid"]
    else:
        os.makedirs(runtime.LOG_DIR, exist_ok=True)
        log_path = os.path.join(runtime.LOG_DIR, "%s.log" % entry["id"])
        url, proc = start_tunnel(cf, port, log_path)
        pid = proc.pid
    if not _tunnel_serving(url):
        # 拿到的是一条死隧道：清干净并报错，让巡检说明白"没恢复成"，
        # 而不是写下新网址、报一句"已自动恢复"，60 秒后再来一遍
        kill_process(pid, ("cloudflared",))
        dead_fw = forwarder.FORWARDERS.pop(entry["id"], None)
        if dead_fw:
            dead_fw.stop()
        raise TunnelError("新隧道没有响应（本机到 Cloudflare 可能不通）：%s" % url)
    still_there = False
    with state_lock():
        entries = load_state()
        for e in entries:
            if e.get("id") == entry["id"]:
                e["url"] = url
                e["pid"] = pid
                still_there = True
        save_state(entries)
    if not still_there:
        kill_process(pid, ("cloudflared",))
        fw = forwarder.FORWARDERS.pop(entry["id"], None)
        if fw:
            fw.stop()
        raise PanwebError(2, "not_found", "发布在恢复过程中已被停止")
    if old_url and old_url != url:
        events.log_event(entry["id"], "url_change", "通道重建，公网网址已更新",
                         url_before=old_url, url_after=url,
                         reason=reason, source="system")
    else:
        events.log_event(entry["id"], "restart", "通道已重建",
                         url_after=url, reason=reason, source="system")
    return url


def restart_entry_proxy(entry):
    """重启密码/静态代理进程（保持同一代理端口，隧道网址不变）。"""
    proxy_port = entry.get("proxy_port")
    if not proxy_port:
        return False
    serve_dir = entry.get("target") if entry.get("kind") == "pages" else None
    proc = _spawn_proxy(proxy_port, entry["id"],
                        target_port=None if serve_dir else entry.get("target"),
                        serve_dir=serve_dir, set_pin=False)
    if not proc:
        return False
    deadline = time.time() + 6
    while time.time() < deadline and not port_listening(proxy_port):
        time.sleep(0.2)
    if not port_listening(proxy_port):
        stop_process(proc, ("--internal-proxy",))
        return False
    still_there = False
    with state_lock():
        entries = load_state()
        for e in entries:
            if e.get("id") == entry["id"]:
                e["server_pid"] = proc.pid
                still_there = True
        save_state(entries)
    if not still_there:
        stop_process(proc, ("--internal-proxy",))
        return False
    log_activity("ui", "「%s」口令/静态代理已重启" % entry.get("name"))
    events.log_event(entry["id"], "restart", "代理已重启（网址保留）",
                     url_after=entry.get("url"), reason="proxy",
                     source="system")
    return True


def recover_all():
    """控制台启动时恢复上一进程遗留的池化条目。"""
    try:
        sweep_expired()
    except Exception as e:  # noqa: BLE001
        log_activity("ui", "到期巡检失败：%s" % e)
    try:
        domain.core_domain_recover()
    except Exception as e:  # noqa: BLE001
        log_activity("ui", "固定域名恢复失败：%s" % e)
    recovered = 0
    for entry in load_state():
        try:
            if entry.get("pooled"):
                entry["url"] = restart_entry_tunnel(entry, "startup")
                recovered += 1
        except Exception as e:  # noqa: BLE001
            log_activity("ui", "「%s」启动恢复失败：%s" % (entry.get("name"), e))
    if recovered:
        log_activity("ui", "控制台重启，已恢复 %d 个发布的通道" % recovered)


def _source_ready(entry):
    """代理条目的源端是否还可用。

    代理端口活着只说明 panweb 自己的进程没死：应用崩了、静态目录被删时，
    公网仍可能拿到 200（口令页/分享页），巡检就会把空壳一直当健康。
    """
    if entry.get("kind") == "pages":
        target = entry.get("target") or ""
        return bool(target) and os.path.isdir(
            os.path.abspath(os.path.expanduser(str(target))))
    try:
        port = int(entry.get("target"))
    except (TypeError, ValueError):
        return False
    return 1 <= port <= 65535 and port_listening(port)


def _health_step(entry):
    """单条巡检：抖动先重启代理，只有隧道进程确实死了才换网址。"""
    entry_id = entry.get("id")
    proxy_restarted = False
    if entry.get("proxy_port") and not pid_alive(entry.get("server_pid")):
        proxy_restarted = restart_entry_proxy(entry)
    if entry.get("proxy_port") and not _source_ready(entry):
        # 源端不可用时重启代理/隧道都没用，只记失败并在阈值处说清原因；
        # 绝不能把“应用挂了”当成“隧道挂了”去换公网网址。
        fails = HEALTH_FAILS.get(entry_id, 0) + 1
        HEALTH_FAILS[entry_id] = fails
        if fails >= HEALTH_FAILS_LIMIT:
            HEALTH_FAILS.pop(entry_id, None)
            log_activity("ui", "「%s」源应用/静态目录不可用，隧道与代理保留"
                         % entry.get("name"))
        return
    local_port = entry_local_port(entry)
    if not port_listening(local_port):
        HEALTH_FAILS.pop(entry_id, None)
        return  # 应用未运行，等它起来
    url = entry.get("url")
    if not url:
        return
    status = public_status(url)
    if pid_alive(entry.get("pid")) and status not in (0, 502, 530):
        HEALTH_FAILS.pop(entry_id, None)
        return
    fails = HEALTH_FAILS.get(entry_id, 0) + 1
    HEALTH_FAILS[entry_id] = fails
    if fails < HEALTH_FAILS_LIMIT:
        return
    HEALTH_FAILS.pop(entry_id, None)
    if not pid_alive(entry.get("pid")):
        new_url = restart_entry_tunnel(entry, "health")
        log_activity("ui", "「%s」隧道进程已死，已重建通道"
                     % entry.get("name"), new_url)
        return
    if entry.get("proxy_port"):
        if not proxy_restarted:
            restart_entry_proxy(entry)
        log_activity("ui", "「%s」应用连续无响应，已重启代理（网址保留）"
                     % entry.get("name"))
    else:
        log_activity("ui", "「%s」应用连续无响应，隧道保留，等待应用恢复"
                     % entry.get("name"))


def recover_failing(progress=None):
    """手动恢复只处理失联或公网探测失败的条目；健康条目不动。"""
    entries = load_state()
    checked = 0
    recovered = []
    for entry in entries:
        try:
            if not _needs_recovery(entry):
                continue
            checked += 1
            if progress:
                progress("恢复「%s」…" % entry.get("name"))
            url = restart_entry_tunnel(entry, "manual")
            recovered.append({"id": entry.get("id"), "url": url})
        except Exception as e:  # noqa: BLE001
            events.log_event(entry.get("id"), "error", "手动恢复失败",
                             reason=type(e).__name__, source="system")
            log_activity("ui", "「%s」手动恢复失败：%s"
                         % (entry.get("name"), e))
    if checked:
        log_activity("ui", "手动恢复完成：检查 %d 个异常条目，成功 %d 个"
                     % (checked, len(recovered)))
    return {"checked": checked, "recovered": recovered}


def _needs_recovery(entry):
    if not entry_alive(entry):
        return True
    url = entry.get("url") or ""
    return (".trycloudflare.com" in url
            and pinned_status(url, 6) in (0, 502, 530))


def health_tick():
    """单次巡检；sweep_expired 的异常不能打死整个后台循环。"""
    write_menubar_state()
    try:
        if sweep_expired():
            return
    except Exception as e:  # noqa: BLE001
        log_activity("ui", "到期巡检失败：%s" % e)
    try:
        d = load_domain() or {}
        if d.get("domain") and not pid_alive(d.get("pid")):
            domain.core_domain_recover()
    except Exception as e:  # noqa: BLE001
        log_activity("ui", "固定域名巡检失败：%s" % e)
    for entry in load_state():
        try:
            _health_step(entry)
        except Exception as e:  # noqa: BLE001
            log_activity("ui", "「%s」自愈失败：%s"
                         % (entry.get("name"), e))


def health_loop():
    """控制台内每 60 秒巡检：代理/隧道失联则自动恢复。"""
    while True:
        time.sleep(60)
        health_tick()


def cleanup_runtime_files():
    """启动时清理遗留池隧道/孤儿代理/陈旧口令与访问记录/过期日志。"""
    ensure_private_dirs()
    forwarder.cleanup_pool_state()
    forwarder.cleanup_forwarder_sockets()
    cleanup_orphan_proxies()
    stray = cleanup_orphan_tunnels()
    if stray:
        log_activity("system", "回收了 %d 条没有归属的隧道" % len(stray))
    migrate_legacy_pins()
    prune_dead_entries()
    state_ids = {e.get("id") for e in load_state()}
    now = time.time()
    if os.path.isdir(runtime.VISITS_DIR):
        for name in os.listdir(runtime.VISITS_DIR):
            if not name.endswith(".jsonl") or name.startswith("._"):
                continue
            stem = name[:-6]
            # 访问日志按天分文件（<id>-YYYYMMDD.jsonl）；旧版单文件也要兼容。
            owner = stem.rsplit("-", 1)[0] if "-" in stem else stem
            if owner in state_ids:
                continue
            path = os.path.join(runtime.VISITS_DIR, name)
            try:
                if now - os.path.getmtime(path) > 3600:
                    os.remove(path)
            except OSError:
                pass
    if os.path.isdir(runtime.LOG_DIR):
        logs = []
        for name in os.listdir(runtime.LOG_DIR):
            path = os.path.join(runtime.LOG_DIR, name)
            try:
                logs.append((os.path.getmtime(path), path))
            except OSError:
                pass
        logs.sort(reverse=True)
        for i, (mtime, path) in enumerate(logs):
            if i >= 200 or now - mtime > 30 * 86400:
                try:
                    os.remove(path)
                except OSError:
                    pass
