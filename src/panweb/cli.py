"""panweb 命令行入口：参数解析与调度。

命令的输入输出渲染在 ``panweb.cli_commands``；控制台、打包、内置代理只在被调用时
才导入，避免每次 CLI 启动都加载整条 UI/代理链。
"""
import argparse
import os
import sys

from . import runtime, upstream
from .cli_commands import (cmd_check, cmd_compat, cmd_discover, cmd_doctor,
                           cmd_host, cmd_list, cmd_license, cmd_pages,
                           cmd_publish, cmd_report, cmd_run, cmd_status,
                           cmd_stop, cmd_pack, cmd_update)
from .cliio import emit_fail
from .console import cmd_console
from .errors import PanwebError
from .mcp_server import cmd_mcp
from .store import ensure_private_dirs


def cmd_ui(args):
    from .ui_server import cmd_ui as _cmd_ui
    _cmd_ui(args)


def cmd_install_app(args):
    from .packaging import cmd_install_app as _install
    _install(args)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="panweb",
        description="免费、零服务器，把本机应用发布到公网（UUMit 复刻版）")
    parser.add_argument("--version", action="version",
                        version="panweb %s" % runtime.PANWEB_VERSION)
    parser.add_argument("--internal-proxy", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--listen-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--target-port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--serve-dir", help=argparse.SUPPRESS)
    parser.add_argument("--entry-id", help=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("discover", help="发现本机可发布的应用")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("publish", help="发布本机端口上正在运行的应用")
    p.add_argument("port", type=int)
    p.add_argument("--name", help="应用名称（默认 port-<端口>）")
    p.add_argument("--pin", help="设置访问口令（打开网址需先输入口令）")
    p.add_argument("--pin-stdin", action="store_true",
                   help="从 stdin 读取口令，避免出现在进程列表中")
    p.add_argument("--share", action="store_true",
                   help="生成分享页并统计访问（会经由内置代理）")
    p.add_argument("--expires", help="有效期：1h / 1d / 7d（默认永久）")
    p.add_argument("--no-check", action="store_true",
                   help="发布后不做访客视角自检（默认会自检并给出结论）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("pages", help="把文件夹发布成只读网页")
    p.add_argument("folder")
    p.add_argument("--name", help="页面名称（默认文件夹名）")
    p.add_argument("--pin", help="设置访问口令（打开网址需先输入口令）")
    p.add_argument("--pin-stdin", action="store_true",
                   help="从 stdin 读取口令，避免出现在进程列表中")
    p.add_argument("--expires", help="有效期：1h / 1d / 7d（默认永久）")
    p.add_argument("--no-check", action="store_true",
                   help="发布后不做访客视角自检")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_pages)

    p = sub.add_parser("run", help="识别并启动项目文件夹（静态/Node），然后发布")
    p.add_argument("folder")
    p.add_argument("--name", help="应用名称（默认文件夹名）")
    p.add_argument("--share", action="store_true",
                   help="生成分享页并统计访问（会经由内置代理）")
    p.add_argument("--no-check", action="store_true",
                   help="发布后不做访客视角自检")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("list", help="查看已发布的应用")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="按访客视角自检一个发布（能不能真打开）")
    p.add_argument("target", help="id / 名称 / 网址")
    p.add_argument("--no-fix", action="store_true",
                   help="只观察，不自动调整 Host 模式")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("compat", help="查看/设置某个发布的前往上游的兼容项")
    p.add_argument("target", help="id / 名称 / 网址")
    p.add_argument("--host-mode", choices=list(upstream.HOST_MODES),
                   help="传给上游的 Host：loopback=本机地址，tunnel=公网域名"
                        "（应用校验 Host 做 CSRF/重绑定防护时用）")
    p.add_argument("--bearer", metavar="TOKEN", help="替访客向上游注入 Bearer 令牌")
    p.add_argument("--user", help="上游用户名（配合 --password，Basic 认证）")
    p.add_argument("--password", help="上游密码")
    p.add_argument("--header", metavar="NAME", help="自定义上游请求头名")
    p.add_argument("--value", help="自定义上游请求头的值（配合 --header）")
    p.add_argument("--auth-stdin", action="store_true",
                   help="从 stdin 读取上游凭据（第一行 bearer/basic/header，"
                        "其后每行一个字段），避免出现在进程列表中")
    p.add_argument("--clear-auth", action="store_true", help="清除已设置的上游凭据")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_compat)

    p = sub.add_parser("stop", help="停止发布")
    p.add_argument("target", help="id / 名称 / 网址，或 all")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("status", help="当前状态")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor", help="环境自检")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("ui", help="前台启动本机控制台（浏览器仪表盘）")
    p.add_argument("--port", type=int, default=runtime.UI_DEFAULT_PORT)
    p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("console", help="控制台守护进程：后台独立运行")
    p.add_argument("action", choices=["start", "stop"])
    p.add_argument("--port", type=int, default=runtime.UI_DEFAULT_PORT)
    p.add_argument("--open", action="store_true", help="启动后打开浏览器")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_console)

    p = sub.add_parser("install-app",
                       help="构建 macOS 应用（内置 cloudflared，双击即用；需系统 python3）")
    p.add_argument("--out", help="输出路径（默认 ~/Applications/panweb.app）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_install_app)

    p = sub.add_parser("host",
                       help="托管静态文件/文件夹到 GitHub Pages（关机可访问）")
    p.add_argument("path")
    p.add_argument("--name", help="站点名称（默认取文件名）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_host)

    p = sub.add_parser("mcp", help="以 MCP stdio 服务运行（供 AI 客户端接入）")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("pack", help="把静态文件夹打包成 zip（可上传免费云托管）")
    p.add_argument("folder")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("report", help="导出脱敏诊断包（给卖家排查用）")
    p.add_argument("--out", help="输出目录（默认 ~/.panweb/reports）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("license", help="查看/激活/解除买断许可")
    p.add_argument("action", choices=["status", "activate", "deactivate"])
    p.add_argument("key", nargs="?", help="许可密钥（activate 时必填）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_license)

    p = sub.add_parser("update", help="检查更新 / 取回升级包（买断含 1 年更新）")
    p.add_argument("action", nargs="?", default="check",
                   choices=["check", "apply"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_update)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.internal_proxy:
        from .proxy import run_internal_proxy
        run_internal_proxy(args.listen_port, args.target_port,
                           args.serve_dir, args.entry_id)
        return
    if not args.command:
        parser.print_help()
        sys.exit(0)
    ensure_private_dirs()
    try:
        args.func(args)
    except PanwebError as e:
        emit_fail(e, as_json=bool(getattr(args, "json", False)))
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        sys.exit(130)
    except Exception as e:  # noqa: BLE001
        if os.environ.get("PANWEB_DEBUG"):
            raise
        emit_fail(e, as_json=bool(getattr(args, "json", False)))
