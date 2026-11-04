"""代理的只读静态服务：目录发布、Range 与缓存头。

拆出 proxy.py 是为了给公网入口的语义修复留出行数空间；行为与原实现一致。
"""
import mimetypes
import os
import re
import urllib.parse

from .static import resolve_static_file


def serve_static(handler, root):
    fp, status = resolve_static_file(root, handler.path)
    if status == 404 and handler.command in ("GET", "HEAD"):
        clean_path = urllib.parse.urlparse(handler.path).path
        last = os.path.basename(clean_path.rstrip("/"))
        if last and not last.startswith(".") \
                and not os.path.splitext(last)[1]:
            fp, status = resolve_static_file(root, "/index.html")
    if not fp:
        msg = "文件不存在" if status == 404 else "禁止访问"
        return handler._text_error(status, msg)
    try:
        size = os.path.getsize(fp)
    except OSError:
        return handler._text_error(404, "文件不存在")
    start, end, status_code = 0, max(0, size - 1), 200
    range_header = (handler.headers.get("Range") or "").strip()
    if range_header.startswith("bytes="):
        m = re.match(r"bytes=(\d*)-(\d*)$", range_header.split(",")[0].strip())
        if m:
            first, last = m.group(1), m.group(2)
            if first:
                start = int(first)
                end = int(last) if last else size - 1
            elif last:
                start = max(0, size - int(last))
                end = size - 1
            if start > end or start >= size or end < 0 or size == 0:
                handler.send_response(416)
                handler.send_header("Content-Range", "bytes */%d" % size)
                handler.send_header("Content-Length", "0")
                handler.end_headers()
                return
            status_code = 206
    length = max(0, end - start + 1)
    mime = mimetypes.guess_type(fp)[0] or "application/octet-stream"
    if mime.startswith("text/") or mime in ("application/javascript",
                                            "application/json"):
        mime += "; charset=utf-8"
    handler.send_response(status_code)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("X-Content-Type-Options", "nosniff")
    if status_code == 206:
        handler.send_header("Content-Range",
                            "bytes %d-%d/%d" % (start, end, size))
    handler.end_headers()
    if handler.command == "HEAD" or length == 0:
        return
    try:
        with open(fp, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                handler.wfile.write(chunk)
                remaining -= len(chunk)
    except OSError:
        pass
