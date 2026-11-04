"""控制台对话指令的保守解析：只产出结构化动作，绝不执行、不读写文件。"""
import shlex

from . import runtime

MAX_COMMAND_LEN = 200

_EXAMPLES = [
    "发布 3000",
    "发布 /path/to/dist",
    "发布 3000 pin=1234 有效期=1d 分享=开",
    "启动 /path/to/project",
    "停止 8080",
    "停止 当前",
    "检查 当前",
    "帮助",
]
_FORBIDDEN = set(";|&$><`")
_VERBS = {
    "发布": "publish", "publish": "publish",
    "启动": "run", "run": "run",
    "停止": "stop", "stop": "stop",
    "检查": "check", "check": "check",
    "帮助": "help", "help": "help",
}
_OPTION_KEYS = {
    "pin": "pin",
    "有效期": "expires", "expires": "expires",
    "分享": "share", "share": "share",
    "名称": "name", "name": "name",
}
_EXPIRES = {"1h": "1h", "1d": "1d", "7d": "7d",
            "永久": "", "forever": "", "none": "", "": ""}
_SHARE = {"开": True, "on": True, "true": True, "是": True,
          "关": False, "off": False, "false": False, "否": False}


def _error(message, hint, kind="invalid_command"):
    return {"ok": False,
            "error": {"type": kind, "message": message, "hint": hint},
            "examples": list(_EXAMPLES)}


def _folder_shaped(token):
    return token.startswith(("/", "~", ".")) or "/" in token


def _control_free(value):
    return all(ord(ch) >= 32 for ch in value)


def _parse_options(tokens):
    """返回 (options, 错误)。未知 key、空值、重复选项都按保守策略拒绝。"""
    opts = {"pin": None, "expires": None, "share": None, "name": None}
    seen = set()
    for token in tokens:
        if "=" not in token:
            return None, _error(
                "选项要写成 key=value，例如 pin=1234 或 有效期=1d",
                "试试：发布 3000 pin=1234 有效期=1d")
        key, _, value = token.partition("=")
        key = key.strip().lower() if key.isascii() else key.strip()
        name = _OPTION_KEYS.get(key)
        if not name:
            return None, _error(
                "不认识的选项「%s」" % key,
                "可用选项：pin、有效期、分享、名称；示例：发布 3000 pin=1234")
        if name in seen:
            return None, _error(
                "选项「%s」重复了" % key, "同一个选项只写一次")
        seen.add(name)
        value = value.strip()
        if name == "pin":
            if not (4 <= len(value) <= 32) or not _control_free(value):
                return None, _error(
                    "口令长度必须是 4–32 个可见字符",
                    "试试：发布 3000 pin=1234")
            opts["pin"] = value
        elif name == "expires":
            low = value.lower()
            if low not in _EXPIRES:
                return None, _error(
                    "有效期只支持 1h、1d、7d、永久",
                    "试试：发布 3000 有效期=1d")
            opts["expires"] = _EXPIRES[low]
        elif name == "share":
            if value.lower() not in _SHARE:
                return None, _error(
                    "分享只支持 开/关",
                    "试试：发布 3000 分享=开")
            opts["share"] = _SHARE[value.lower()]
        elif name == "name":
            if not value:
                return None, _error(
                    "名称不能为空", "试试：发布 3000 名称=演示站")
            if len(value) > 80:
                return None, _error(
                    "名称过长（≤80 字符）", "把名称缩短到 80 字以内")
            opts["name"] = value
    return opts, None


def _parse_target(verb, tokens):
    """端口 / 文件夹 / 停止目标 / 检查目标。"""
    word = tokens[0] if tokens else ""
    if verb in ("stop", "check"):
        if not word:
            return None, _error(
                "%s 需要一个目标" % ("停止" if verb == "stop" else "检查"),
                "试试：停止 8080、停止 当前、检查 当前")
        if word in ("全部", "all"):
            if verb == "check":
                return None, _error(
                    "检查只针对单个应用", "试试：检查 当前 或 检查 8080")
            return {"scope": "all"}, None
        if word in ("当前", "current"):
            return {"scope": "current"}, None
        if word.isdigit():
            port = int(word)
            if not 1 <= port <= 65535:
                return None, _error(
                    "端口必须在 1–65535 之间", "试试：停止 3000")
            return {"port": port}, None
        if not _control_free(word):
            return None, _error("目标含有不可见字符", "试试：停止 当前")
        return {"id": word}, None

    if not word:
        return {}, None
    if word.isdigit():
        port = int(word)
        if not 1 <= port <= 65535:
            return None, _error(
                "端口必须在 1–65535 之间", "试试：发布 3000")
        return {"port": port}, None
    if _folder_shaped(word):
        return {"folder": word}, None
    return None, _error(
        "「%s」既不是端口也不是文件夹路径" % word,
        "文件夹请写绝对路径或以 ./ 开头，例如：发布 /path/to/dist")


def parse_command(text, defaults=None):
    """解析一条控制台指令。成功只返回动作描述；失败附可复制的示例。"""
    defaults = defaults or {}
    raw = text if isinstance(text, str) else ""
    command = raw.strip()
    if not command:
        return _error("指令为空", "试试：发布 3000，或输入「帮助」")
    if len(command) > MAX_COMMAND_LEN:
        return _error(
            "指令过长（上限 %d 字符）" % MAX_COMMAND_LEN,
            "把指令缩短到一行，例如：发布 3000")
    if not _control_free(command) or any(ch in _FORBIDDEN for ch in command):
        return _error(
            "指令里不能出现分号、管道、重定向或反引号",
            "只写一条指令，例如：发布 3000 pin=1234")

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return _error(
            "引号没有闭合，无法解析",
            "检查引号，或改用不含空格的路径")
    if not tokens:
        return _error("指令为空", "试试：发布 3000")

    verb_token = tokens[0]
    verb = _VERBS.get(verb_token.lower() if verb_token.isascii()
                      else verb_token)
    if not verb:
        return _error(
            "只支持：发布、启动、停止、检查、帮助",
            "试试：发布 3000，或输入「帮助」查看示例")

    rest = tokens[1:]
    if verb == "help":
        if rest:
            return _error("帮助不接受参数", "直接输入：帮助")
        return {"ok": True, "verb": "help", "action": "help",
                "port": None, "folder": None, "id": None,
                "scope": None, "options": {}, "examples": list(_EXAMPLES)}

    option_tokens = [t for t in rest if _is_option(t)]
    target_tokens = [t for t in rest if not _is_option(t)]
    if verb in ("stop", "check") and option_tokens:
        return _error(
            "停止/检查不支持 pin、有效期等选项",
            "试试：停止 8080；改口令请用右侧详情抽屉")
    options, err = _parse_options(option_tokens)
    if err:
        return err
    target, err = _parse_target(verb, target_tokens)
    if err:
        return err
    if verb in ("stop", "check") and not target:
        return _error(
            "%s 需要一个目标" % ("停止" if verb == "stop" else "检查"),
            "试试：停止 8080、停止 当前、检查 当前")
    if verb in ("stop", "check") and len(target_tokens) > 1:
        return _error(
            "%s 一次只能指定一个目标" % ("停止" if verb == "stop" else "检查"),
            "试试：停止 8080，或停止 全部")

    port = target.get("port")
    folder = target.get("folder")
    entry_id = target.get("id")
    scope = target.get("scope")

    if verb == "publish":
        if len(target_tokens) > 1:
            return _error(
                "一次只能发布一个目标",
                "先发布一个，再执行下一条；例如：发布 3000")
        if port and runtime.RISKY_PORTS.get(port):
            return _error(
                "端口 %d 是%s，不能从指令直接公开" %
                (port, runtime.RISKY_PORTS[port]),
                "改用「高级发布」并勾选风险确认，或先给应用加访问口令",
                kind="risky_port")
        action = "pages" if folder else "publish"
    elif verb == "run":
        if len(target_tokens) > 1:
            return _error(
                "一次只能启动一个项目",
                "先启动一个，再执行下一条；例如：启动 /path/to/project")
        action = "run"
    else:
        action = verb

    share = options["share"]
    if share is None:
        share = bool(defaults.get("share", True))
    expires = options["expires"]
    if expires is None:
        expires = defaults.get("expires") or ""

    return {
        "ok": True,
        "verb": verb,
        "action": action,
        "port": port,
        "folder": folder,
        "id": entry_id,
        "scope": scope,
        "options": {"pin": options["pin"], "expires": expires,
                    "share": share, "name": options["name"]},
        "examples": list(_EXAMPLES),
    }


def _is_option(token):
    key = token.partition("=")[0]
    key = key.strip().lower() if key.isascii() else key.strip()
    return "=" in token and key in _OPTION_KEYS


__all__ = ["MAX_COMMAND_LEN", "parse_command"]
