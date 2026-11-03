"""一键诊断包：把能定位问题的东西打成一个**脱敏** zip，发不发由主人决定。

原则：只收本机自己写的状态与日志，绝不收凭据。secrets/、pins/、visits/ 与许可密钥
本体一律排除；分享令牌、Cloudflare 令牌、密码这类字段即便混在状态里也会被抹成掩码。
"""
import json
import os
import platform
import re
import time
import zipfile

from . import runtime
from .discovery import core_doctor
from .entries import core_list
from .licensing import license_status
from .store import load_activity, load_domain, load_meta, load_state
from .system import core_system

MAX_LOG_BYTES = 200000        # 单个日志只取尾部，够看最近一次故障
ACTIVITY_KEEP = 300
SECRET_WORDS = ("token", "password", "passwd", "secret", "pin", "key",
                "cookie", "authorization")
EXCLUDED_DIRS = ("secrets", "pins", "visits")
# 日志正文没有结构化字段可依，只能按凭据形态扫：key=value、Cookie、
# panweb_auth、JWT/Bearer 这几类在真实日志里出现过就抹掉。
_SECRET_TEXT_RE = re.compile(
    r"(?i)(panweb_auth=)[0-9a-f]{8,}"
    r"|((?:authorization)[\"']?\s*[=:]\s*[\"']?"
    r"(?:(?:bearer|basic|token)\s+)?)"
    r"[^\s\"'&,;}]{6,}"
    r"|((?:share_token|share|api_key|access_token|token|password|passwd|"
    r"secret|pin)[\"']?\s*[=:]\s*[\"']?)"
    r"[^\s\"'&,;}]{6,}"
    r"|(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
    r"|(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}")


def _scrub_text(text):
    """把日志正文里的凭据形态统一抹掉，保留其余可诊断信息。"""
    return _SECRET_TEXT_RE.sub("***已省略***", text)


def _is_secret(key):
    low = str(key).lower()
    return any(w in low for w in SECRET_WORDS)


def _mask(value):
    if value in (None, "", [], {}):
        return None
    return "***已省略***"


def clean(obj):
    """递归去掉密钥：留下"这里有几个字符"这类可诊断的信息。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret(k):
                if isinstance(v, str) and len(v) > 8:
                    out[k] = "%s…（%d 位，已省略）" % (v[:4], len(v))
                else:
                    out[k] = _mask(v)
            else:
                out[k] = clean(v)
        return out
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    return obj


def _log_tails():
    """返回 (相对路径, 内容) 列表：logs/ 下的文本与 App 日志尾部。"""
    out = []
    if not os.path.isdir(runtime.LOG_DIR):
        return out
    for name in sorted(os.listdir(runtime.LOG_DIR)):
        if name.startswith("._") or not os.path.isfile(
                os.path.join(runtime.LOG_DIR, name)):
            continue
        path = os.path.join(runtime.LOG_DIR, name)
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                if size > MAX_LOG_BYTES:
                    f.seek(size - MAX_LOG_BYTES)
                body = f.read().decode("utf-8", "replace")
        except OSError:
            continue
        out.append(("logs/%s" % name,
                    _scrub_text(
                        ("（原文件 %d 字节，这里只保留尾部 %d 字节）\n"
                         % (size, MAX_LOG_BYTES) if size > MAX_LOG_BYTES else "")
                        + body)))
    return out


def _summary_text(meta, apps):
    lines = [
        "panweb 诊断包（已脱敏）",
        "生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "版本：%s / cloudflared %s" % (meta["panweb_version"],
                                      meta["cloudflared_version"]),
        "系统：%s %s / Python %s" % (meta["system"], meta["machine"],
                                    meta["python"]),
        "数据目录：%s" % meta["data_dir"],
        "",
        "发布 %d 个（在线 %d）：" % (meta["apps_total"], meta["apps_online"]),
    ]
    for a in apps:
        lines.append("  - %s [%s] %s %s" % (
            a.get("name"), a.get("id"), a.get("url"),
            "在线" if a.get("alive") else "已停止"))
    lines += ["", "已排除的内容：" + "、".join(EXCLUDED_DIRS) +
              "（凭据、口令、访客记录）与许可密钥本体；"
              "日志正文已按凭据形态扫描，命中即抹成掩码"]
    return "\n".join(lines) + "\n"


def core_report(out_dir=None):
    """打包诊断信息，返回 zip 路径与清单（不含任何凭据）。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = os.path.abspath(os.path.expanduser(
        out_dir or os.path.join(runtime.HOME_DIR, "reports")))
    os.makedirs(target, exist_ok=True)
    out = os.path.join(target, "panweb-report-%s.zip" % stamp)
    doctor = clean(core_doctor())
    system = clean(core_system())
    apps = clean(core_list())
    meta = {
        "panweb_version": runtime.PANWEB_VERSION,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                    time.localtime(runtime.STARTED_AT)),
        "python": platform.python_version(),
        "system": "%s %s" % (platform.system(), platform.release()),
        "machine": platform.machine(),
        "zipapp": runtime.is_zipapp(),
        "resource_root": runtime.resource_root(),
        "data_dir": runtime.HOME_DIR,
        "cloudflared_version": system.get("cloudflared_version"),
        "apps_total": system.get("apps_total"),
        "apps_online": system.get("apps_online"),
    }
    files = {
        "report.txt": _summary_text(meta, apps),
        "meta.json": meta,
        "doctor.json": doctor,
        "system.json": system,
        "state.json": clean(load_state()),
        "activity.json": clean(load_activity())[-ACTIVITY_KEEP:],
        "domain.json": clean(load_domain() or {}),
        "prefs.json": clean(load_meta()),
        "license.json": clean(license_status(start_trial=False)),
    }
    files.update(dict(_log_tails()))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in files.items():
            text = body if isinstance(body, str) else json.dumps(
                body, ensure_ascii=False, indent=2)
            z.writestr("panweb-report-%s/%s" % (stamp, name), text)
    leaked = _audit(out)
    if leaked:
        try:
            os.remove(out)
        except OSError:
            pass
        raise AssertionError("诊断包混进了密钥字段：%s" % ", ".join(leaked))
    return {"zip": out, "size": os.path.getsize(out),
            "included": sorted(files), "excluded": list(EXCLUDED_DIRS)}


def _audit(path):
    """自我审查：把包再读一遍——文件名不许是凭据文件，JSON 里的密钥字段必须已是掩码。"""
    bad = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            rel = name.split("/", 1)[-1]
            if rel.startswith(EXCLUDED_DIRS) or rel.endswith(
                    (".auth.json", ".pin.json")):
                bad.append(rel)
                continue
            if not rel.endswith(".json"):
                text = z.read(name).decode("utf-8", "replace")
                if _SECRET_TEXT_RE.search(text):
                    bad.append("%s 含未脱敏凭据" % rel)
                continue
            try:
                _check_masked(json.loads(z.read(name).decode("utf-8")), rel,
                              bad)
            except ValueError:
                bad.append("%s 不是合法 JSON" % rel)
    return bad


def _check_masked(obj, where, bad):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _is_secret(k) and isinstance(v, str) and len(v) > 8 \
                    and "已省略" not in v:
                bad.append("%s 的 %s 没脱敏" % (where, k))
            _check_masked(v, where, bad)
    elif isinstance(obj, list):
        for item in obj:
            _check_masked(item, where, bad)
