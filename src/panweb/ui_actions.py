"""控制台 API 路由：GET 查询与 POST 动作。"""
import http.client
import os
import signal
import threading
import time
import urllib.parse

from . import deployment, events, jobs, last_deploy, runtime, ui_context
from .agents import (AGENT_GUIDE, core_agent_connect, core_agent_disconnect,
                     core_agents, core_terminal_agents, skill_source_dir)
from .browser import open_browser
from .commands import parse_command
from .discovery import core_discover, core_doctor
from .diagnostics import core_report
from .domain import (core_domain_bind, core_domain_login,
                     core_domain_setup, core_domain_status,
                     core_domain_teardown)
from .entries import core_compat, core_list, core_stats, core_stop
from .folders import core_folders
from .healthcheck import core_check
from .hosting import core_host, core_host_redeploy, load_hosted
from .installer import core_install_cf, core_install_cf_status
from .licensing import (activate_license, deactivate_license,
                        license_status)
from .menubar import core_install_menubar
from .models import entry_port, entry_share_url
from .publish import (core_detect, core_pages, core_publish, core_run,
                      core_set_pin, load_publish_defaults, normalize_desc)
from .share import new_share_token
from .store import (json_lock, load_activity, load_domain, load_meta,
                    load_state, log_activity, save_meta, save_state,
                    state_issue, state_lock)
from .supervisor import recover_failing
from .system import core_pack, core_system
from .term import (core_terminal_close, core_terminal_input,
                   core_terminal_open, core_terminal_resize,
                   core_terminal_sessions, core_terminal_stream)
from .update import core_update_apply, core_update_status
from .visits import aggregate_visits


def _query(handler):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query)


def _first(q, key, default=""):
    return (q.get(key) or [default])[0]


PREVIEW_BLOCK_REASON = "该应用禁止内嵌，请用打开"
PREVIEW_DOWN_REASON = "本机预览加载失败，请用打开"


def _preview_url(entry):
    """预览只允许本机代理端口或源端口；绝不返回公网地址。"""
    if entry.get("proxy_port"):
        return "http://127.0.0.1:%d/" % int(entry["proxy_port"])
    port = entry_port(entry)
    if port is not None:
        return "http://127.0.0.1:%d/" % int(port)
    return None


def _preview_embed_check(url):
    """HEAD 一次目标，按 X-Frame-Options / CSP frame-ancestors 判断能否内嵌。"""
    parts = urllib.parse.urlsplit(url)
    try:
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=2)
        try:
            conn.request("HEAD", parts.path or "/")
            resp = conn.getresponse()
            resp.read()
            headers = resp.headers
        finally:
            conn.close()
    except (OSError, http.client.HTTPException, ValueError):
        return False, PREVIEW_DOWN_REASON
    xfo = (headers.get("X-Frame-Options") or "").strip().lower()
    if xfo.startswith("deny") or xfo.startswith("sameorigin"):
        return False, PREVIEW_BLOCK_REASON
    csp = headers.get("Content-Security-Policy") or ""
    for directive in csp.split(";"):
        name, _, rest = directive.strip().partition(" ")
        if name.strip().lower() != "frame-ancestors":
            continue
        sources = rest.replace("'", " ").split()
        if not sources:
            return False, PREVIEW_BLOCK_REASON
        if "*" in sources:
            return True, ""
        allowed = any(s in ("127.0.0.1", "localhost", "127.0.0.1:*",
                            "localhost:*", "http://127.0.0.1",
                            "http://127.0.0.1:*", "http://localhost",
                            "http://localhost:*") for s in sources)
        return allowed, "" if allowed else PREVIEW_BLOCK_REASON
    return True, ""


def _preview_payload(entry_id):
    """解析真实条目的本机预览地址；只读，不写状态、不记录口令。"""
    entry = next((e for e in core_list() if e.get("id") == entry_id), None)
    if not entry:
        return None, {"type": "not_found",
                      "message": "该条目没有本机预览，请用打开"}
    if not entry.get("alive"):
        return None, {"type": "not_found",
                      "message": "应用已停止，右栏可用同样配置重新发布"}
    url = _preview_url(entry)
    if not url:
        return None, {"type": "not_found",
                      "message": "该条目没有本机端口，无法预览"}
    embeddable, reason = _preview_embed_check(url)
    return {"id": entry_id, "url": url, "embeddable": embeddable,
            "reason": reason,
            "source": "proxy" if entry.get("proxy_port") else "port"}, None


def handle_get(handler, path):
    if path == "/api/state":
        apps = core_list()
        for e in apps:
            e["pv"] = aggregate_visits(e["id"])
        return handler.send_json({"ok": True, "data": {
            "doctor": core_doctor(),
            "apps": apps,
            "last_deployments": last_deploy.load_snapshots(apps),
            "state_issue": state_issue(),
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
    if path == "/api/publish-defaults":
        return handler.send_json({"ok": True, "data": {
            "defaults": load_publish_defaults(),
            "candidates": core_discover()}}) or True
    if path == "/api/job":
        job = jobs.get(_first(_query(handler), "id"))
        if not job:
            return handler.send_json({"ok": False, "error": {
                "type": "not_found", "message": "任务不存在或控制台已重启"}}) or True
        return handler.send_json({"ok": True, "data": job}) or True
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
    if path == "/api/history":
        q = _query(handler)
        entry_id = _first(q, "id") or None
        try:
            limit = min(max(int(_first(q, "limit", "30") or 30), 1),
                        events.MAX_LIMIT)
        except ValueError:
            limit = 30
        rows = events.read_events(entry_id, limit)
        data = {"events": rows}
        if entry_id:
            entry = next((e for e in load_state()
                          if e.get("id") == entry_id), None)
            snap = None if entry else last_deploy.find_snapshot(entry_id)
            entry = entry or snap
            if entry:
                stats = (snap.get("pv") if snap
                         else aggregate_visits(entry_id))
                detail = deployment.build_detail(
                    entry, events.read_events(entry_id, events.MAX_LIMIT),
                    load_domain(), stats)
                if snap and detail:
                    detail["from_snapshot"] = True
                    detail["stopped_at"] = snap.get("stopped_at")
                    detail["stop_reason"] = snap.get("stop_reason")
                    detail["expires_text"] = (snap.get("expires_text")
                                              or detail.get("expires_text"))
                data["detail"] = detail
        return handler.send_json({"ok": True, "data": data}) or True
    if path == "/api/preview":
        data, error = _preview_payload(_first(_query(handler), "id"))
        if error:
            return handler.send_json({"ok": False, "error": error}) or True
        return handler.send_json({"ok": True, "data": data}) or True
    if path == "/api/agents":
        return handler.send_json({"ok": True, "data": {
            "agents": core_agents()}}) or True
    if path == "/api/term/agents":
        return handler.send_json({"ok": True, "data": {
            "agents": core_terminal_agents()}}) or True
    if path == "/api/term/sessions":
        return handler.send_json({"ok": True, "data": {
            "sessions": core_terminal_sessions()}}) or True
    if path == "/api/term/output":
        query = _query(handler)
        core_terminal_stream(handler, _first(query, "id"),
                             _first(query, "after") or 0)
        return True
    if path == "/api/folders":
        return handler.send_json({"ok": True, "data": core_folders(
            _first(_query(handler), "path"))}) or True
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
    if path == "/api/update":
        return handler.send_json({"ok": True, "data": core_update_status()}) or True
    return False


def _run_or_job(handler, body, kind, fn):
    """慢动作可以异步跑：返回 job id，前端轮询拿步骤与结果。"""
    if body.get("async"):
        target = body.get("port") or body.get("folder")
        job_id = jobs.start(kind, fn, key=target)
        return handler.send_json({"ok": True, "data": {
            "job": job_id, "kind": kind}}) or True
    return handler.send_json({"ok": True, "data": fn(None)}) or True


def handle_post(handler, path, body):
    if path == "/api/command":
        parsed = parse_command(body.get("text") or "", load_publish_defaults())
        if not parsed.get("ok"):
            return handler.send_json({"ok": False,
                                      "error": parsed["error"]}) or True
        return handler.send_json({"ok": True, "data": parsed}) or True
    if path == "/api/publish":
        return _run_or_job(handler, body, "publish", lambda progress: core_publish(
            body.get("port"), body.get("name"), pin=body.get("pin"),
            expires=body.get("expires"), share=bool(body.get("share")),
            progress=progress, title=body.get("title"),
            desc=body.get("desc"))) or True
    if path == "/api/pages":
        return _run_or_job(handler, body, "pages", lambda progress: core_pages(
            body.get("folder"), body.get("name"), pin=body.get("pin"),
            expires=body.get("expires"), progress=progress,
            title=body.get("title"), desc=body.get("desc"))) or True
    if path == "/api/run":
        return _run_or_job(handler, body, "run", lambda progress: core_run(
            body.get("folder"), body.get("name"),
            share=bool(body.get("share")), pin=body.get("pin"),
            expires=body.get("expires"), progress=progress,
            title=body.get("title"), desc=body.get("desc"))) or True
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
        with json_lock(runtime.META_FILE):
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
        now = time.time()
        with json_lock(runtime.META_FILE):
            meta = load_meta()
            grace = {k: v for k, v in (meta.get("owner_grace") or {}).items()
                     if v > now}
            grace[entry_id] = now + 15
            meta["owner_grace"] = grace
            save_meta(meta)
        return handler.send_json({"ok": True, "data": {
            "owner": True}}) or True
    if path == "/api/term/open":
        return handler.send_json({"ok": True, "data": core_terminal_open(
            body.get("agent"), cwd=body.get("cwd") or "",
            cols=body.get("cols") or 0, rows=body.get("rows") or 0)}) or True
    if path == "/api/term/input":
        return handler.send_json({"ok": True, "data": core_terminal_input(
            body.get("id"), body.get("data"))}) or True
    if path == "/api/term/resize":
        return handler.send_json({"ok": True, "data": core_terminal_resize(
            body.get("id"), body.get("cols"), body.get("rows"))}) or True
    if path == "/api/term/close":
        return handler.send_json({"ok": True, "data": core_terminal_close(
            body.get("id"))}) or True
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
    if path == "/api/report":
        return handler.send_json({"ok": True, "data": core_report(
            body.get("out"))}) or True
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
    if path == "/api/update/apply":
        return handler.send_json({"ok": True, "data": core_update_apply()}) or True
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
    data = core_set_pin(body.get("id"), (body.get("pin") or "").strip())
    handler.send_json({"ok": True, "data": data})
    return True


def _share(handler, body):
    entry_id = body.get("id")
    desc = normalize_desc(body.get("desc")) or ""
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
    """恢复可能耗时数分钟，放后台 job，避免阻塞控制台请求线程。"""
    job = jobs.start("recover", recover_failing)
    handler.send_json({"ok": True, "data": {"job": job, "kind": "recover"}})
    return True
