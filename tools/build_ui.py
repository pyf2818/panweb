#!/usr/bin/env python3
"""把 ui/src 的 CSS/JS/HTML 模块组装成单文件 ui/index.html。

用法：
  python3 tools/build_ui.py          # 重新生成
  python3 tools/build_ui.py --check  # 只检查产物是否最新
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "ui" / "src"
MANIFEST = SRC / "manifest.json"
LIB = ROOT / "ui" / "vendor" / "qrcode.js"
OUT = ROOT / "ui" / "index.html"

STYLE_SLOT = "/*__PANWEB_STYLES__*/"
SCRIPT_SLOT = "/*__PANWEB_SCRIPTS__*/"
QR_SLOT = "/*__QR_LIBRARY__*/"
PAGES_SLOT = "<!--__PANWEB_PAGES__-->"
OVERLAYS_SLOT = "<!--__PANWEB_OVERLAYS__-->"
DOCTYPE = "<!DOCTYPE html>"
BANNER = ("<!-- 生成文件，请勿直接编辑：由 tools/build_ui.py 从 ui/src/ 组装；"
          "改样式或脚本请动 ui/src/，然后运行 python3 tools/build_ui.py -->")


def read(rel):
    return (SRC / rel).read_text(encoding="utf-8").rstrip("\n")


def build():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    index = (SRC / "index.html").read_text(encoding="utf-8")
    styles = "\n\n".join(read(rel) for rel in manifest["styles"])
    scripts = "\n\n".join(read(rel) for rel in manifest["scripts"])
    partials = {name: read(rel)
                for name, rel in (manifest.get("partials") or {}).items()}
    library = LIB.read_text(encoding="utf-8").rstrip("\n")

    for slot, value in ((STYLE_SLOT, styles), (SCRIPT_SLOT, scripts),
                        (QR_SLOT, library), (PAGES_SLOT, partials["pages"]),
                        (OVERLAYS_SLOT, partials["overlays"])):
        if slot not in index:
            raise SystemExit("ui/src/index.html 缺少占位符 %s" % slot)
        index = index.replace(slot, value, 1)

    leftovers = [s for s in (STYLE_SLOT, SCRIPT_SLOT, QR_SLOT,
                             PAGES_SLOT, OVERLAYS_SLOT) if s in index]
    if leftovers:
        raise SystemExit("组装后仍有未替换占位符：%s" % ", ".join(leftovers))
    if not index.startswith(DOCTYPE):
        raise SystemExit("ui/src/index.html 必须以 <!DOCTYPE html> 开头")
    return index.replace(DOCTYPE, DOCTYPE + "\n" + BANNER, 1)


def main():
    generated = build()
    if "--check" in sys.argv[1:]:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != generated:
            print("ui/index.html 与 ui/src 不一致，请运行 python3 tools/build_ui.py")
            return 1
        print("ui/index.html 已是最新")
        return 0
    OUT.write_text(generated, encoding="utf-8")
    print("已生成 ui/index.html（%d 字节）" % len(generated.encode("utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
