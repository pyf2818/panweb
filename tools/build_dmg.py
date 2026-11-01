#!/usr/bin/env python3
"""构建 macOS 安装包 dist/panweb-<版本>-<架构>.dmg。

安装包里的 App 由 ``panweb install-app`` 生成（自包含：内置 Python 包、UI、
Agent 技能与 cloudflared），本脚本只负责把它装进一个可拖拽安装的磁盘映像。
只能在 macOS 上运行（依赖 hdiutil）。

用法：
  python3 tools/build_dmg.py [--out dist/panweb-1.5.0-arm64.dmg]
"""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from panweb import runtime  # noqa: E402  只要版本号，不加载业务链


def _run(argv, **kw):
    proc = subprocess.run(argv, capture_output=True, text=True, **kw)
    if proc.returncode:
        raise SystemExit("命令失败：%s\n%s" % (" ".join(argv),
                                              (proc.stderr or proc.stdout)[-800:]))
    return proc.stdout


def build_app(stage):
    """用项目自己的构建命令造 App，避免这里和 packaging.py 各写一套。"""
    app = os.path.join(stage, "panweb.app")
    out = _run([sys.executable, str(ROOT / "panweb"), "install-app",
                "--out", app, "--json"], cwd=str(ROOT))
    return json.loads(out.strip().splitlines()[-1])["data"]["app"]


def write_readme(stage):
    """拖拽安装的说明；不写「已签名/已公证」这类做不到的承诺。"""
    (pathlib.Path(stage) / "安装说明.txt").write_text(
        """panweb 发布台 — 安装

1. 把 panweb.app 拖到「应用程序」文件夹（或直接拖到桌面上用）。
2. 第一次打开：右键点图标 →「打开」→ 再点「打开」。
   （本 App 用 ad-hoc 签名、未走苹果公证，Gatekeeper 会先拦一次，属正常。）
3. 双击图标即启动本机控制台并打开浏览器 http://127.0.0.1:7788。

无需 brew、无需终端、无需额外下载：cloudflared 已内置。
状态与口令存在 ~/.panweb；命令行版仍在终端里用 ./panweb 或 install.sh。
""", encoding="utf-8")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target(out, arch):
    """``--out dist`` 落到 dist/panweb-<版本>-<架构>.dmg；给 .dmg 路径就照用。"""
    if out.suffix == ".dmg":
        out.parent.mkdir(parents=True, exist_ok=True)
        return out
    out.mkdir(parents=True, exist_ok=True)
    return out / ("panweb-%s-%s.dmg" % (runtime.PANWEB_VERSION, arch))


def build(out):
    if sys.platform != "darwin":
        raise SystemExit("构建 .dmg 需要在 macOS 上运行（依赖 hdiutil）")
    arch = os.uname().machine
    target = _target(out, arch)
    with tempfile.TemporaryDirectory(prefix="panweb-dmg-") as stage:
        build_app(stage)
        write_readme(stage)
        # 拖进去就装到 /Applications：Mac 安装盘的通用做法
        os.symlink("/Applications", os.path.join(stage, "Applications"))
        if target.exists():
            target.unlink()
        _run(["hdiutil", "create", "-volname", "panweb %s" % runtime.PANWEB_VERSION,
              "-srcfolder", stage, "-ov", "-format", "UDZO",
              "-imagekey", "zlib-level=9", "-quiet", str(target)])
    return target, arch


def main():
    parser = argparse.ArgumentParser(description="构建 panweb macOS 安装包")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()
    target, arch = build(pathlib.Path(args.out).resolve())
    print("已生成 %s（%.1f MB，%s）" % (target, target.stat().st_size / 1048576, arch))
    print("SHA-256：%s" % sha256(target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
