"""`panweb history` 的人读/JSON 回执，单独成文件以守住模块行数上限。"""
import json
import time

from . import events

EVENT_LABELS = {"publish": "发布", "restart": "重启", "url_change": "换网址",
                "pin_change": "改口令", "expire": "到期", "stop": "停止",
                "error": "出错"}


def _event_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return "-"


def cmd_history(args):
    entry_id = getattr(args, "id", None) or None
    try:
        limit = min(max(int(getattr(args, "limit", 30) or 30), 1),
                    events.MAX_LIMIT)
    except (TypeError, ValueError):
        limit = 30
    rows = events.read_events(entry_id, limit)
    if args.json:
        print(json.dumps({"ok": True, "data": {"events": rows,
                                               "limit": limit,
                                               "id": entry_id}},
                         ensure_ascii=False))
        return
    if not rows:
        print("还没有变更记录。发布、改口令、重建通道或停止后，"
              "这里会出现时间线。")
        return
    print("最近 %d 条变更%s：" % (len(rows),
                              "（%s）" % entry_id if entry_id else ""))
    for row in rows:
        detail = row.get("details") or {}
        label = EVENT_LABELS.get(row.get("type"), row.get("type") or "-")
        print("  %s  %s  %s" % (_event_time(row.get("ts")), label,
                               row.get("summary") or "-"))
        before, after = detail.get("url_before"), detail.get("url_after")
        if before and after and before != after:
            print("       %s → %s" % (before, after))
