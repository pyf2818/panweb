#!/usr/bin/env python3
"""构建单文件分发版 dist/panweb.pyz。

包含 Python 包、ui/index.html、Agent 技能与（可选）许可公钥；
运行期只需 Python 3.9+ 与 cloudflared，不需要 pip 依赖。

用法：
  python3 tools/build_zipapp.py [--out dist/panweb.pyz]
"""
import argparse
import pathlib
import shutil
import tempfile
import zipapp

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "dist" / "panweb.pyz"
# macOS 移动硬盘会写出 ._* AppleDouble 伴生文件，不能跟着进分发物
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "._*", ".DS_Store")


def build(out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="panweb-pyz-") as tmp:
        stage = pathlib.Path(tmp)
        shutil.copytree(ROOT / "src" / "panweb", stage / "panweb",
                        ignore=IGNORE)
        skill = ROOT / "skill"
        if skill.is_dir():
            shutil.copytree(skill, stage / "skill", ignore=IGNORE)
        ui = ROOT / "ui"
        if (ui / "index.html").is_file():
            (stage / "ui").mkdir()
            shutil.copy2(ui / "index.html", stage / "ui" / "index.html")
            if (ui / "favicon.png").is_file():
                shutil.copy2(ui / "favicon.png", stage / "ui" / "favicon.png")
        key = ROOT / "assets" / "license_public_key.pem"
        if key.is_file():
            (stage / "assets").mkdir()
            shutil.copy2(key, stage / "assets" / "license_public_key.pem")
        notices = ROOT / "THIRD_PARTY_NOTICES.md"
        if notices.is_file():
            shutil.copy2(notices, stage / "THIRD_PARTY_NOTICES.md")
        # xterm.js 等库内联进产物，但 MIT 声明要跟着分发物一起走
        for name in ("LICENSE.xterm", "LICENSE.addon-fit", "LICENSE.addon-canvas"):
            src_license = ui / "vendor" / name
            if src_license.is_file():
                shutil.copy2(src_license, stage / name)
        (stage / "__main__.py").write_text(
            "from panweb.cli import main\n\nmain()\n", encoding="utf-8")
        if out.exists():
            out.unlink()
        zipapp.create_archive(str(stage), str(out),
                              interpreter="/usr/bin/env python3",
                              compressed=True)
    return out


def main():
    parser = argparse.ArgumentParser(description="构建 panweb 单文件 zipapp")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out = build(pathlib.Path(args.out).resolve())
    print("已生成 %s（%.1f MB）" % (out, out.stat().st_size / 1048576))
    print("运行：python3 %s --version" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
