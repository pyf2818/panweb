"""发布前的探测与守卫：挑选端口、拒绝内部端口、从日志嗅探端口。"""
import re

from . import runtime
from .errors import PanwebError
from .processes import internal_ports, is_panweb_service, port_listening

NODE_DEV_PORTS = [3000, 3001, 5173, 5174, 4321, 1420, 8000, 8080, 8888]
PORT_HINT_RE = re.compile(
    r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|::1?|\[[^\]]+\]):(\d{2,5})", re.I)


def emit(progress, message):
    if progress:
        progress(message)


def pick_port(progress=None):
    """没给端口时替主人挑一个：优先上次用的，其次唯一候选。"""
    from .discovery import core_discover
    from .publish_defaults import load_publish_defaults

    emit(progress, "自动探测本机正在运行的应用…")
    candidates = core_discover()
    if not candidates:
        raise PanwebError(
            2, "invalid_argument", "没有发现可发布的应用",
            "先在本地启动应用，再运行 panweb discover 查看端口；"
            "也可以直接 panweb publish <端口>")
    last = load_publish_defaults().get("last_port")
    if last and any(c["port"] == last for c in candidates):
        return int(last)
    fresh = [c for c in candidates if not c.get("published")] or candidates
    if len(fresh) == 1:
        return int(fresh[0]["port"])
    ports = "、".join(str(c["port"]) for c in fresh[:6])
    raise PanwebError(
        2, "ambiguous_port", "发现多个可发布端口：%s" % ports,
        "指定其中一个：panweb publish %d" % fresh[0]["port"])


def is_risky_port(port):
    return runtime.RISKY_PORTS.get(port)


def ensure_publishable_port(port):
    if port in internal_ports():
        raise PanwebError(2, "internal_port",
                          "端口 %d 是 panweb 的内部服务端口" % port,
                          "控制台/代理端口不能发布；请选择你的应用端口")
    if is_panweb_service(port):
        raise PanwebError(2, "internal_port",
                          "端口 %d 是 panweb 控制台或代理" % port,
                          "发布它会把本机管理权限暴露到公网；请选择你的应用端口")


def sniff_port(log_path):
    """从项目启动日志里嗅探监听端口（必须是当前确实在监听的）。"""
    try:
        with open(log_path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    for m in PORT_HINT_RE.finditer(text):
        try:
            p = int(m.group(1))
        except ValueError:
            continue
        if 1024 <= p <= 65535 and port_listening(p):
            return p
    return None
