"""文件夹发布边界与上传路径校验。"""
import os
import re

from . import runtime
from .errors import PanwebError


def check_pages_folder(folder):
    real = os.path.realpath(folder)
    home = os.path.realpath(os.path.expanduser("~"))
    denied = {os.path.realpath(p) for p in runtime.UNSAFE_PAGE_ROOTS}
    denied.add(home)
    denied.add(os.path.dirname(home))
    if real in denied:
        raise PanwebError(2, "unsafe_folder", "不允许直接发布该目录：%s" % real,
                          "请选择具体的项目或网页子文件夹")
    for raw in runtime.UNSAFE_PAGE_PREFIXES:
        prefix = os.path.realpath(os.path.expanduser(raw))
        try:
            inside = os.path.commonpath([real, prefix]) == prefix
        except ValueError:
            inside = False
        if inside:
            raise PanwebError(
                2, "unsafe_folder",
                "不允许发布敏感目录或其子目录：%s" % real,
                "私钥、云凭据和钥匙串不能发到公网，请换一个项目文件夹")


def safe_upload_rel_path(rel):
    """校验控制台上传的相对路径，拒绝穿越、绝对路径与非法字符。"""
    rel = (rel or "index.html").replace("\\", "/")
    if "\x00" in rel:
        raise PanwebError(2, "invalid_argument", "文件名包含非法字符")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise PanwebError(2, "invalid_argument", "文件路径不合法：%s" % rel)
    if re.match(r"^[a-zA-Z]:$", parts[0]):
        raise PanwebError(2, "invalid_argument", "文件路径不合法：%s" % rel)
    return "/".join(parts)
