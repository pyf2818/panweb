"""发布条目的注册、存活判断、停止、列表与菜单栏状态。"""
import os
import time

from . import forwarder, runtime, upstream
from .errors import PanwebError
from .models import entry_share_url
from .pins import write_pin
from .processes import kill_process, pid_alive, port_listening
from .store import (bump_stopped, load_domain, load_meta, load_state,
                    log_activity, save_json, save_state, state_lock)


def register_entry(entry):
    with state_lock():
        entries = load_state()
        entries.append(entry)
        save_state(entries)


def replace_entry(old_id, entry):
    """新发布已就绪后，一次性把旧条目换成新条目，避免中间态。"""
    with state_lock():
        entries = [e for e in load_state() if e.get("id") != old_id]
        entries.append(entry)
        save_state(entries)
    write_menubar_state()


def remove_entry_files(entry_id):
    if not entry_id:
        return
    upstream.remove_auth_file(entry_id)
    for path in (os.path.join(runtime.SECRETS_DIR, "%s.pin" % entry_id),
                 os.path.join(runtime.VISITS_DIR, "%s.jsonl" % entry_id)):
        try:
            os.remove(path)
        except OSError:
            pass


def stop_entry(entry, keep_app=False, clear_secrets=True):
    fw = forwarder.FORWARDERS.pop(entry.get("id"), None)
    if fw:
        fw.stop()
    kill_process(entry.get("pid"), ("cloudflared",))
    kill_process(entry.get("server_pid"), ("--internal-proxy",))
    if not keep_app:
        kill_process(entry.get("app_pid"),
                     ("npm", "node", "pnpm", "yarn", "bun"))
    if clear_secrets:
        write_pin(entry.get("id"), None)
        remove_entry_files(entry.get("id"))


def entry_alive(entry):
    """隧道/代理进程存活，且本地应用/代理端口确实在监听。"""
    if not (pid_alive(entry.get("pid")) or pid_alive(entry.get("server_pid"))):
        return False
    if entry.get("kind") == "pages":
        return bool(entry.get("proxy_port")
                    and port_listening(entry["proxy_port"]))
    if entry.get("proxy_port") and not port_listening(entry["proxy_port"]):
        return False
    try:
        target = int(entry.get("target"))
    except (TypeError, ValueError):
        return False
    return 1 <= target <= 65535 and port_listening(target)


def core_list():
    """全部发布条目（死亡条目保留给健康监控自愈，stop 才移除）。"""
    entries = load_state()
    domain = load_domain() or {}
    for e in entries:
        e["alive"] = entry_alive(e)
        e["share_url"] = entry_share_url(e, domain)
        if e.get("auth_kind") and not upstream.read_auth(e.get("id")):
            # 密钥文件不在了就别在卡片上谎称已代填（详情抽屉读的是同一份真相）
            e.pop("auth_kind")
    return entries


def find_entry(target):
    """按 id / 名称 / 网址定位一个发布条目；自检和兼容设置都从这里拿。"""
    for e in load_state():
        if target in (e.get("id"), e.get("name"), e.get("url")):
            return e
    raise PanwebError(2, "not_found", "没有找到匹配「%s」的发布" % target,
                      "用 panweb list 查看已发布的应用")


def core_stop(target):
    stopped = []
    with state_lock():
        entries = load_state()
        if target == "all":
            hits = list(entries)
        else:
            hits = [e for e in entries
                    if target in (e.get("id"), e.get("name"), e.get("url"))]
        if not hits and target != "all":
            raise PanwebError(2, "not_found", "没有找到匹配「%s」的发布" % target,
                              "用 panweb list 查看已发布的应用")
        hit_ids = {e.get("id") for e in hits}
        for e in hits:
            stop_entry(e)
            stopped.append({"id": e.get("id"), "name": e.get("name"),
                            "url": e.get("url")})
            log_activity("stop", "停止了「%s」" % e.get("name"), e.get("url"))
        remaining = [e for e in entries if e.get("id") not in hit_ids]
        save_state(remaining)
        bump_stopped(len(stopped))
    write_menubar_state()
    return stopped


def core_compat(target, host_mode=None, auth_kind=None, token="", user="",
                password="", header_name="", header_value="", clear_auth=False):
    """设置一个发布的上游兼容项：Host 怎么传、要不要替访客带上应用自己的凭据。

    返回值只带脱敏描述——密钥留在 ``secrets/``，不经过这里，也就不会进日志。
    直连发布的请求链路里没有 panweb，改这些不会生效，所以先让人把发布切到代理。
    """
    entry = find_entry(target)
    entry_id = entry["id"]
    if not entry.get("proxy_port") and (host_mode is not None or auth_kind
                                         or clear_auth):
        raise PanwebError(
            3, "not_supported",
            "「%s」是直连发布，panweb 不在请求链路上，改了也不会生效"
            % (entry.get("name") or entry_id),
            "重新发布并走代理：panweb publish <端口> --share，"
            "或在详情抽屉里设置访问口令/开启分享页（直连发布会换网址）")
    changed = []
    if host_mode is not None:
        mode = upstream.normalize_host_mode(host_mode)
        if mode != upstream.host_mode(entry):
            upstream.set_host_mode(entry_id, mode)
            changed.append("Host 模式改为「%s」"
                           % upstream.HOST_MODE_LABELS[mode])
    else:
        mode = upstream.host_mode(entry)
    if clear_auth:
        if upstream.read_auth(entry_id):
            upstream.clear_auth(entry_id)
            changed.append("已清除上游凭据")
    elif auth_kind:
        rec = upstream.normalize_auth(auth_kind, token, user, password,
                                      header_name, header_value)
        upstream.set_auth(entry_id, rec)
        changed.append("已设置上游凭据（%s）" % upstream.AUTH_LABELS[rec["kind"]])
    if changed:
        log_activity("compat", "「%s」：%s" % (entry.get("name"), "；".join(changed)),
                     entry.get("url"))
    return {"id": entry_id, "name": entry.get("name"), "host_mode": mode,
            "host_mode_label": upstream.HOST_MODE_LABELS[mode],
            "host_modes": [{"value": m, "label": upstream.HOST_MODE_LABELS[m]}
                           for m in upstream.HOST_MODES],
            "proxied": bool(entry.get("proxy_port")),
            "auth": upstream.describe_auth(entry_id),
            "auth_changes": changed}


def core_stats():
    apps = core_list()
    attention = [a for a in apps if a.get("risky")]
    return {
        "total": len(apps),
        "online": sum(1 for a in apps if a.get("alive")),
        "stopped_total": load_meta().get("stopped_total", 0),
        "attention": len(attention),
        "attention_items": [{"id": a["id"], "name": a["name"],
                             "risky": a["risky"]} for a in attention],
    }


def write_menubar_state():
    try:
        online = sum(1 for a in core_list() if a.get("alive"))
        save_json(runtime.MENUBAR_STATE, {"online": online, "ts": time.time()})
    except Exception:  # noqa: BLE001
        pass
