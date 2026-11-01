"""只读静态文件解析：路径穿越、根外符号链接、dotfile 防护。"""
import os
import urllib.parse


def resolve_static_file(root, url_path):
    """解析静态文件请求，返回 (绝对路径, 状态码)。"""
    try:
        rel = urllib.parse.unquote(urllib.parse.urlparse(url_path).path)
    except ValueError:
        return None, 400
    if "\x00" in rel:
        return None, 400
    rel = rel.lstrip("/")
    root_real = os.path.realpath(root)
    fp = os.path.realpath(os.path.join(root_real, rel))
    try:
        if os.path.commonpath([root_real, fp]) != root_real:
            return None, 403
    except ValueError:
        return None, 403
    rel_parts = [p for p in os.path.relpath(fp, root_real).split(os.sep)
                 if p not in ("", ".")]
    if any(p.startswith(".") for p in rel_parts):
        return None, 404
    if os.path.isdir(fp):
        fp = os.path.realpath(os.path.join(fp, "index.html"))
        try:
            if os.path.commonpath([root_real, fp]) != root_real:
                return None, 403
        except ValueError:
            return None, 403
    if not os.path.isfile(fp):
        return None, 404
    return fp, 200
