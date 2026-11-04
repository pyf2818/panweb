"""各命令的实现：把 core 结果渲染成人类可读文本或 JSON。

这里只允许「取数据 + 打印」，业务逻辑都在 core 模块；
参数解析与调度在 ``panweb.cli``。
"""
import json
import os
import sys

from .cli_input import (compat_kind as _compat_kind,
                        read_auth_stdin as _read_auth_stdin,
                        resolve_pin as _resolve_cli_pin)
from .cli_render import (entry_for_json as _entry_for_json,
                         print_share_qr as _print_share_qr,
                         render_check, report_check as _report_check,
                         source_text as _source_text)
from .console import daemon_pid
from .diagnostics import core_report
from .discovery import core_discover, core_doctor
from .entries import core_compat, core_list, core_stop
from .errors import PanwebError
from .healthcheck import core_check
from .hosting import core_host
from .licensing import (activate_license, deactivate_license,
                        license_status)
from .publish import (core_pages, core_publish, core_run,
                      load_publish_defaults)
from .store import state_issue
from .system import core_pack
from .update import core_update_apply, core_update_status


def _progress(args):
    """人读模式才把步骤打到 stderr，JSON 输出保持干净。"""
    if getattr(args, "json", False):
        return None

    def show(message):
        print("→ %s" % message, file=sys.stderr, flush=True)

    return show


def _expires_arg(args):
    """只区分“显式指定”；未指定交给 core 按 配置 > 记忆 > 默认 解析。"""
    if getattr(args, "permanent", False):
        return ""
    return getattr(args, "expires", None)


def cmd_discover(args):
    if not args.json:
        print("正在扫描本机监听端口…")
    results = core_discover()
    if args.json:
        print(json.dumps({"ok": True, "data": {"candidates": results}},
                         ensure_ascii=False))
        return
    if not results:
        print("没有发现可发布的应用。先在本地把应用跑起来，再试一次。")
        return
    print("发现 %d 个候选应用：" % len(results))
    for r in results:
        mark = "（已发布：%s）" % r["published"] if r["published"] else ""
        risk = " ⚠️%s" % r["risky"] if r["risky"] else ""
        print("  端口 %-6s %-14s %s %s%s" % (r["port"], r["process"] or "-",
                                             r["title"], mark, risk))
    print("\n发布：panweb publish <端口>")


def cmd_publish(args):
    entry = core_publish(args.port, args.name, pin=_resolve_cli_pin(args),
                         expires=_expires_arg(args),
                         share=getattr(args, "share", None),
                         auto_check=not args.no_check,
                         progress=_progress(args),
                         title=getattr(args, "title", None),
                         desc=getattr(args, "desc", None),
                         folder=os.getcwd())
    if args.json:
        print(json.dumps({"ok": True, "data": _entry_for_json(entry)},
                         ensure_ascii=False))
        return
    print("✅ 已发布：%s" % entry["name"])
    print("   公网网址：%s" % entry["url"])
    if entry.get("share_url"):
        print("   分享页：%s" % entry["share_url"])
    _print_share_qr(args, entry)
    print("   本地来源：%s" % _source_text(entry))
    if entry["reachable"] and entry["dns_slow"]:
        print("   提示：本地 DNS 对新网址传播较慢，打不开时稍等几分钟再试"
              "（通道已就绪）。")
    elif not entry["reachable"]:
        print("   （公网通道已建立，应用第一次响应可能稍慢）")
    if entry.get("pinned"):
        print("   🔐 已设置访问口令：打开网址需先输入口令。")
    if entry.get("risky"):
        print("   ⚠️  高危：%s" % entry["risky"])
    print("   ⚠️  公开访问：任何拿到网址的人都能打开。"
          "随机子域名，未泄露即外人不知道。")
    print("   停止发布：panweb stop %s" % entry["id"])
    _report_check(entry)


def cmd_pages(args):
    entry = core_pages(args.folder, args.name, pin=_resolve_cli_pin(args),
                       expires=_expires_arg(args),
                       auto_check=not args.no_check,
                       progress=_progress(args),
                       title=getattr(args, "title", None),
                       desc=getattr(args, "desc", None))
    if args.json:
        print(json.dumps({"ok": True, "data": _entry_for_json(entry)},
                         ensure_ascii=False))
        return
    print("✅ 已发布只读网页：%s" % entry["name"])
    print("   公网网址：%s" % entry["url"])
    if entry.get("share_url"):
        print("   分享页：%s" % entry["share_url"])
    _print_share_qr(args, entry)
    print("   文件夹：%s（只读，原始文件不会被修改）" % _source_text(entry))
    if entry["reachable"] and entry["dns_slow"]:
        print("   提示：本地 DNS 对新网址传播较慢，打不开时稍等几分钟再试"
              "（通道已就绪）。")
    elif not entry["reachable"]:
        print("   （公网通道已建立，首次打开可能稍慢）")
    if entry.get("pinned"):
        print("   🔐 已设置访问口令：打开网址需先输入口令。")
    print("   ⚠️  公开访问：任何拿到网址的人都能打开。")
    print("   停止发布：panweb stop %s" % entry["id"])
    _report_check(entry)


def cmd_run(args):
    entry = core_run(args.folder, args.name,
                     share=getattr(args, "share", None),
                     auto_check=not args.no_check,
                     pin=_resolve_cli_pin(args),
                     expires=_expires_arg(args),
                     progress=_progress(args),
                     title=getattr(args, "title", None),
                     desc=getattr(args, "desc", None))
    if args.json:
        print(json.dumps({"ok": True, "data": _entry_for_json(entry)},
                         ensure_ascii=False))
        return
    print("🚀 已启动并发布：%s" % entry["name"])
    print("   公网网址：%s" % entry["url"])
    if entry.get("share_url"):
        print("   分享页：%s" % entry["share_url"])
    _print_share_qr(args, entry)
    print("   本地来源：%s（由 panweb 启动）" % _source_text(entry))
    if entry["reachable"] and entry["dns_slow"]:
        print("   提示：本地 DNS 对新网址传播较慢，打不开时稍等几分钟再试"
              "（通道已就绪）。")
    elif not entry["reachable"]:
        print("   （公网通道已建立，应用第一次响应可能稍慢）")
    if entry.get("risky"):
        print("   ⚠️  高危：%s" % entry["risky"])
    print("   ⚠️  公开访问：任何拿到网址的人都能打开。")
    print("   停止（同时结束项目进程）：panweb stop %s" % entry["id"])
    _report_check(entry)


def cmd_check(args):
    check = core_check(args.target, auto_fix=not args.no_fix)
    if args.json:
        print(json.dumps({"ok": True, "data": check}, ensure_ascii=False))
    else:
        print("访客视角自检：%s" % (check.get("url") or "-"))
        render_check(check, indent="")
    # 挡住时给非零码，脚本里可以 `panweb check x && ...`
    if check.get("verdict") == "blocked":
        sys.exit(1)


def cmd_compat(args):
    auth = {"token": args.bearer or "", "user": args.user or "",
            "password": args.password or "", "header_name": args.header or "",
            "header_value": args.value or ""}
    kind = _compat_kind(args)
    if args.auth_stdin:
        if kind or args.clear_auth:
            raise PanwebError(2, "invalid_argument",
                              "--auth-stdin 与命令行里的凭据 / --clear-auth 只能二选一",
                              "走标准输入时不要再把凭据写到命令行上")
        kind, auth = _read_auth_stdin()
    result = core_compat(args.target, host_mode=args.host_mode, auth_kind=kind,
                         clear_auth=args.clear_auth, **auth)
    if args.json:
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False))
        return
    print("「%s」的上游兼容：" % result["name"])
    print("   Host 模式：%s" % result["host_mode_label"])
    auth = result.get("auth")
    if auth:
        detail = auth.get("name") or auth.get("user") or ""
        print("   上游凭据：%s%s" % (auth["label"], "（%s）" % detail if detail else ""))
    else:
        print("   上游凭据：未设置")
    for change in result.get("auth_changes") or []:
        print("   🔧 %s" % change)
    if not result.get("auth_changes"):
        print("   （未修改；用 --host-mode / --bearer / --user+--password /"
              " --header+--value / --auth-stdin / --clear-auth）")
    print("   凭据只存在本机数据目录，控制台、命令行和分享页都只显示种类。"
          "不想让密钥进进程列表就用 --auth-stdin。")
    print("   改完验证一下：panweb check %s" % result["id"])


def cmd_list(args):
    entries = core_list()
    issue = state_issue()
    if args.json:
        print(json.dumps({"ok": True,
                          "data": {"apps": entries, "state_issue": issue}},
                         ensure_ascii=False))
        return
    if issue:
        print("⚠️ %s" % issue["message"])
        print("   之前的发布可能仍在运行；确认后可用 panweb stop all 清理。")
    if not entries:
        print("当前没有已发布的应用。发布：panweb publish <端口> "
              "或 panweb pages <文件夹>")
        return
    print("已发布 %d 个应用：" % len(entries))
    for e in entries:
        src = _source_text(e)
        print("  [%s] %s  %s" % (e["id"], e["name"], e["url"]))
        if e.get("share_url"):
            print("         分享页：%s" % e["share_url"])
        print("         来源：%s  发布于：%s" % (src, e["started"]))


def cmd_stop(args):
    stopped = core_stop(args.target, source="cli")
    if args.json:
        print(json.dumps({"ok": True, "data": {"stopped": stopped}},
                         ensure_ascii=False))
        return
    for s in stopped:
        print("✅ 已停止发布：%s（%s）" % (s["name"], s["url"]))


def cmd_status(args):
    doctor = core_doctor()
    entries = core_list()
    data = {"cloudflared": doctor["cloudflared"],
            "cloudflared_version": doctor["cloudflared_version"],
            "published_count": len(entries),
            "apps": [{"id": e["id"], "name": e["name"], "url": e["url"],
                      "share_url": e.get("share_url")} for e in entries]}
    if args.json:
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return
    print("cloudflared：%s（%s）" % (doctor["cloudflared"] or "未安装",
                                    doctor["cloudflared_version"] or "-"))
    if not doctor["cloudflared"]:
        print("提示：brew install cloudflared")
    daemon = daemon_pid()
    print("控制台：%s" % (
        "后台运行中（pid %d，http://127.0.0.1:7788）" % daemon
        if daemon else "未在后台运行（panweb console start）"))
    print("已发布应用：%d 个" % len(entries))
    for a in data["apps"]:
        print("  [%s] %s  %s" % (a["id"], a["name"], a["url"]))
        if a.get("share_url"):
            print("         分享页：%s" % a["share_url"])


def cmd_doctor(args):
    data = core_doctor(force=True)
    if args.json:
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return
    print("环境自检：")
    print("  cloudflared：%s %s" % (
        "✅" if data["cloudflared"]
        else "❌ 未安装（brew install cloudflared）",
        data["cloudflared_version"] or ""))
    py = data.get("python") or {}
    print("  python：%s %s" % (
        "✅" if py.get("ok") else "❌ 需要 3.9+（xcode-select --install）",
        py.get("version") or ""))
    tools = data.get("tools") or {}
    for name in ("curl", "lsof", "ps", "git", "npm", "gh", "swiftc"):
        state = "✅" if tools.get(name) else "— 未安装（可选）"
        print("  %-11s %s" % (name + "：", state))
    print("  状态目录：%s ✅" % data["state_dir"])
    cfg = data.get("project_config") or {}
    if cfg.get("error"):
        print("  .panweb.json：❌ %s" % cfg["error"]["message"])
        if cfg["error"].get("hint"):
            print("     → %s" % cfg["error"]["hint"])
    else:
        for warning in cfg.get("warnings") or []:
            print("  .panweb.json：⚠️ %s" % warning["message"])
        if cfg.get("exists") and not cfg.get("warnings"):
            print("  .panweb.json：✅ 已读取")
    print("  总体：%s" % ("可以发布 🎉" if data["ready"] else "还差一步"))


def cmd_license(args):
    if args.action == "status":
        status = license_status()
    elif args.action == "activate":
        key = (args.key or sys.stdin.read()).strip()
        if not key:
            raise PanwebError(2, "invalid_argument", "缺少许可密钥",
                              "用法：panweb license activate <密钥>")
        status = activate_license(key)
    else:
        result = deactivate_license()
        status = result["status"]
        if args.json:
            print(json.dumps({"ok": True, "data": result},
                             ensure_ascii=False))
            return
        print("✅ 已在本机解除许可绑定" if result["removed"]
              else "本机没有已激活的许可")
        print("   许可密钥仍可重新激活（受设备策略约束）。")
        return
    if args.json:
        print(json.dumps({"ok": True, "data": status}, ensure_ascii=False))
        return
    print("许可状态：%s" % status["message"])
    if status.get("license_id"):
        print("  许可编号：%s" % status["license_id"])
    if status.get("machine"):
        print("  本机指纹：%s" % status["machine"])
    if status.get("trial_ends_text"):
        print("  试用到期：%s" % status["trial_ends_text"])
    if status.get("updates_until_text"):
        print("  更新权益：%s" % status["updates_until_text"])
    if status.get("hint"):
        print("  %s" % status["hint"])
    if status.get("activation_required"):
        sys.exit(10)


def cmd_pack(args):
    data = core_pack(args.folder)
    if args.json:
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return
    print("✅ 离线包已导出：%s（%d KB）" % (data["zip"], data["size"] // 1024))
    print("   上传到任意免费静态托管（Cloudflare Pages / Netlify / Vercel），")
    print("   关机后别人也能打开 —— 云托管地址固定不变。")


def cmd_report(args):
    data = core_report(args.out)
    if args.json:
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return
    print("✅ 诊断包已导出：%s（%d KB）" % (data["zip"], data["size"] // 1024))
    print("   里面是：版本/环境、doctor、发布状态、最近动态与日志尾部。")
    print("   已排除：%s 与许可密钥本体 —— 发给卖家前可以自己再翻一遍。"
          % "、".join(data["excluded"]))


def _update_head(data):
    print("本机版本：panweb %s" % data["current"])
    if data.get("latest"):
        print("最新发布：%s%s" % (data["latest"],
                                 "（可升级 ⬆️）" if data.get("newer") else "（已是最新）"))
    lic = ("更新权益有效至 %s" % data["updates_until_text"]
           if data.get("updates_active") else "更新权益已到期")
    print("许可：%s（%s）" % (data.get("license_mode") or "-", lic))


def cmd_update(args):
    if args.action == "apply":
        data = core_update_apply()
    else:
        data = core_update_status()
    if args.json:
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return
    _update_head(data)
    if args.action == "apply":
        if data.get("downloaded"):
            print("✅ %s" % data["message"])
            print("   SHA-256：%s" % data["sha256"])
            print("   比对签名后把 panweb.app 拖进「应用程序」覆盖即可；"
                  "正在运行的版本不会被替换。")
            if not data.get("opened"):
                print("   手动打开：%s" % data["downloaded"])
        else:
            print("ℹ️ %s" % data["message"])
        return
    asset = data.get("asset")
    if not asset:
        return
    print("升级包：%s（%s，%.1f MB）"
          % (asset["name"], asset["kind"], (asset.get("size") or 0) / 1048576.0))
    print("   取回：panweb update apply")


def cmd_host(args):
    data = core_host(args.path, args.name)
    if args.json:
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return
    print("🌐 已托管到云端：%s（%d 个文件）" % (data["name"], data["files"]))
    print("   固定网址：%s" % data["url"])
    print("   ⚠️  %s" % data["note"])
    print("   电脑关机也能访问；仓库为公开，请勿上传敏感内容。")
