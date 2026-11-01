"""Cloudflare 命名隧道固定域名向导。"""
import hashlib
import json
import os
import re
import signal
import subprocess

from . import forwarder, runtime
from .errors import PanwebError
from .licensing import require_publish_license
from .models import entry_local_port
from .processes import find_cloudflared, free_port, kill_process, pid_alive
from .store import load_domain, load_state, log_activity, save_domain

CF_CERT = os.path.expanduser("~/.cloudflared/cert.pem")
DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)+$")


def core_domain_status():
    d = load_domain() or {}
    return {
        "cert": os.path.isfile(CF_CERT),
        "configured": bool(d.get("domain")),
        "domain": d.get("domain"),
        "tunnel_id": d.get("tunnel_id"),
        "running": bool(d.get("pid") and pid_alive(d["pid"])),
        "bound_id": d.get("bound_id"),
    }


def core_domain_login():
    """打开浏览器完成 cloudflared 授权（生成 cert.pem）。"""
    cf = find_cloudflared()
    if not cf:
        raise PanwebError(3, "dependency_missing", "未找到 cloudflared")
    if os.path.isfile(CF_CERT):
        return {"already": True}
    subprocess.Popen([cf, "tunnel", "login"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return {"started": True}


def _cf_run(args_list, timeout=90):
    cf = find_cloudflared()
    if not cf:
        raise PanwebError(3, "dependency_missing", "未找到 cloudflared")
    return subprocess.run([cf] + args_list, capture_output=True, text=True,
                          timeout=timeout)


def core_domain_setup(domain, name=None):
    """创建命名隧道 + DNS 路由 + 配置文件并启动（一次一个域名）。"""
    require_publish_license()
    domain = (domain or "").strip().lower()
    if not DOMAIN_RE.match(domain):
        raise PanwebError(2, "invalid_argument", "域名格式不对：%s" % domain)
    if not os.path.isfile(CF_CERT):
        raise PanwebError(2, "need_login", "尚未授权 Cloudflare",
                          "先点「授权 Cloudflare」在浏览器完成登录")
    steps = []
    tunnel_name = "panweb-" + hashlib.sha1(domain.encode()).hexdigest()[:8]
    old = load_domain()
    if old and pid_alive(old.get("pid")):
        try:
            os.killpg(os.getpgid(old["pid"]), signal.SIGTERM)
        except OSError:
            pass
    out = _cf_run(["tunnel", "create", tunnel_name])
    text = (out.stdout + out.stderr).strip()
    if out.returncode != 0 and "already exists" not in text:
        raise PanwebError(9, "domain_failed", "创建隧道失败：" + text[:300])
    steps.append("create ✅")
    tid = None
    lst = _cf_run(["tunnel", "list", "--output", "json"])
    try:
        for t in json.loads(lst.stdout or "[]"):
            if t.get("name") == tunnel_name:
                tid = t.get("id")
                break
    except ValueError:
        pass
    if not tid:
        raise PanwebError(9, "domain_failed", "无法获取隧道 ID",
                          lst.stdout[:300])
    out = _cf_run(["tunnel", "route", "dns", tid, domain])
    text = (out.stdout + out.stderr).strip()
    if out.returncode != 0 and "already exists" not in text:
        raise PanwebError(9, "domain_failed", "DNS 路由失败：" + text[:300])
    steps.append("dns ✅")
    local_port = free_port()
    cfg_dir = os.path.expanduser("~/.cloudflared")
    cfg = os.path.join(cfg_dir, "config-panweb.yml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("tunnel: %s\ncredentials-file: %s\ningress:\n"
                "  - hostname: %s\n    service: http://127.0.0.1:%d\n"
                "  - service: http_status:404\n"
                % (tid, os.path.join(cfg_dir, "%s.json" % tid),
                   domain, local_port))
    steps.append("config ✅")
    os.makedirs(runtime.LOG_DIR, exist_ok=True)
    logf = open(os.path.join(runtime.LOG_DIR, "domain.log"), "ab",
                buffering=0)
    cf = find_cloudflared()
    proc = subprocess.Popen(
        [cf, "tunnel", "--config", cfg, "run", tunnel_name],
        stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        start_new_session=True)
    logf.close()
    old_fw = forwarder.FORWARDERS.pop("domain", None)
    if old_fw:
        old_fw.stop()
    fw = forwarder.Forwarder(local_port)
    fw.start()
    forwarder.FORWARDERS["domain"] = fw
    save_domain({"domain": domain, "tunnel_id": tid,
                 "tunnel_name": tunnel_name, "pid": proc.pid,
                 "local_port": local_port, "bound_id": None})
    log_activity("ui", "固定域名已启用：%s（在应用详情里绑定）" % domain)
    return {"domain": domain, "tunnel_id": tid, "local_port": local_port,
            "steps": steps}


def core_domain_bind(entry_id=None):
    """把某个应用绑定到固定域名（同一时间一个应用）。"""
    d = load_domain()
    if not d or not d.get("domain"):
        raise PanwebError(2, "not_configured", "尚未配置固定域名")
    fw = forwarder.FORWARDERS.get("domain")
    if not fw:
        raise PanwebError(9, "domain_failed",
                          "固定域名转发器未运行，请重启控制台")
    if entry_id is None:
        fw.dest_port = None
        d["bound_id"] = None
        save_domain(d)
        log_activity("ui", "已解绑固定域名 %s" % d["domain"])
        return {"bound": None}
    hits = [e for e in load_state() if e["id"] == entry_id]
    if not hits:
        raise PanwebError(2, "not_found", "应用不存在")
    fw.retarget(entry_local_port(hits[0]))
    d["bound_id"] = entry_id
    save_domain(d)
    log_activity("ui", "「%s」已绑定到固定域名 %s"
                 % (hits[0]["name"], d["domain"]), "https://%s" % d["domain"])
    return {"bound": entry_id, "domain": d["domain"]}


def core_domain_teardown():
    d = load_domain()
    if d:
        kill_process(d.get("pid"), ("cloudflared", "tunnel"))
    fw = forwarder.FORWARDERS.pop("domain", None)
    if fw:
        fw.stop()
    try:
        os.remove(runtime.DOMAIN_FILE)
    except OSError:
        pass
    log_activity("ui", "固定域名已停用")
    return {"torn_down": True,
            "hint": "本地隧道已停用；Cloudflare 上的 DNS 记录仍在，可在 Cloudflare 控制台删除"}


def core_domain_recover():
    """控制台重启后恢复固定域名转发器与隧道进程。"""
    d = load_domain()
    if not d or not d.get("domain"):
        return None
    fw = forwarder.FORWARDERS.get("domain")
    if not fw:
        fw = forwarder.Forwarder(d["local_port"])
        fw.start()
        forwarder.FORWARDERS["domain"] = fw
    if d.get("bound_id"):
        hits = [e for e in load_state() if e["id"] == d["bound_id"]]
        if hits:
            fw.retarget(entry_local_port(hits[0]))
    if not pid_alive(d.get("pid")):
        cf = find_cloudflared()
        if not cf:
            return d
        cfg = os.path.join(os.path.expanduser("~/.cloudflared"),
                           "config-panweb.yml")
        logf = open(os.path.join(runtime.LOG_DIR, "domain.log"), "ab",
                    buffering=0)
        proc = subprocess.Popen(
            [cf, "tunnel", "--config", cfg, "run", d["tunnel_name"]],
            stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True)
        logf.close()
        d["pid"] = proc.pid
        save_domain(d)
    return d
