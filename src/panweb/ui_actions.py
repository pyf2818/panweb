"""控制台 API 路由：GET 查询与 POST 动作。"""
import os
import re
import signal
import threading
import time
import urllib.parse

from . import runtime, ui_context
from .agents import (AGENT_GUIDE, core_agent_connect, core_agent_disconnect,
                     core_agents, skill_source_dir)
from .browser import open_browser
from .discovery import core_discover, core_doctor
from .domain import (core_domain_bind, core_domain_login,
                     core_domain_setup, core_domain_status,
                     core_domain_teardown)
from .entries import (core_compat, core_list, core_stats, core_stop,
                      stop_entry)
from .errors import PanwebError
from .healthcheck import core_check
from .hosting import core_host, core_host_redeploy, load_hosted
from .installer import core_install_cf, core_install_cf_status
from .licensing import (activate_license, deactivate_license,
                        license_status, require_publish_license)
from .menubar import core_install_menubar
from .models import entry_share_url
from .pins import normalize_pin, write_pin
from .publish import (_publish_port, core_detect, core_pages, core_publish,
                      core_run)
from .share import new_share_token
from .store import (load_activity, load_domain, load_meta, load_state,
                    log_activity, save_meta, save_state, state_lock)
from .supervisor import restart_entry_tunnel
from .system import core_pack, core_system
from .visits import aggregate_visits


def _query(handler):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)


def _first(q, key, default=""):
    return (q.get(key) or [default])[0]


def handle_get(handler, path):
    if path == "/api/state":
        apps = core_list()
        for e in apps:
            e["pv"] = aggregate_visits(e["id"])
        return handler.send_json({"ok": True, "data": {
            "doctor": core_doctor(),
            "apps": apps,
            "hosted": load_hosted(),
            "stats": core_stats(),
            "activity": list(reversed(load_activity()))[:20],
            "visits_recent": (ui_context.VISIT_NOTIFIER.snapshot()
                              if ui_context.VISIT_NOTIFIER else []),
            "notify_visits": load_meta().get("notify_visits", True),
            "license": license_status(),
        }}) or True
    if path == "/api/discover":
        return handler.send_json({"ok": True, "data": {
            "candidates": core_discover()}}) or True
    if path == "/api/detect":
        folder = _first(_query(handler), "folder")
        return handler.send_json({"ok": True, "data": core_detect(folder)}) or True
    if path == "/api/visits":
        q = _query(handler)
        entry_id = _first(q, "id")
        try:
            hours = min(int(_first(q, "hours", "24") or 24), 168)
        except ValueError:
            hours = 24
        if not any(e["id"] == entry_id for e in core_list()):
            return handler.send_json({"ok": False, "error": {
                "type": "not_found", "message": "应用不存在"}}) or True
        return handler.send_json({"ok": True, "data": aggregate_visits(
            entry_id, hours)}) or True
    if path == "/api/log":
        q = _query(handler)
        entry_id = _first(q, "id")
        try:
            lines = min(int(_first(q, "lines", "80") or 80), 300)
        except ValueError:
            lines = 80
        hits = [e for e in core_list() if e["id"] == entry_id]
        if not hits:
            return handler.send_json({"ok": False, "error": {
                "type": "not_found", "message": "应用不存在"}}) or True
        entry = hits[0]
        log_file = entry.get("app_log") or os.path.join(
            runtime.LOG_DIR, "%s.log" % entry_id)
        if not os.path.isfile(log_file):
            log_file = os.path.join(runtime.LOG_DIR, "%s-proxy.log" % entry_id)
        try:
            with open(log_file, "rb") as f:
                data = f.read()[-16000:].decode("utf-8", "replace")
            tail = data.splitlines()[-lines:]
        except OSError:
            tail = []
        return handler.send_json({"ok": True, "data": {
            "log": tail, "file": log_file}}) or True
    if path == "/api/agents":
        return handler.send_json({"ok": True, "data": {
            "agents": core_agents()}}) or True
    if path == "/api/compat":
        return handler.send_json({"ok": True, "data": core_compat(
            _first(_query(handler), "id"))}) or True
    if path == "/api/system":
        return handler.send_json({"ok": True, "data": core_system()}) or True
    if path == "/api/domain":
        return handler.send_json({"ok": True, "data": core_domain_status()}) or True
    if path == "/api/install-cf/status":
        return handler.send_json({"ok": True, "data": core_install_cf_status()}) or True
    if path == "/api/doctor":
        return handler.send_json({"ok": True, "data": core_doctor()}) or True
    if path == "/api/license":
        return handler.send_json({"ok": True, "data": license_status()}) or True
    return False


def handle_post(handler, path, body):
    if path == "/api/publish":
        entry = core_publish(body.get("port"), body.get("name"),
                             pin=body.get("pin"), expires=body.get("expires"),
                             share=bool(body.get("share")))
        return handler.send_json({"ok": True, "data": entry}) or True
    if path == "/api/pages":
        entry = core_pages(body.get("folder"), body.get("name"),
                           pin=body.get("pin"), expires=body.get("expires"))
        return handler.send_json({"ok": True, "data": entry}) or True
    if path == "/api/run":
        entry = core_run(body.get("folder"), body.get("name"),
                         share=bool(body.get("share")))
        return handler.send_json({"ok": True, "data": entry}) or True
    if path == "/api/stop":
        stopped = core_stop(body.get("target") or "all")
        return handler.send_json({"ok": True, "data": {
            "stopped": stopped}}) or True
    if path == "/api/rename":
        return _rename(handler, body) or True
    if path == "/api/pin":
        return _set_pin(handler, body) or True
    if path == "/api/check":
        return handler.send_json({"ok": True, "data": core_check(
            body.get("id") or "", auto_fix=not body.get("no_fix"))}) or True
    if path == "/api/compat":
        return handler.send_json({"ok": True, "data": core_compat(
            body.get("id") or "", host_mode=body.get("host_mode"),
            auth_kind=body.get("auth_kind"), token=body.get("token") or "",
            user=body.get("user") or "", password=body.get("password") or "",
            header_name=body.get("header_name") or "",
            header_value=body.get("header_value") or "",
            clear_auth=bool(body.get("clear_auth")))}) or True
    if path == "/api/share":
        return _share(handler, body) or True
    if path == "/api/notify-visits":
        enabled = bool(body.get("enabled"))
        meta = load_meta()
        meta["notify_visits"] = enabled
        save_meta(meta)
        log_activity("ui", "访客提醒已%s" % ("开启" if enabled else "关闭"))
        return handler.send_json({"ok": True, "data": {
            "enabled": enabled}}) or True
    if path == "/api/owner-open":
        entry_id = body.get("id")
        if not entry_id:
            return handler.send_json({"ok": True, "data": {
                "owner": False}}) or True
        meta = load_meta()
        now = time.time()
        grace = {k: v for k, v in (meta.get("owner_grace") or {}).items()
                 if v > now}
        grace[entry_id] = now + 15
        meta["owner_grace"] = grace
        save_meta(meta)
        return handler.send_json({"ok": True, "data": {
            "owner": True}}) or True
    if path == "/api/agents/connect":
        return handler.send_json({"ok": True, "data": core_agent_connect(
            body.get("id"))}) or True
    if path == "/api/agents/disconnect":
        return handler.send_json({"ok": True, "data": core_agent_disconnect(
            body.get("id"))}) or True
    if path == "/api/agents/guide":
        src = skill_source_dir()
        return handler.send_json({"ok": True, "data": {
            "guide": AGENT_GUIDE.format(
                src=src or "(未找到技能源，请先运行 install.sh)")}}) or True
    if path == "/api/pack":
        return handler.send_json({"ok": True, "data": core_pack(
            body.get("folder"))}) or True
    if path == "/api/domain/login":
        return handler.send_json({"ok": True, "data": core_domain_login()}) or True
    if path == "/api/domain/setup":
        return handler.send_json({"ok": True, "data": core_domain_setup(
            body.get("domain"), body.get("name"))}) or True
    if path == "/api/domain/bind":
        return handler.send_json({"ok": True, "data": core_domain_bind(
            body.get("id"))}) or True
    if path == "/api/domain/teardown":
        return handler.send_json({"ok": True, "data": core_domain_teardown()}) or True
    if path == "/api/install-cf":
        return handler.send_json({"ok": True, "data": core_install_cf()}) or True
    if path == "/api/install-menubar":
        return handler.send_json({"ok": True, "data": core_install_menubar()}) or True
    if path == "/api/license/activate":
        status = activate_license((body.get("key") or "").strip())
        log_activity("ui", "许可已激活")
        return handler.send_json({"ok": True, "data": status}) or True
    if path == "/api/license/deactivate":
        result = deactivate_license()
        log_activity("ui", "已解除本机许可绑定")
        return handler.send_json({"ok": True, "data": result}) or True
    if path == "/api/open-dir":
        return _open_dir(handler, body) or True
    if path == "/api/recover":
        return _recover(handler) or True
    if path == "/api/host":
        return handler.send_json({"ok": True, "data": core_host(
            body.get("path"), body.get("name"))}) or True
    if path == "/api/host-upload":
        return handler.send_json({"ok": True, "data": core_host(
            None, body.get("name"), files=body.get("files"))}) or True
    if path == "/api/host-redeploy":
        return handler.send_json({"ok": True, "data": core_host_redeploy(
            body.get("name"))}) or True
    if path == "/api/shutdown":
        log_activity("ui", "控制台已停止（页面操作）")
        threading.Timer(0.6, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        return handler.send_json({"ok": True, "data": {
            "stopping": True}}) or True
    return False


def _rename(handler, body):
    entry_id, name = body.get("id"), (body.get("name") or "").strip()
    if not entry_id or not name:
        handler.send_json({"ok": False, "error": {
            "type": "invalid_argument", "message": "缺少 id 或新名称"}})
        return True
    if len(name) > 80:
        handler.send_json({"ok": False, "error": {
            "type": "invalid_argument", "message": "名称过长（≤80）"}})
        return True
    with state_lock():
        entries = load_state()
        for e in entries:
            if e.get("id") == entry_id:
                old = e.get("name")
                e["name"] = name
                save_state(entries)
                log_activity("ui", "「%s」改名为「%s」" % (old, name))
                handler.send_json({"ok": True, "data": {
                    "id": entry_id, "name": name}})
                return True
    handler.send_json({"ok": False, "error": {
        "type": "not_found", "message": "应用不存在"}})
    return True


def _set_pin(handler, body):
    entry_id, pin = body.get("id"), (body.get("pin") or "").strip()
    hits = [e for e in load_state() if e.get("id") == entry_id]
    if not hits:
        handler.send_json({"ok": False, "error": {
            "type": "not_found", "message": "应用不存在"}})
        return True
    entry = hits[0]
    if pin:
        try:
            pin = normalize_pin(pin)
        except PanwebError as e:
            handler.send_json(e.to_dict())
            return True
    had_proxy = bool(entry.get("proxy_port"))
    if not had_proxy and pin:
        require_publish_license()
        extra = {k: entry[k] for k in
                 ("app_pid", "app_log", "launched", "risky") if k in entry}
        stop_entry(entry)
        with state_lock():
            entries = [e for e in load_state() if e.get("id") != entry_id]
            save_state(entries)
        new_entry = _publish_port(entry.get("target"), entry.get("name"),
                                  pin=pin, extra=extra,
                                  expires_at=entry.get("expires_at"))
        log_activity("ui", "为「%s」设置了访问口令（网址已更新）"
                     % entry.get("name"), new_entry["url"])
        handler.send_json({"ok": True, "data": {
            "updated": True, "entry": new_entry}})
        return True
    write_pin(entry_id, pin or None)
    log_activity("ui", ("为「%s」设置了访问口令" if pin
                        else "「%s」的访问口令已移除") % entry.get("name"))
    handler.send_json({"ok": True, "data": {"updated": True, "entry": entry}})
    return True


def _share(handler, body):
    entry_id = body.get("id")
    desc = (body.get("desc") or "").strip()
    desc = re.sub(r"[\x00-\x1f\x7f]+", " ", desc)[:120]
    with state_lock():
        entries = load_state()
        for e in entries:
            if e.get("id") != entry_id:
                continue
            if not e.get("proxy_port"):
                handler.send_json({"ok": False, "error": {
                    "type": "not_supported",
                    "message": "直连发布不支持分享页；重新发布时勾选「分享页 + 访问统计」"}})
                return True
            if not e.get("share_token"):
                e["share_token"] = new_share_token()
            if desc:
                e["desc"] = desc
            else:
                e.pop("desc", None)
            save_state(entries)
            log_activity("ui", "更新了「%s」的分享页说明" % e.get("name"))
            handler.send_json({"ok": True, "data": {
                "id": entry_id, "desc": desc,
                "share_url": entry_share_url(e, load_domain() or {})}})
            return True
    handler.send_json({"ok": False, "error": {
        "type": "not_found", "message": "应用不存在"}})
    return True


def _open_dir(handler, body):
    p = os.path.realpath(os.path.abspath(
        os.path.expanduser(body.get("dir") or "")))
    home_real = os.path.realpath(runtime.HOME_DIR)
    try:
        inside = os.path.commonpath([home_real, p]) == home_real
    except ValueError:
        inside = False
    if not inside or not os.path.isdir(p):
        handler.send_json({"ok": False, "error": {
            "type": "invalid_argument", "message": "目录不在数据目录内"}})
        return True
    open_browser(p)
    handler.send_json({"ok": True, "data": {"opened": p}})
    return True


def _recover(handler):
    done = []
    for entry in load_state():
        try:
            url = restart_entry_tunnel(entry)
            done.append({"id": entry["id"], "name": entry["name"],
                         "url": url})
        except Exception as e:  # noqa: BLE001
            log_activity("ui", "「%s」手动恢复失败：%s"
                         % (entry.get("name"), e))
    log_activity("ui", "手动重启了全部通道（%d 个）" % len(done))
    handler.send_json({"ok": True, "data": {"recovered": done}})
    return True
