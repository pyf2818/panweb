"""极简 MCP stdio 服务：initialize / tools/list / tools/call。"""
import json
import sys

from . import runtime
from .discovery import core_discover
from .entries import core_compat, core_list, core_stop
from .errors import PanwebError
from .healthcheck import core_check
from .publish import core_pages, core_publish, core_run
from .system import core_system

MCP_TOOLS = [
    {"name": "discover_apps",
     "description": "扫描本机正在运行、可发布的 HTTP 应用",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "publish_port",
     "description": ("把本机端口发布到公网。注意：任何拿到网址的人都能访问；"
                     "高危服务（Ollama/ComfyUI/数据库等）请先加 pin。"
                     "share=true 会生成带说明/有效期/统计的分享页（返回 share_url）"),
     "inputSchema": {"type": "object", "properties": {
         "port": {"type": "integer"}, "name": {"type": "string"},
         "pin": {"type": "string"},
         "expires": {"type": "string", "enum": ["1h", "1d", "7d"]},
         "share": {"type": "boolean"}}, "required": ["port"]}},
    {"name": "publish_pages",
     "description": ("把文件夹发布成公开只读网页（自动带分享页与统计）。"
                     "注意：文件夹内非隐藏文件都可被下载"),
     "inputSchema": {"type": "object", "properties": {
         "folder": {"type": "string"}, "name": {"type": "string"},
         "pin": {"type": "string"}, "expires": {"type": "string"}},
         "required": ["folder"]}},
    {"name": "run_project",
     "description": ("识别并自动启动项目（静态/Node）再发布；会执行项目内的 npm 脚本。"
                     "share=true 会生成分享页与访问统计"),
     "inputSchema": {"type": "object", "properties": {
         "folder": {"type": "string"}, "name": {"type": "string"},
         "share": {"type": "boolean"}}, "required": ["folder"]}},
    {"name": "stop",
     "description": "停止发布（target 为 id/名称/网址；传 all 停止全部）",
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string"}}, "required": ["target"]}},
    {"name": "list_apps",
     "description": "列出已发布的应用与网址",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "status",
     "description": "系统与数据全景",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "check_app",
     "description": ("按访客视角自检一个已发布应用：真打开公网网址、页面引用的资源，"
                     "并试一次 WebSocket 握手；发现应用在校验 Host 且有证据时会自动改 "
                     "host_mode。返回 verdict（ok/warn/blocked）与可执行建议"),
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string", "description": "id / 名称 / 网址"},
         "no_fix": {"type": "boolean", "description": "只观察不自动调整"}},
         "required": ["target"]}},
    {"name": "set_compat",
     "description": ("查看/设置某个发布前往上游的兼容项：host_mode（loopback 传本机地址、"
                     "tunnel 传访客看到的公网域名）与上游凭据（bearer/basic/header）。"
                     "凭据只存本机，返回值只有脱敏描述"),
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string"},
         "host_mode": {"type": "string", "enum": ["loopback", "tunnel"]},
         "auth_kind": {"type": "string", "enum": ["bearer", "basic", "header"]},
         "token": {"type": "string"}, "user": {"type": "string"},
         "password": {"type": "string"}, "header_name": {"type": "string"},
         "header_value": {"type": "string"},
         "clear_auth": {"type": "boolean"}}, "required": ["target"]}},
]


def _mcp_call(name, a):
    if name == "discover_apps":
        return {"candidates": core_discover()}
    if name == "publish_port":
        return core_publish(a.get("port"), a.get("name"),
                            pin=(a.get("pin") or "") or None,
                            expires=a.get("expires"),
                            share=bool(a.get("share")))
    if name == "publish_pages":
        return core_pages(a.get("folder"), a.get("name"),
                          pin=(a.get("pin") or "") or None,
                          expires=a.get("expires"))
    if name == "run_project":
        return core_run(a.get("folder"), a.get("name"),
                        share=bool(a.get("share")),
                        pin=(a.get("pin") or "") or None,
                        expires=a.get("expires"))
    if name == "stop":
        return {"stopped": core_stop(a.get("target") or "all")}
    if name == "list_apps":
        return {"apps": core_list()}
    if name == "status":
        return core_system()
    if name == "check_app":
        return core_check(a.get("target"), auto_fix=not a.get("no_fix"))
    if name == "set_compat":
        return core_compat(a.get("target"), host_mode=a.get("host_mode"),
                           auth_kind=a.get("auth_kind"),
                           token=a.get("token") or "", user=a.get("user") or "",
                           password=a.get("password") or "",
                           header_name=a.get("header_name") or "",
                           header_value=a.get("header_value") or "",
                           clear_auth=bool(a.get("clear_auth")))
    raise PanwebError(2, "unknown_tool", "未知工具：%s" % name)


def cmd_mcp(args):
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        method = req.get("method")
        rid = req.get("id")

        def send(res, rid=rid):
            sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
            sys.stdout.flush()

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "panweb",
                               "version": runtime.PANWEB_VERSION}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid,
                  "result": {"tools": MCP_TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            try:
                data = _mcp_call(params.get("name"),
                                 params.get("arguments") or {})
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text",
                                 "text": json.dumps(data, ensure_ascii=False)}]}})
            except PanwebError as e:
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text",
                                 "text": json.dumps(e.to_dict(),
                                                    ensure_ascii=False)}],
                    "isError": True}})
            except Exception as e:  # noqa: BLE001
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": str(e)}],
                    "isError": True}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
