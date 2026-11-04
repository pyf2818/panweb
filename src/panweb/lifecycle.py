"""有效期解析、到期收回与陈旧条目清理。"""
import math
import time

from . import events, last_deploy
from .entries import entry_alive, stop_entry, write_menubar_state
from .errors import PanwebError
from .store import (bump_stopped, load_domain, load_state, log_activity,
                    save_state, state_lock)
from .visits import aggregate_visits

EXPIRES_PRESETS = {"1h": 3600, "1d": 86400, "7d": 604800}


def parse_expires(value):
    """'1h'/'1d'/'7d' → 时间戳；None/'' → None（永久）。非法值抛错。"""
    if not value:
        return None
    if value in EXPIRES_PRESETS:
        return time.time() + EXPIRES_PRESETS[value]
    try:
        ts = float(value)
        return ts if ts > time.time() else None
    except (TypeError, ValueError):
        raise PanwebError(2, "invalid_argument", "有效期需为 1h / 1d / 7d")


def sweep_expired():
    """收回已到期的发布（健康巡检与启动时调用）。"""
    now = time.time()
    swept = []
    with state_lock():
        entries = load_state()
        domain = load_domain() or {}
        keep = []
        for entry in entries:
            exp = entry.get("expires_at")
            broken = False
            ts = None
            if exp:
                try:
                    if isinstance(exp, bool):
                        raise ValueError
                    ts = float(exp)
                    if not math.isfinite(ts):
                        raise ValueError
                except (TypeError, ValueError):
                    # 脏数据不能把整个巡检线程打死；按立即到期收回并留证。
                    ts, broken = now, True
            if ts is not None and ts <= now:
                reason = "invalid_expires_at" if broken else "expired"
                visits = (aggregate_visits(entry.get("id"))
                          if entry.get("proxy_port") else None)
                last_deploy.remember_last(entry, reason=reason,
                                          visits=visits, domain=domain)
                stop_entry(entry)
                swept.append(entry.get("name"))
                message = ("「%s」有效期字段损坏（%r），已按到期自动收回"
                           % (entry.get("name"), exp)) if broken else (
                    "「%s」已到期，自动收回" % entry.get("name"))
                log_activity("stop", message, entry.get("url"))
                events.log_event(entry.get("id"), "expire", message,
                                 url_before=entry.get("url"),
                                 expires_at=entry.get("expires_at"),
                                 source="system", reason=reason)
            else:
                keep.append(entry)
        if swept:
            save_state(keep)
            bump_stopped(len(swept))
    if swept:
        write_menubar_state()
    return swept


def prune_dead_entries(max_age_days=7):
    """清理长期离线且进程已不存在的发布，避免状态无限增长。"""
    now = time.time()
    removed = []
    with state_lock():
        domain = load_domain() or {}
        keep = []
        for entry in load_state():
            try:
                started = time.mktime(time.strptime(entry.get("started", ""),
                                                    "%Y-%m-%d %H:%M:%S"))
            except (TypeError, ValueError):
                started = now
            if now - started > max_age_days * 86400 \
                    and not entry_alive(entry):
                last_deploy.remember_last(entry, reason="cleanup",
                                          domain=domain)
                stop_entry(entry)
                removed.append(entry.get("name"))
                events.log_event(entry.get("id"), "stop",
                                 "清理长期离线的「%s」" % entry.get("name"),
                                 url_before=entry.get("url"),
                                 source="system", reason="cleanup")
            else:
                keep.append(entry)
        if removed:
            save_state(keep)
    if removed:
        log_activity("ui", "清理了 %d 个长期离线的发布" % len(removed))
    return removed
