"""项目根目录的 ``.panweb.json``：发布默认值的项目级来源。

只读取当前目录，不向上递归；未知键一律拒绝，所以里面没有能合法存放
PIN/令牌的位置。文件内容不会写进事件流、日志或 MCP 回执。
"""
import json
import os

from .errors import PanwebError
from .publish_text import normalize_desc, normalize_title

CONFIG_NAME = ".panweb.json"
EXPIRES_VALUES = ("1h", "1d", "7d", "permanent")
PIN_POLICIES = ("none", "required")
KNOWN_FIELDS = ("port", "script", "name", "expires", "share", "title",
                "desc", "pin_policy")
NAME_MAX = 120
SCRIPT_MAX = 100
_SECRET_HINTS = ("pin", "token", "password", "secret", "key")


def config_path(folder=None):
    if not folder:
        return None
    folder = os.path.abspath(os.path.expanduser(str(folder)))
    return os.path.join(folder, CONFIG_NAME)


def _invalid(message, hint=None):
    return PanwebError(
        2, "invalid_config", message,
        hint or ("修正 %s 后重试；支持字段：%s"
                 % (CONFIG_NAME, "、".join(KNOWN_FIELDS))))


def _text_field(key, value, limit):
    if not isinstance(value, str):
        raise _invalid("%s 必须是字符串" % key)
    text = value.strip()
    if not text:
        raise _invalid("%s 不能为空" % key)
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in text):
        raise _invalid("%s 不能包含换行或控制字符" % key)
    if len(text) > limit:
        raise _invalid("%s 过长（最多 %d 个字符）" % (key, limit))
    return text


def _validated(data):
    values = {}
    unknown = sorted(set(data) - set(KNOWN_FIELDS))
    if unknown:
        if any(part in key.lower() for key in unknown for part in _SECRET_HINTS):
            raise _invalid(
                "口令/密钥不能写进 %s：%s" % (CONFIG_NAME, "、".join(unknown)),
                "口令只在发布时通过 --pin / --pin-stdin / MCP pin 传入，不落盘")
        raise _invalid("未知配置项：%s" % "、".join(unknown))

    if "port" in data:
        port = data["port"]
        if isinstance(port, bool) or not isinstance(port, int):
            raise _invalid("port 必须是整数")
        if not (1 <= port <= 65535):
            raise _invalid("port 必须在 1-65535 之间")
        values["port"] = port
    if "script" in data:
        values["script"] = _text_field("script", data["script"], SCRIPT_MAX)
    if "name" in data:
        values["name"] = _text_field("name", data["name"], NAME_MAX)
    if "expires" in data:
        expires = data["expires"]
        if not isinstance(expires, str) or expires not in EXPIRES_VALUES:
            raise _invalid("expires 只能是 %s" % " / ".join(EXPIRES_VALUES))
        values["expires"] = "" if expires == "permanent" else expires
    if "share" in data:
        if not isinstance(data["share"], bool):
            raise _invalid("share 必须是 true 或 false")
        values["share"] = data["share"]
    for key, normalize in (("title", normalize_title),
                           ("desc", normalize_desc)):
        if key in data:
            if not isinstance(data[key], str):
                raise _invalid("%s 必须是字符串" % key)
            try:
                values[key] = normalize(data[key])
            except PanwebError as e:
                raise _invalid("%s：%s" % (key, e.message), e.hint)
    if "pin_policy" in data:
        policy = data["pin_policy"]
        if not isinstance(policy, str) or policy not in PIN_POLICIES:
            raise _invalid("pin_policy 只能是 %s" % " / ".join(PIN_POLICIES))
        values["pin_policy"] = policy
    return values


def load_project_config(folder=None):
    """读取并校验配置；文件不存在时返回空配置（不是错误）。"""
    path = config_path(folder)
    empty = {"path": path, "exists": False, "values": {}, "warnings": [],
             "mode": None}
    if not path:
        return empty
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return empty
    except OSError as e:
        raise _invalid("无法读取 %s：%s" % (CONFIG_NAME, e.strerror or e))

    mode = oct(st.st_mode & 0o777)
    warnings = []
    if st.st_mode & 0o044:
        warnings.append({
            "type": "config_permission",
            "message": "%s 权限过宽（%s，同组/其他用户可读），建议 chmod 600"
                       % (CONFIG_NAME, mode),
            "path": path,
            "mode": mode,
        })
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise _invalid("无法读取 %s：%s" % (CONFIG_NAME, e.strerror or e))
    except ValueError:
        raise _invalid("%s 不是合法 JSON" % CONFIG_NAME)
    if not isinstance(data, dict):
        raise _invalid("%s 的顶层必须是 JSON 对象" % CONFIG_NAME)
    return {"path": path, "exists": True,
            "values": _validated(data), "warnings": warnings, "mode": mode}


def inspect_project_config(folder=None):
    """doctor 用：解析失败也返回结构，不让一个坏配置拖垮整份诊断。"""
    path = config_path(folder)
    try:
        loaded = load_project_config(folder)
        return {"path": loaded["path"], "exists": loaded["exists"],
                "warnings": loaded["warnings"], "error": None}
    except PanwebError as e:
        return {"path": path, "exists": True, "warnings": [],
                "error": {"type": e.err_type, "message": e.message,
                          "hint": e.hint}}
