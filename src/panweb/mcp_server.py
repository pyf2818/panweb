"""极简 MCP stdio 服务：initialize / tools/list / tools/call。

发布类工具提交到 ``jobs`` 后立即返回 job id；Agent 用 ``get_job`` 轮询，
也可以传 ``wait=true`` 做有限等待（超时不算失败）。
"""
import json
import os
import sys
import time

from . import jobs, runtime
from .discovery import core_discover
from .entries import core_compat, core_list, core_stop
from .errors import PanwebError
from .healthcheck import core_check
from .publish import core_pages, core_publish, core_run
from .system import core_system

WAIT_TIMEOUT = 20.0
POLL_INTERVAL = 0.2
PUBLISH_TOOLS = {"publish_port": "publish", "publish_pages": "pages",
                 "run_project": "run"}

_EXPIRES = {"type": "string", "enum": ["1h", "1d", "7d", "permanent"],
            "description": ("有效期；省略时依次取 .panweb.json、上次发布记忆，"
                            "内置为 permanent（永久）")}
_PIN = {"type": "string",
        "description": ("访问口令（4-32 位）。只在本次调用内存中使用，"
                        "经现有口令校验，不落盘、不进回执")}
_NAME = {"type": "string", "maxLength": 120, "description": "应用名称"}
_TITLE = {"type": "string", "maxLength": 80, "description": "分享页标题"}
_DESC = {"type": "string", "maxLength": 300, "description": "分享页说明"}
_WAIT = {"type": "boolean", "default": False,
         "description": ("true 时最多等待 20 秒；完成返回最终回执，"
                         "超时返回 state=running 与 job_id（不是失败）")}

MCP_TOOLS = [
    {"name": "discover_apps",
     "description": "扫描本机正在运行、可发布的 HTTP 应用",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "publish_port",
     "description": ("把本机端口发布到公网，立即返回 job_id；用 get_job 轮询结果。"
                     "任何拿到网址的人都能访问；高危服务（Ollama/ComfyUI/数据库等）"
                     "请先加 pin。share 控制是否生成分享页与统计"),
     "inputSchema": {"type": "object", "properties": {
         "port": {"type": "integer", "minimum": 1, "maximum": 65535,
                  "description": "应用端口；省略时读取 .panweb.json 的 port 或自动探测"},
         "folder": {"type": "string",
                    "description": "项目目录（仅用于读取 .panweb.json），默认当前目录"},
         "name": _NAME, "pin": _PIN, "expires": _EXPIRES,
         "share": {"type": "boolean",
                   "description": "是否生成分享页与访问统计；省略时沿用上次发布/内置 true"},
         "title": _TITLE, "desc": _DESC, "wait": _WAIT}}},
    {"name": "publish_pages",
     "description": ("把文件夹发布成公开只读网页（自动带分享页与统计），立即返回 "
                     "job_id；用 get_job 轮询。注意：文件夹内非隐藏文件都可被下载"),
     "inputSchema": {"type": "object", "properties": {
         "folder": {"type": "string", "default": ".",
                    "description": "要发布的文件夹，默认当前目录"},
         "name": _NAME, "pin": _PIN, "expires": _EXPIRES,
         "title": _TITLE, "desc": _DESC, "wait": _WAIT}, "required": []}},
    {"name": "run_project",
     "description": ("识别并自动启动项目（静态/Node）再发布，立即返回 job_id；"
                     "用 get_job 轮询。Node 项目会执行项目内的 npm 脚本"),
     "inputSchema": {"type": "object", "properties": {
         "folder": {"type": "string", "default": ".",
                    "description": "项目目录；读取其中的 .panweb.json"},
         "script": {"type": "string", "maxLength": 100,
                    "description": "npm 脚本名；省略时读 .panweb.json 或自动识别 dev/start"},
         "name": _NAME, "pin": _PIN, "expires": _EXPIRES,
         "share": {"type": "boolean",
                   "description": "是否生成分享页与访问统计；省略时沿用上次发布/内置 true"},
         "title": _TITLE, "desc": _DESC, "wait": _WAIT}, "required": []}},
    {"name": "get_job",
     "description": ("查询异步发布任务；wait=true 时最多等 20 秒。"
                     "返回统一回执：ok/job_id/state/id/url/share_url/"
                     "expires_at/check/error"),
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string", "description": "发布工具返回的 job_id"},
         "wait": _WAIT}, "required": ["id"]}},
    {"name": "stop",
     "description": "停止发布（target 为 id/名称/网址；传 all 停止全部）",
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string", "description": "id / 名称 / 网址 / all"}},
         "required": ["target"]}},
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
         "no_fix": {"type": "boolean", "default": False,
                    "description": "只观察不自动调整"}},
         "required": ["target"]}},
    {"name": "set_compat",
     "description": ("查看/设置某个发布前往上游的兼容项：host_mode（loopback 传本机地址、"
                     "tunnel 传访客看到的公网域名）与上游凭据（bearer/basic/header）。"
                     "凭据只存本机，返回值只有脱敏描述"),
     "inputSchema": {"type": "object", "properties": {
         "target": {"type": "string", "description": "id / 名称 / 网址"},
         "host_mode": {"type": "string", "enum": ["loopback", "tunnel"]},
         "auth_kind": {"type": "string", "enum": ["bearer", "basic", "header"]},
         "token": {"type": "string"}, "user": {"type": "string"},
         "password": {"type": "string"}, "header_name": {"type": "string"},
         "header_value": {"type": "string"},
         "clear_auth": {"type": "boolean"}}, "required": ["target"]}},
]


def _receipt(job=None, error=None):
    """统一回执；运行中/成功/失败都是同一形状。"""
    data = {"ok": True, "job_id": None, "state": "running", "id": None,
            "url": None, "share_url": None, "expires_at": None, "check": None,
            "error": None, "steps": [], "step": None}
    if job:
        data.update(job_id=job["id"], steps=list(job.get("steps") or []),
                    step=job.get("step"))
        if job.get("done"):
            if job.get("ok"):
                entry = job.get("result") or {}
                data.update(state="succeeded", id=entry.get("id"),
                            url=entry.get("url"),
                            share_url=entry.get("share_url"),
                            expires_at=entry.get("expires_at"),
                            check=entry.get("check"))
            else:
                data.update(state="failed", ok=False,
                            error=_error_obj(job.get("error")))
    if error:
        data.update(ok=False, state="failed", error=error)
    return data


def _error_obj(error):
    if not isinstance(error, dict):
        error = {"type": "internal_error", "message": str(error)}
    return {"type": error.get("type") or "internal_error",
            "message": error.get("message") or "发布失败",
            "hint": error.get("hint") or "重试一次；若仍失败，查看 panweb 日志"}


def _error_receipt(err_type, message, hint, job_id=None):
    return _receipt(error={"type": err_type, "message": message,
                           "hint": hint}, job=(
        {"id": job_id, "steps": [], "step": None} if job_id else None))


def _await_job(job_id, timeout=None):
    deadline = time.time() + (WAIT_TIMEOUT if timeout is None else timeout)
    while True:
        job = jobs.get(job_id)
        if job is None or job.get("done"):
            return job
        if time.time() >= deadline:
            return job
        time.sleep(POLL_INTERVAL)


def _job_key(tool, arguments):
    folder = os.path.abspath(os.path.expanduser(
        str(arguments.get("folder") or ".")))
    if tool == "publish_port":
        return "%s|%s" % (folder, arguments.get("port") or "")
    return folder


def _invoke(tool, arguments, progress):
    folder = arguments.get("folder")
    if tool == "publish_port":
        return core_publish(
            arguments.get("port"), arguments.get("name"),
            pin=(arguments.get("pin") or "") or None,
            expires=arguments.get("expires"),
            share=arguments.get("share"),
            title=arguments.get("title"), desc=arguments.get("desc"),
            progress=progress, folder=folder or os.getcwd())
    if tool == "publish_pages":
        return core_pages(
            arguments.get("folder"), arguments.get("name"),
            pin=(arguments.get("pin") or "") or None,
            expires=arguments.get("expires"),
            title=arguments.get("title"), desc=arguments.get("desc"),
            progress=progress)
    return core_run(
        arguments.get("folder"), arguments.get("name"),
        script=arguments.get("script"),
        share=arguments.get("share"),
        pin=(arguments.get("pin") or "") or None,
        expires=arguments.get("expires"),
        title=arguments.get("title"), desc=arguments.get("desc"),
        progress=progress)


def _start_publish(tool, arguments):
    job_id = jobs.start(PUBLISH_TOOLS[tool],
                        lambda progress: _invoke(tool, arguments, progress),
                        key=_job_key(tool, arguments))
    job = (_await_job(job_id) if arguments.get("wait") else jobs.get(job_id))
    return _receipt(job=job)


def _mcp_call(name, a):
    if name in PUBLISH_TOOLS:
        return _start_publish(name, a)
    if name == "get_job":
        job_id = a.get("id")
        if not job_id:
            raise PanwebError(2, "invalid_argument", "缺少 job id",
                              "使用发布工具返回的 job_id 调用 get_job")
        job = (_await_job(job_id) if a.get("wait") else jobs.get(job_id))
        if job is None:
            return _error_receipt(
                "job_not_found", "找不到任务 %s" % job_id,
                "job 只保留在当前 panweb 进程内；重新提交发布即可拿到新 job", job_id)
        return _receipt(job=job)
    if name == "discover_apps":
        return {"candidates": core_discover()}
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
                    "content": [{"type": "text", "text": json.dumps(
                        _error_receipt(e.err_type, e.message, e.hint),
                        ensure_ascii=False)}],
                    "isError": True}})
            except Exception as e:  # noqa: BLE001
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": json.dumps(
                        _error_receipt("internal_error", str(e),
                                       "重试一次；若仍失败，查看 panweb 日志"),
                        ensure_ascii=False)}],
                    "isError": True}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
