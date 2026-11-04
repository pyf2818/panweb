"""构建 macOS App（内置包、UI、技能与 cloudflared；Python 用系统解释器 3.9+）。"""
import json
import os
import shutil
import subprocess
import time

from . import codesign, runtime
from .errors import PanwebError
from .processes import find_cloudflared
from .system import dir_size


def _copy_tree(src, dst):
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    # AppleDouble（._*）与 .DS_Store 是文件系统伴生垃圾，不能进 App
    shutil.copytree(src, dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                  "._*", ".DS_Store"))


def app_launcher_script():
    """App 双击启动器：不内置 Python，所以要先确认系统的 python3 够新。"""
    return """#!/bin/bash
# panweb 双击启动器：已运行则直接打开浏览器，否则后台拉起
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
export PANWEB_CLOUDFLARED="$DIR/cloudflared"
export PANWEB_RESOURCE_ROOT="$DIR"
export PANWEB_ENTRYPOINT="$DIR/panweb"
LOG="$HOME/.panweb/app.log"
mkdir -p "$HOME/.panweb"

if curl -s -o /dev/null --max-time 2 http://127.0.0.1:7788; then
  open "http://127.0.0.1:7788"
  exit 0
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  osascript -e 'display dialog "panweb 需要 macOS 命令行工具（python3）。\\n点击「安装」后按系统提示装好，再双击本应用。" with title "panweb" buttons {"好的"} default button 1' >/dev/null 2>&1
  xcode-select --install >/dev/null 2>&1
  exit 1
fi

if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
  osascript -e 'display dialog "panweb 需要 Python 3.9 或更高版本。\\n请安装新版 Python 后重新打开本应用；当前解释器版本过低。" with title "panweb" buttons {"好的"} default button 1' >/dev/null 2>&1
  exit 1
fi

nohup "$PY" "$DIR/panweb" ui --no-open --port 7788 >> "$LOG" 2>&1 &
for i in $(seq 1 40); do
  curl -s -o /dev/null --max-time 1 http://127.0.0.1:7788 && break
  sleep 0.5
done
open "http://127.0.0.1:7788"
"""


def cmd_install_app(args):
    if runtime.is_zipapp():
        raise PanwebError(9, "unsupported",
                          "zipapp 内不能构建 macOS App",
                          "从源码仓库运行 panweb install-app")
    app = args.out or os.path.expanduser("~/Applications/panweb.app")
    cf = find_cloudflared()
    if not cf:
        raise PanwebError(3, "dependency_missing",
                          "本机没有 cloudflared 可打包",
                          "先 brew install cloudflared，再重新构建")
    root = runtime.resource_root()
    pkg_dir = os.path.dirname(os.path.realpath(__file__))
    macos = os.path.join(app, "Contents", "MacOS")
    res = os.path.join(app, "Contents", "Resources")
    # 结束正在运行的本 App 实例（内置 cloudflared 被占用时无法覆盖）
    subprocess.run(["pkill", "-f",
                    os.path.join(app, "Contents", "Resources")],
                   capture_output=True)
    time.sleep(0.6)
    if os.path.isdir(app):
        subprocess.run(["chmod", "-R", "u+w", app], capture_output=True)
        shutil.rmtree(app)
    os.makedirs(macos, exist_ok=True)
    os.makedirs(res, exist_ok=True)
    for d in ("ui", "skill"):
        src_dir = os.path.join(root, d)
        if os.path.isdir(src_dir):
            _copy_tree(src_dir, os.path.join(res, d))
    notices = os.path.join(root, "THIRD_PARTY_NOTICES.md")
    if os.path.isfile(notices):
        shutil.copy2(notices, os.path.join(res, "THIRD_PARTY_NOTICES.md"))
    license_key = os.path.join(root, "assets", "license_public_key.pem")
    if os.path.isfile(license_key):
        os.makedirs(os.path.join(res, "assets"), exist_ok=True)
        shutil.copy2(license_key,
                     os.path.join(res, "assets", "license_public_key.pem"))
    third_party = os.path.join(root, "assets", "third_party")
    if os.path.isdir(third_party):
        _copy_tree(third_party, os.path.join(res, "third_party"))
    _copy_tree(pkg_dir, os.path.join(res, "src", "panweb"))
    launcher_py = os.path.join(root, "panweb")
    if not os.path.isfile(launcher_py):
        raise PanwebError(9, "build_failed", "找不到 panweb 启动器")
    shutil.copy2(launcher_py, os.path.join(res, "panweb"))
    shutil.copy2(cf, os.path.join(res, "cloudflared"))
    os.chmod(os.path.join(res, "cloudflared"), 0o755)
    launcher = os.path.join(macos, "panweb-launcher")
    with open(launcher, "w", encoding="utf-8") as f:
        f.write(app_launcher_script())
    os.chmod(launcher, 0o755)
    with open(os.path.join(app, "Contents", "Info.plist"), "w",
              encoding="utf-8") as f:
        f.write("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>panweb</string>
  <key>CFBundleDisplayName</key><string>panweb 发布台</string>
  <key>CFBundleIdentifier</key><string>com.panweb.console</string>
  <key>CFBundleExecutable</key><string>panweb-launcher</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>panweb</string>
  <key>CFBundleShortVersionString</key><string>%s</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>""" % runtime.PANWEB_VERSION)
    icns = os.path.join(root, "assets", "icon.icns")
    if os.path.isfile(icns):
        shutil.copy2(icns, os.path.join(res, "panweb.icns"))
    signed = codesign.sign(app)
    size = dir_size(app)
    if args.json:
        print(json.dumps({"ok": True, "data": {"app": app, "size": size,
                                               "signed": signed}},
                         ensure_ascii=False))
    else:
        print("✅ macOS 应用已构建：%s（%.0f MB）" % (app, size / 1048576))
        print("   双击即可使用 —— 无需 brew / 终端 / install.sh（cloudflared 已内置）")
        print("   不内置 Python 解释器：运行需系统 python3 ≥ 3.9，"
              "缺失时启动器会引导安装")
        print("   控制台已有实例运行时会直接打开浏览器（幂等）")
        print("   %s" % codesign.describe(signed))
