"""上次发布记忆：有效期、分享选项、最近端口/文件夹；口令不落盘。"""
from . import runtime
from .store import json_lock, load_meta, log_activity, save_meta

DEFAULTS_KEY = "publish_defaults"


def load_publish_defaults():
    """上次发布用的有效期/分享选项与最近端口、文件夹；口令不落盘。"""
    meta = load_meta()
    saved = meta.get(DEFAULTS_KEY)
    saved = saved if isinstance(saved, dict) else {}
    return {
        "expires": saved.get("expires") or "",
        "share": bool(saved.get("share", True)),
        "last_port": saved.get("last_port"),
        "last_folder": saved.get("last_folder"),
        "last_project": saved.get("last_project"),
    }


def remember_publish(**values):
    """记住选项供下次预填；失败只记日志，不能因为偏好写不进去而毁掉发布。"""
    try:
        with json_lock(runtime.META_FILE):
            meta = load_meta()
            saved = meta.get(DEFAULTS_KEY)
            saved = dict(saved) if isinstance(saved, dict) else {}
            for key, value in values.items():
                if value is not None:
                    saved[key] = value
            meta[DEFAULTS_KEY] = saved
            save_meta(meta)
    except OSError as e:
        log_activity("system", "保存发布偏好失败：%s" % e)
