"""CLI 的敏感输入读取：口令与上游凭据走标准输入，避免进进程列表。"""
import sys

from .errors import PanwebError
from .pins import normalize_pin

AUTH_STDIN_FIELDS = {"bearer": ("token",), "basic": ("user", "password"),
                     "header": ("header_name", "header_value")}


def resolve_pin(args):
    pin = getattr(args, "pin", None)
    if getattr(args, "pin_stdin", False):
        if pin:
            raise PanwebError(2, "invalid_argument",
                              "--pin 与 --pin-stdin 只能二选一")
        pin = sys.stdin.readline().strip()
    return normalize_pin(pin)


def compat_kind(args):
    if getattr(args, "bearer", None):
        return "bearer"
    if getattr(args, "user", None) or getattr(args, "password", None):
        return "basic"
    if getattr(args, "header", None):
        return "header"
    return None


def read_auth_stdin():
    """从标准输入读上游凭据：第一行是种类，其后每行一个字段。

    命令行参数会出现在进程列表和 shell 历史里，令牌一旦进过 ``ps`` 就不算秘密了。
    """
    lines = [line.rstrip("\r\n") for line in sys.stdin if line.strip()]
    if not lines:
        raise PanwebError(2, "invalid_argument", "--auth-stdin 没有读到内容",
                          "第一行写 bearer / basic / header，其后每行填一个字段")
    kind = lines[0].strip().lower()
    fields = AUTH_STDIN_FIELDS.get(kind)
    if not fields:
        raise PanwebError(2, "invalid_argument",
                          "上游凭据种类应是 bearer / basic / header，读到「%s」" % lines[0])
    values = lines[1:1 + len(fields)]
    if len(values) < len(fields):
        raise PanwebError(2, "invalid_argument",
                          "%s 需要 %d 行凭据，只读到 %d 行" % (kind, len(fields), len(values)),
                          "bearer：令牌；basic：用户名、密码；header：头名称、值")
    return kind, dict(zip(fields, values))
