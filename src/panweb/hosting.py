"""GitHub Pages 云端托管（关机也能访问）。"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

from . import runtime
from .convert import build_site
from .errors import PanwebError
from .licensing import require_publish_license
from .safety import check_pages_folder, safe_upload_rel_path
from .store import log_activity, save_json


def _gh(args_list, timeout=180, check=False):
    gh = shutil.which("gh")
    if not gh:
        raise PanwebError(3, "dependency_missing", "未找到 GitHub CLI（gh）",
                          "brew install gh 后运行 gh auth login")
    out = subprocess.run(["gh"] + args_list, capture_output=True, text=True,
                         timeout=timeout)
    if check and out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout or "")[:300])
    return out


def gh_logged_in():
    try:
        return _gh(["auth", "status"]).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def load_hosted():
    try:
        with open(runtime.HOSTED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_hosted(items):
    save_json(runtime.HOSTED_FILE, items)


def _ensure_nojekyll(stage):
    """GitHub Pages 默认跑 Jekyll，会丢掉 _next/_astro 等下划线目录。"""
    os.makedirs(stage, exist_ok=True)
    with open(os.path.join(stage, ".nojekyll"), "wb"):
        pass


def core_host(path=None, name=None, files=None):
    """部署静态站点到 GitHub Pages（关机可访问）。"""
    require_publish_license()
    if not gh_logged_in():
        raise PanwebError(2, "need_login", "GitHub 未登录",
                          "终端运行一次  gh auth login  即可激活云端托管")
    if not files and not path:
        raise PanwebError(2, "invalid_argument", "缺少要托管的文件或路径")
    name = (name or "").strip() or (
        os.path.basename(path or "site").rsplit(".", 1)[0] or "site")
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "site"
    if slug == "site":
        slug = "site-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    stage = os.path.join(runtime.HOSTING_DIR, slug)
    os.makedirs(runtime.HOSTING_DIR, exist_ok=True)
    if files:
        if os.path.isdir(stage):
            shutil.rmtree(stage)
        stage_real = os.path.realpath(stage)
        os.makedirs(stage_real, exist_ok=True)
        total_bytes = 0
        for item in files:
            rel = safe_upload_rel_path(item.get("path") or "index.html")
            dst = os.path.join(stage_real, rel)
            if os.path.commonpath([stage_real, os.path.realpath(dst)]) \
                    != stage_real:
                raise PanwebError(2, "invalid_argument", "文件路径越界：%s" % rel)
            data = base64.b64decode(item.get("content_b64") or "")
            total_bytes += len(data)
            if total_bytes > runtime.MAX_UPLOAD_BYTES:
                raise PanwebError(2, "too_large", "上传内容超过 %d MB" %
                                  (runtime.MAX_UPLOAD_BYTES // 1048576))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(data)
        file_count = len(files)
    else:
        src = os.path.abspath(os.path.expanduser(path or ""))
        if not os.path.exists(src):
            raise PanwebError(2, "invalid_argument", "路径不存在：%s" % src)
        if os.path.isdir(src):
            check_pages_folder(src)
        if os.path.realpath(src) == os.path.realpath(stage):
            file_count = sum(len(fs) for _, _, fs in os.walk(stage))
        else:
            file_count = build_site(src, stage, name)

    repo = ("panweb-" + slug)[:60]
    _ensure_nojekyll(stage)
    subprocess.run(["git", "init", "-b", "main"], cwd=stage,
                   capture_output=True)
    subprocess.run(["git", "add", "."], cwd=stage, capture_output=True)
    subprocess.run(["git", "-c", "user.name=panweb", "-c",
                    "user.email=panweb@local", "commit", "-m", "deploy",
                    "--allow-empty"], cwd=stage, capture_output=True)
    _gh(["auth", "setup-git"])
    owner = _gh(["api", "user", "--jq", ".login"], check=True).stdout.strip()
    repo_full = "%s/%s" % (owner, repo)
    exists = _gh(["api", "repos/%s" % repo_full,
                  "--jq", ".full_name"]).returncode == 0
    if exists:
        known = any(h.get("repo") == repo_full for h in load_hosted())
        if not known:
            desc = _gh(["api", "repos/%s" % repo_full,
                        "--jq", ".description"]).stdout.strip()
            if desc != "panweb hosted site":
                raise PanwebError(
                    9, "repo_conflict",
                    "GitHub 上已有同名仓库 %s，且不是 panweb 托管仓库" % repo_full,
                    "请换一个托管名称，避免覆盖你的其他仓库")
    else:
        out = _gh(["repo", "create", repo, "--public",
                   "--description", "panweb hosted site"])
        if out.returncode != 0:
            raise PanwebError(9, "host_failed", "创建仓库失败：" +
                              (out.stderr or out.stdout or "")[:300])
    remote = "https://github.com/%s/%s.git" % (owner, repo)
    subprocess.run(["git", "remote", "remove", "origin"], cwd=stage,
                   capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=stage,
                   capture_output=True)
    push = subprocess.run(["git", "push", "-f", "origin", "main"], cwd=stage,
                          capture_output=True, text=True, timeout=300)
    if push.returncode != 0:
        raise PanwebError(9, "host_failed", "推送失败：" + (push.stderr or "")[-300:])
    _gh(["api", "-X", "POST", "repos/%s/pages" % repo_full,
         "-f", "source[branch]=main", "-f", "source[path]=/"])
    url = "https://%s.github.io/%s/" % (owner, repo)
    items = [h for h in load_hosted() if h.get("name") != name]
    items.append({"name": name, "repo": repo_full, "url": url, "dir": stage,
                  "files": file_count,
                  "updated": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_hosted(items)
    log_activity("publish", "云端托管了「%s」（%d 个文件，关机可访问）"
                 % (name, file_count), url)
    return {"name": name, "repo": repo_full, "url": url,
            "files": file_count,
            "note": "首次部署 GitHub 构建1-2 分钟，稍候刷新即可访问"}


def core_host_redeploy(name):
    items = [h for h in load_hosted() if h["name"] == name]
    if not items:
        raise PanwebError(2, "not_found", "没有找到托管项：%s" % name)
    stage = items[0].get("dir")
    if not stage or not os.path.isdir(stage):
        raise PanwebError(2, "not_found", "本地站点目录丢失，请重新托管")
    return core_host(stage, name=name)
