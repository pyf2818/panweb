"""健康巡检、隧道/代理自愈、启动清理与恢复。"""
import os
import threading
import time

from . import domain, forwarder, runtime
from .entries import write_menubar_state
from .errors import PanwebError
from .lifecycle import prune_dead_entries, sweep_expired
from .models import entry_local_port
from .pins import migrate_legacy_pins
from .processes import (cleanup_orphan_proxies, find_cloudflared, kill_process,
                        pid_alive, port_listening, stop_process)
from .publish import _spawn_proxy
from .store import (ensure_private_dirs, load_domain, load_state, log_activity,
                    save_state, state_lock)
from .tunnel import public_status, start_tunnel

RESTART_LOCK = threading.Lock()
HEALTH_FAILS = {}


def restart_entry_tunnel(entry):
    with RESTART_LOCK:
        return _restart_entry_tunnel(entry)


def _restart_entry_tunnel(entry):
    """重启一条发布的隧道（健康监控自愈用），返回新 url。"""
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
    return True


def recover_all():
    """控制台启动时恢复上一进程遗留的池化条目。"""
    sweep_expired()
    try:
        domain.core_domain_recover()
    except Exception as e:  # noqa: BLE001
        log_activity("ui", "固定域名恢复失败：%s" % e)
    recovered = 0
    for entry in load_state():
        try:
            if entry.get("pooled"):
                entry["url"] = restart_entry_tunnel(entry)
                recovered += 1
        except Exception as e:  # noqa: BLE001
            log_activity("ui", "「%s」启动恢复失败：%s" % (entry.get("name"), e))
    if recovered:
        log_activity("ui", "控制台重启，已恢复 %d 个发布的通道" % recovered)


def health_loop():
    """控制台内每 60 秒巡检：代理/隧道失联则自动恢复。"""
    while True:
        time.sleep(60)
        write_menubar_state()
        if sweep_expired():
            continue
        try:
            d = load_domain() or {}
            if d.get("domain") and not pid_alive(d.get("pid")):
                domain.core_domain_recover()
        except Exception as e:  # noqa: BLE001
            log_activity("ui", "固定域名巡检失败：%s" % e)
        for entry in load_state():
            try:
                entry_id = entry.get("id")
                if entry.get("proxy_port") \
                        and not pid_alive(entry.get("server_pid")):
                    restart_entry_proxy(entry)
                local_port = entry_local_port(entry)
                if not port_listening(local_port):
                    HEALTH_FAILS.pop(entry_id, None)
                    continue  # 应用未运行，等它起来
                url = entry.get("url")
                if not url:
                    continue
                status = public_status(url)
                if pid_alive(entry.get("pid")) and status not in (0, 502, 530):
                    HEALTH_FAILS.pop(entry_id, None)
                    continue
                if status == 0:
                    fails = HEALTH_FAILS.get(entry_id, 0) + 1
                    HEALTH_FAILS[entry_id] = fails
                    if fails < 3:
                        continue
                HEALTH_FAILS.pop(entry_id, None)
                new_url = restart_entry_tunnel(entry)
                log_activity("ui", "「%s」通道失联，已自动恢复"
                             % entry.get("name"), new_url)
            except Exception as e:  # noqa: BLE001
                log_activity("ui", "「%s」自愈失败：%s"
                             % (entry.get("name"), e))


def cleanup_runtime_files():
    """启动时清理遗留池隧道/孤儿代理/陈旧口令与访问记录/过期日志。"""
    ensure_private_dirs()
    forwarder.cleanup_pool_state()
    cleanup_orphan_proxies()
    migrate_legacy_pins()
    prune_dead_entries()
    state_ids = {e.get("id") for e in load_state()}
    now = time.time()
    if os.path.isdir(runtime.VISITS_DIR):
        for name in os.listdir(runtime.VISITS_DIR):
            if not name.endswith(".jsonl") or name[:-6] in state_ids:
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
