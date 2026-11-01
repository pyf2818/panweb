"""一键安装 cloudflared（Homebrew）。"""
import os
import shutil
import subprocess

from . import runtime
from .errors import PanwebError
from .processes import find_cloudflared

INSTALLER = {"proc": None}


def core_install_cf():
    if find_cloudflared():
        return {"already": True}
    if INSTALLER["proc"] and INSTALLER["proc"].poll() is None:
        return {"running": True}
    brew = shutil.which("brew") or os.path.expanduser("~/homebrew/bin/brew")
    if not os.path.exists(brew):
        raise PanwebError(3, "dependency_missing", "未找到 Homebrew",
                          "先安装 Homebrew，或手动运行 brew install cloudflared")
    os.makedirs(runtime.LOG_DIR, exist_ok=True)
    logf = open(os.path.join(runtime.LOG_DIR, "install-cf.log"), "ab",
                buffering=0)
    INSTALLER["proc"] = subprocess.Popen(
        [brew, "install", "cloudflared"], stdout=logf,
        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    logf.close()
    return {"started": True}


def core_install_cf_status():
    proc = INSTALLER["proc"]
    ready = bool(find_cloudflared())
    if not proc:
        return {"running": False, "ready": ready}
    code = proc.poll()
    return {"running": code is None, "done": code is not None, "code": code,
            "ready": ready}
