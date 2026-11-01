"""本机目录浏览：控制台里的「选文件夹」既不该靠复制粘贴，也不该让浏览器编路径。

浏览器拿不到绝对路径（`<input type=file>` 只给相对名），所以选目录必须由本机
这一侧提供：只列目录、不列文件、不读内容、跳过隐藏项，也不列符号链接指向的目录
—— 发布那条链路本来就拒绝根外的符号链接，选择器里出现它只会误导。
控制台只监听回环地址并校验 Host/Origin，这份列表出不了这台电脑。
"""
import os

from . import safety
from .errors import PanwebError
from .store import load_state

MAX_ENTRIES = 400
QUICK_LABELS = (("", "主目录"), ("Desktop", "桌面"), ("Documents", "文稿"),
                ("Downloads", "下载"))


def _dedupe(items):
    seen, out = set(), []
    for item in items:
        path = item.get("path")
        if path and path not in seen:
            seen.add(path)
            out.append(item)
    return out[:8]


def quick_picks():
    """常用去处 + 最近发布过的文件夹（选过一次的下次多半还要选）。"""
    home = os.path.expanduser("~")
    out = [{"label": label, "path": os.path.join(home, rel) if rel else home}
           for rel, label in QUICK_LABELS]
    out = [p for p in out if os.path.isdir(p["path"])]
    for entry in load_state():
        target = str(entry.get("target") or "")
        if entry.get("kind") in ("pages", "run") and os.path.isdir(target):
            out.append({"label": entry.get("name") or "上次发布", "path": target})
    return _dedupe(out)


def publishable(folder):
    """这个目录能不能直接发布 —— 用发布那条真实规则回答，不在这里另写一套。"""
    try:
        safety.check_pages_folder(folder)
    except PanwebError as e:
        return {"ok": False, "reason": e.message}
    return {"ok": True, "reason": ""}


def core_folders(path=""):
    raw = (path or "").strip() or os.path.expanduser("~")
    if "\x00" in raw:
        raise PanwebError(2, "invalid_argument", "路径不合法")
    target = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(target):
        raise PanwebError(2, "not_found", "这个目录不存在或已移走",
                          "回到上一层重新选：%s" % target)
    parent = os.path.dirname(target)
    entries, truncated = [], 0
    try:
        names = sorted(os.listdir(target), key=str.lower)
    except OSError as e:
        raise PanwebError(9, "unreadable", "读不了这个目录：%s" % e.strerror,
                          "换一层，或在「系统与数据」里看数据目录")
    for name in names:
        if name.startswith("."):
            continue
        full = os.path.join(target, name)
        try:
            if os.path.islink(full) or not os.path.isdir(full):
                continue
        except OSError:
            continue
        if len(entries) >= MAX_ENTRIES:
            truncated += 1
            continue
        entries.append({"name": name, "path": full})
    return {"path": target,
            "parent": parent if parent and parent != target else None,
            "home": os.path.expanduser("~"),
            "label": os.path.basename(target) or target,
            "entries": entries, "truncated": truncated,
            "quick": quick_picks(), "publishable": publishable(target)}
