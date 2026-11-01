"""Markdown/Excel → HTML，以及云端托管站点整理。"""
import html as _html
import os
import re
import shutil
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from .errors import PanwebError


def safe_url(url):
    """只允许 http(s)/mailto/锚点/相对路径，阻断 javascript:、data: 等协议。"""
    url = (url or "").strip()
    if not url:
        return "#"
    if url.startswith(("#", "/", "./", "../")):
        return url
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", url):
        return url if re.match(r"^(https?:|mailto:)", url, re.I) else "#"
    return url


def convert_md(text, title="文档"):
    """轻量 Markdown → HTML（标题/列表/表格/代码/链接/加粗等常用语法）。"""
    def inline(t):
        t = _html.escape(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)",
                   lambda m: '<img src="%s" alt="%s">' %
                   (safe_url(m.group(2)), m.group(1)), t)
        t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                   lambda m: '<a href="%s">%s</a>' %
                   (safe_url(m.group(2)), m.group(1)), t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", t)
        return t

    lines = text.replace("\r\n", "\n").split("\n")
    out, i, para = [], 0, []

    def flush():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            flush()
            block = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            out.append("<pre><code>%s</code></pre>"
                       % _html.escape("\n".join(block)))
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if m:
            flush()
            lvl = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
            i += 1
            continue
        if re.match(r"^\s*([-*_])\s*\1\s*\1[\s\1]*$", ln):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if ln.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % inline(" ".join(quote)))
            continue
        if re.match(r"^\s*\|.*\|\s*$", ln) and i + 1 < len(lines) and \
                re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush()
            header = [c.strip() for c in ln.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                rows.append([c.strip() for c in
                             lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
                "".join("<th>%s</th>" % inline(c) for c in header),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c)
                                                for c in r) for r in rows)))
            continue
        if re.match(r"^\s*[-*+]\s+", ln):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*[-*+]\s+", lines[i]):
                items.append("<li>%s</li>" % inline(
                    re.sub(r"^\s*[-*+]\s+", "", lines[i])))
                i += 1
            out.append("<ul>%s</ul>" % "".join(items))
            continue
        if re.match(r"^\s*\d+\.\s+", ln):
            flush()
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append("<li>%s</li>" % inline(
                    re.sub(r"^\s*\d+\.\s+", "", lines[i])))
                i += 1
            out.append("<ol>%s</ol>" % "".join(items))
            continue
        if not ln.strip():
            flush()
            i += 1
            continue
        para.append(ln.strip())
        i += 1
    flush()
    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title><style>
body{font-family:-apple-system,'PingFang SC',sans-serif;max-width:820px;margin:40px auto;padding:0 24px;
color:#22312e;line-height:1.85;background:#f7f6f2}
h1,h2,h3{font-family:'Noto Serif SC','Songti SC',serif;line-height:1.4}
code{background:#ece9e2;border-radius:5px;padding:2px 6px;font-size:.92em}
pre{background:#1b211f;color:#a9c3ba;padding:16px;border-radius:10px;overflow-x:auto}
pre code{background:none;color:inherit;padding:0}
table{border-collapse:collapse;width:100%%;margin:14px 0;background:#fff}
th,td{border:1px solid #e0dcd2;padding:8px 12px;font-size:14px}
th{background:#e9f2ee}
blockquote{border-left:3px solid #b9975b;margin:12px 0;padding:6px 16px;background:#fff;color:#5c6b65}
img{max-width:100%%}a{color:#2a6558}
</style></head><body>%s</body></html>""" % (_html.escape(title), "\n".join(out))


def convert_xlsx(path, title="表格"):
    """xlsx → HTML 表格页（值提取，支持 sharedStrings / inlineStr）。"""
    z = zipfile.ZipFile(path)
    expanded = sum(i.file_size for i in z.infolist())
    if expanded > 200 * 1024 * 1024:
        raise PanwebError(2, "too_large", "Excel 解压后超过 200 MB，拒绝转换")
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(ns + "si"):
            shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
    parts = []
    sheets = sorted(n for n in z.namelist()
                    if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    for i, sn in enumerate(sheets):
        root = ET.fromstring(z.read(sn))
        rows = []
        for row in root.iter(ns + "row"):
            cells = []
            for c in row.iter(ns + "c"):
                t = c.get("t", "n")
                v = c.find(ns + "v")
                val = v.text if v is not None and v.text is not None else ""
                if t == "s" and val != "":
                    try:
                        val = shared[int(val)]
                    except (IndexError, ValueError):
                        pass
                elif t == "inlineStr":
                    is_el = c.find(ns + "is")
                    if is_el is not None:
                        val = "".join(x.text or "" for x in is_el.iter(ns + "t"))
                cells.append("<td>%s</td>" % _html.escape(str(val)))
            if cells:
                rows.append("<tr>%s</tr>" % "".join(cells))
        parts.append("<h2>%s</h2><table>%s</table>"
                     % (_html.escape("工作表 %d" % (i + 1)), "".join(rows)))
    body = "".join(parts) or "<p>空表格</p>"
    return """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title><style>
body{font-family:-apple-system,'PingFang SC',sans-serif;max-width:960px;margin:40px auto;
padding:0 24px;color:#22312e;background:#f7f6f2}
h2{font-family:'Noto Serif SC',serif}
table{border-collapse:collapse;width:100%%;background:#fff;font-size:13.5px}
th,td{border:1px solid #e0dcd2;padding:7px 11px}
tr:first-child td,th{background:#e9f2ee;font-weight:600}
</style></head><body><h1>%s</h1>%s</body></html>""" % (
        _html.escape(title), _html.escape(title), body)


def build_site(src, staging, name):
    """把文件/文件夹整理成静态站点目录（md/xlsx 自动转 HTML）。"""
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)
    file_count = 0
    if os.path.isfile(src):
        ext = os.path.splitext(src)[1].lower()
        base = os.path.basename(src)
        if ext == ".md":
            with open(src, encoding="utf-8", errors="replace") as f:
                text = f.read()
            with open(os.path.join(staging, "index.html"), "w",
                      encoding="utf-8") as f:
                f.write(convert_md(text, name or os.path.splitext(base)[0]))
            file_count += 1
        elif ext == ".xlsx":
            with open(os.path.join(staging, "index.html"), "w",
                      encoding="utf-8") as f:
                f.write(convert_xlsx(src, name or os.path.splitext(base)[0]))
            shutil.copy2(src, os.path.join(staging, base))
            file_count += 2
        else:
            dst_name = "index.html" if ext in (".html", ".htm") else base
            shutil.copy2(src, os.path.join(staging, dst_name))
            if dst_name != "index.html":
                page = ("""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title><style>body{font-family:-apple-system,'PingFang SC',sans-serif;max-width:820px;
margin:60px auto;padding:0 24px;color:#22312e;background:#f7f6f2;line-height:1.8}
a{color:#2a6558}</style></head><body><h1>%s</h1>
<p><a href="%s">打开 / 下载文件</a></p></body></html>""" %
                        (_html.escape(name or base), _html.escape(name or base),
                         urllib.parse.quote(base)))
                with open(os.path.join(staging, "index.html"), "w",
                          encoding="utf-8") as f:
                    f.write(page)
                file_count += 1
            file_count += 1
        return file_count
    excluded = {"node_modules", "__pycache__", "venv"}
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in excluded]
        rel = os.path.relpath(root, src)
        dst_root = staging if rel == "." else os.path.join(staging, rel)
        os.makedirs(dst_root, exist_ok=True)
        for name_f in files:
            if name_f.startswith("."):
                continue
            fp = os.path.join(root, name_f)
            if os.path.islink(fp):
                continue
            dst = os.path.join(dst_root, name_f)
            ext = os.path.splitext(name_f)[1].lower()
            if ext == ".md":
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        text = f.read()
                    with open(os.path.splitext(dst)[0] + ".html", "w",
                              encoding="utf-8") as f:
                        f.write(convert_md(text, os.path.splitext(name_f)[0]))
                except OSError:
                    continue
            else:
                shutil.copy2(fp, dst)
            file_count += 1
    if not os.path.isfile(os.path.join(staging, "index.html")):
        htmls = sorted(f for f in os.listdir(staging) if f.endswith(".html"))
        if htmls:
            shutil.copy2(os.path.join(staging, htmls[0]),
                         os.path.join(staging, "index.html"))
    return file_count
