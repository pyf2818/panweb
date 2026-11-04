"""发布选项优先级：显式参数 > .panweb.json > 上次记忆 > 内置默认值。"""
from .errors import PanwebError
from .project_config import load_project_config
from .publish_defaults import load_publish_defaults

_MISSING = object()


def _pick(out, sources, key, explicit, config_values, default, source):
    if explicit is not None:
        out[key], sources[key] = explicit, "argument"
    elif key in config_values:
        out[key], sources[key] = config_values[key], "config"
    elif default is not _MISSING:
        out[key], sources[key] = default, source
    else:
        out[key], sources[key] = None, "builtin"


def resolve_options(folder=None, port=None, script=None, name=None,
                    expires=None, share=None, title=None, desc=None,
                    pin=None):
    """把四个来源合成一次发布实际使用的值，并记录每个值的来源。"""
    loaded = load_project_config(folder)
    config = loaded["values"]
    defaults = load_publish_defaults()
    out, sources = {}, {}

    _pick(out, sources, "port", port, config, _MISSING, None)
    _pick(out, sources, "script", script, config, _MISSING, None)
    _pick(out, sources, "name", name, config, _MISSING, None)
    _pick(out, sources, "expires", expires, config,
          defaults.get("expires") or "", "defaults")
    _pick(out, sources, "share", share, config,
          bool(defaults.get("share", True)), "defaults")
    _pick(out, sources, "title", title, config, _MISSING, None)
    _pick(out, sources, "desc", desc, config, _MISSING, None)

    policy = config.get("pin_policy", "none")
    out["pin"] = pin
    out["pin_policy"] = policy
    out["config_path"] = loaded["path"]
    out["config_exists"] = loaded["exists"]
    out["config_warnings"] = list(loaded["warnings"])
    out["sources"] = sources
    if policy == "required" and not (str(pin or "")).strip():
        raise PanwebError(
            2, "pin_required", "%s 要求访问口令" % ".panweb.json",
            "发布时传入 pin（CLI --pin/--pin-stdin，MCP pin 参数）；"
            "口令不会写进 .panweb.json")
    return out


def notify_config_warnings(options, emit):
    for warning in options.get("config_warnings") or []:
        emit("⚠️ %s" % warning.get("message"))
