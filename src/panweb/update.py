"""检查更新与取回升级包：买断含 1 年更新，所以先看许可窗口再谈版本。

数据源是 GitHub Releases（`panweb` 仓库的 latest）。下载只走 HTTPS，落地后本地算
SHA-256 打出来给主人自己比对 —— 真正的信任链是 Developer ID 签名与苹果公证
（见 ``codesign``），不是这个摘要。
"""
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import urllib.error
import urllib.request

from . import runtime
from .errors import PanwebError
from .licensing import license_status
from .store import log_activity

RELEASE_REPO = os.environ.get("PANWEB_RELEASE_REPO") or "pyf2818/panweb"
API_TIMEOUT = 12.0
USER_AGENT = "panweb/%s" % runtime.PANWEB_VERSION
VERSION_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def repo_slug():
    """仓库 slug 允许用环境变量覆盖（内测分发到别的仓库时不必改代码）。"""
    return (os.environ.get("PANWEB_RELEASE_REPO") or RELEASE_REPO).strip()


def parse_version(text):
    m = VERSION_RE.search(str(text or ""))
    if not m:
        return (0, 0, 0)
    return tuple(int(x or 0) for x in m.groups())


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_release():
    """拉 latest release；网络不通/没发布过都如实报错，不猜。"""
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo_slug()):
        raise PanwebError(2, "invalid_argument",
                          "发布仓库配置不合法：%s" % repo_slug())
    url = "https://api.github.com/repos/%s/releases/latest" % repo_slug()
    try:
        data = _get_json(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise PanwebError(4, "not_found",
                              "这个仓库还没有公开发布过版本",
                              "先在 GitHub 建一个 Release 并上传 dmg")
        raise PanwebError(4, "network", "查询更新失败：HTTP %s" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PanwebError(4, "network", "查询更新失败：%s" % e,
                          "本机到 GitHub 不通；也可以稍后再试")
    return data


def find_checksum_asset(release):
    """找到 Release 里的 SHA-256 清单；没有就返回 None。"""
    for item in release.get("assets") or []:
        name = str(item.get("name", ""))
        if name in ("SHA256SUMS", "sha256sums.txt", "checksums.txt"):
            return item
    return None


def pick_asset(release):
    """挑本机这个架构的 dmg，其次任意 dmg，最后 .pyz。"""
    checksums = find_checksum_asset(release)
    release_checksums = None
    if checksums:
        # 只是给后续 apply 用的内部字段，不影响 CLI 对外 JSON 的字段语义。
        release_checksums = checksums.get("browser_download_url")
    assets = release.get("assets") or []
    arch = platform.machine().lower()
    named = [a for a in assets if str(a.get("name", "")).endswith(".dmg")]
    want = [a for a in named if arch in str(a.get("name", "")).lower()]
    for item in (want or named):
        return {"name": item.get("name"), "url": item.get("browser_download_url"),
                "size": item.get("size"), "kind": "dmg",
                "checksums_url": release_checksums}
    for item in assets:
        if str(item.get("name", "")).endswith(".pyz"):
            return {"name": item.get("name"),
                    "url": item.get("browser_download_url"),
                    "size": item.get("size"), "kind": "pyz",
                    "checksums_url": release_checksums}
    return None


def core_update_status():
    """当前版本 / 最新版 / 许可更新窗口，三件事一次说清。"""
    lic = license_status(start_trial=False)
    out = {"current": runtime.PANWEB_VERSION, "repo": repo_slug(),
           "latest": None, "latest_notes": "", "newer": False,
           "asset": None, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "updates_active": bool(lic.get("updates_active")),
           "updates_until_text": lic.get("updates_until_text") or "",
           "license_mode": lic.get("mode")}
    release = latest_release()
    if not isinstance(release, dict):
        raise PanwebError(4, "network", "更新源返回了不认识的内容")
    tag = str(release.get("tag_name") or release.get("name") or "")
    out["latest"] = tag
    out["latest_notes"] = (release.get("body") or "")[:600]
    out["newer"] = parse_version(tag) > parse_version(runtime.PANWEB_VERSION)
    if out["newer"]:
        out["asset"] = pick_asset(release)
    return out


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def core_update_apply():
    """把升级包取到本机并打开：不覆盖正在运行的 App，那一步交给主人拖拽。"""
    status = core_update_status()
    if not status["newer"]:
        return dict(status, downloaded=None,
                    message="已经是最新版（%s）" % status["current"])
    if not status["updates_active"]:
        raise PanwebError(5, "license_expired",
                          "更新的 1 年窗口已过（至 %s）"
                          % (status["updates_until_text"] or "未知"),
                          "续费后同一密钥可继续升级；已装版本不受影响，可继续用")
    asset = status.get("asset")
    if not asset or not str(asset.get("url", "")).startswith("https://"):
        raise PanwebError(4, "not_found", "这个 Release 里没有可用的安装包",
                          "上传 dmg 后再试")
    out_dir = os.path.join(runtime.HOME_DIR, "update")
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, os.path.basename(asset["name"]))
    expected = None
    if asset.get("checksums_url"):
        expected = _expected_sha256(asset["checksums_url"], asset["name"])
    if not expected:
        raise PanwebError(4, "checksum",
                          "发布记录缺少 SHA256 校验清单，已拒绝取回升级包",
                          "请发布者上传 SHA256SUMS 后再试；没有摘要就不下载")
    _download(asset["url"], target)
    size = os.path.getsize(target)
    if asset.get("size") and abs(size - int(asset["size"])) > 1024:
        _discard(target)
        raise PanwebError(4, "checksum", "下载大小与发布记录不符，已丢弃")
    digest = sha256_of(target)
    if digest.lower() != expected:
        _discard(target)
        raise PanwebError(4, "checksum",
                          "升级包 SHA-256 与 SHA256SUMS 不符，已丢弃",
                          "不要运行这个文件；请重新下载或联系发布者")
    opened = _open_quietly(target, asset["kind"])
    log_activity("system", "已取回升级包 %s（%d MB，SHA-256 校验通过）"
                 % (asset["name"], max(1, size // 1048576)))
    return dict(status, downloaded=target, size=size, sha256=digest,
                verified=True, opened=opened,
                message="升级包已就绪：%s" % target)


def _discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _expected_sha256(url, name):
    if not str(url).startswith("https://"):
        raise PanwebError(4, "checksum", "SHA256SUMS 地址不是 HTTPS，已拒绝")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT) as resp:
            text = resp.read(1 << 16).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PanwebError(4, "network", "读取 SHA256SUMS 失败：%s" % e)
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1].lstrip("*") == name:
            digest = parts[0].lower()
            if re.fullmatch(r"[0-9a-f]{64}", digest):
                return digest
            break
    raise PanwebError(4, "checksum",
                      "SHA256SUMS 里没有 %s 的有效摘要，已拒绝" % name)


def _download(url, target):
    part = target + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, \
                open(part, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        # 断在半截时不能把 .part 留在本机：下次会被当成“正在下载”或占满目录
        _discard(part)
        raise PanwebError(4, "network", "下载失败：%s" % e)
    try:
        os.replace(part, target)
    except OSError as e:
        _discard(part)
        raise PanwebError(9, "write_failed", "升级包落盘失败：%s" % e)


def _open_quietly(path, kind):
    """macOS 上直接打开 dmg（挂载窗口弹出来）；其它平台只给路径。"""
    if kind != "dmg" or platform.system() != "Darwin":
        return False
    try:
        subprocess.Popen(["open", path], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
