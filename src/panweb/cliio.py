"""CLI 输出契约：成功 stdout JSON；失败 stderr JSON + 退出码。"""
import json
import sys

from .errors import PanwebError


def emit_ok(data, as_json):
    if as_json:
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
    return data


def emit_fail(err, as_json=False):
    if isinstance(err, PanwebError):
        if as_json:
            print(json.dumps(err.to_dict(), ensure_ascii=False), file=sys.stderr)
        else:
            print("❌ %s" % err.message, file=sys.stderr)
            if err.hint:
                print("   %s" % err.hint, file=sys.stderr)
        sys.exit(err.exit_code)
    if as_json:
        print(json.dumps({"ok": False, "error": {
            "type": "internal_error", "message": str(err), "exit_code": 1}},
            ensure_ascii=False), file=sys.stderr)
    else:
        print("❌ %s" % err, file=sys.stderr)
    sys.exit(1)
