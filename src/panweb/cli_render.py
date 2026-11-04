"""CLI 共用的渲染：来源描述、自检结论、JSON 回执收尾、终端二维码。

只做“取数据 + 打印”，业务逻辑仍在 core 模块。
"""
from .healthcheck import await_check
from .models import entry_folder, entry_port

CHECK_ICONS = {"ok": "✅", "warn": "⚠️", "blocked": "❌"}


def source_text(entry):
    """按 kind 分发：pages 显示文件夹，端口条目显示本机源地址。"""
    if entry.get("kind") == "pages":
        return entry_folder(entry) or ""
    return "http://127.0.0.1:%s" % entry_port(entry)


def render_check(check, indent="   "):
    """先给一句结论，再列能照着做的信号。"""
    print("%s自检：%s %s" % (indent, CHECK_ICONS.get(check.get("verdict"), "·"),
                            check.get("summary") or "-"))
    for fix in check.get("fixes") or []:
        print("%s🔧 %s" % (indent, fix))
    for sig in check.get("signals") or []:
        if sig.get("severity") == "info":
            continue
        print("%s   · %s" % (indent, sig.get("label") or sig.get("code")))
        if sig.get("advice"):
            print("%s     → %s" % (indent, sig["advice"]))


def entry_for_json(entry):
    if entry.get("checking"):
        entry["check"] = await_check(entry["id"])
    entry.pop("checking", None)
    return entry


def report_check(entry):
    if not entry.get("checking"):
        return
    print("   正在按访客视角自检（首页、页面引用的资源、WebSocket）…")
    render_check(await_check(entry["id"]))


def print_share_qr(args, entry):
    """只在人读模式下打印终端二维码；JSON 模式保持干净。"""
    if not getattr(args, "qr", False):
        return
    target = entry.get("share_url") or entry.get("url")
    if not target:
        return
    from .qr import encode, render_terminal
    try:
        print(render_terminal(encode(target)))
    except ValueError:
        print("   （链接过长，未生成二维码；请直接使用上面的链接）")
