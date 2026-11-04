"""项目类型识别：静态 / Node / Python / 未识别。"""
import json
import os

from .errors import PanwebError


def core_detect(folder):
    folder = os.path.abspath(os.path.expanduser(folder or ""))
    if not os.path.isdir(folder):
        raise PanwebError(2, "invalid_argument", "文件夹不存在：%s" % folder)
    pkg_path = os.path.join(folder, "package.json")
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            scripts = pkg.get("scripts") or {}
            script = ("dev" if "dev" in scripts
                      else ("start" if "start" in scripts else None))
            if script:
                return {"type": "node", "script": script, "folder": folder,
                        "scripts": sorted(scripts),
                        "detail": "识别到 Node 项目（npm run %s）" % script}
            return {"type": "node", "script": None, "folder": folder,
                    "scripts": sorted(scripts),
                    "detail": "Node 项目缺少 dev/start 脚本，无法自动启动"}
        except ValueError:
            pass
    if os.path.isfile(os.path.join(folder, "index.html")):
        return {"type": "static", "folder": folder,
                "detail": "识别到静态网页（直接发布）"}
    try:
        if any(f.endswith(".py") for f in os.listdir(folder)):
            return {"type": "python", "folder": folder,
                    "detail": "Python 项目：请手动启动后到「发布端口」选择"}
    except OSError:
        pass
    return {"type": "unknown", "folder": folder,
            "detail": "未识别的项目类型：可手动启动后到「发布端口」选择"}
