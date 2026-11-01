"""Cloudflare 快速隧道与公网可达性验证。"""
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

from . import runtime
from .errors import TunnelError


def read_log_tail(log_path, n=800):
    try:
        with open(log_path, "rb") as f:
            return f.read()[-n:].decode("utf-8", "replace")
    except OSError:
        return ""


def start_tunnel(cf_bin, local_port, log_path):
    """启动 cloudflared 快速隧道，返回 (公网网址, 进程)。失败抛 TunnelError。"""
    logf = open(log_path, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            [cf_bin, "tunnel", "--url", "http://127.0.0.1:%d" % local_port,
             "--no-autoupdate"],
            stdout=logf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError as e:
        logf.close()
        raise TunnelError("无法启动 cloudflared：%s" % e)

    url = None
    deadline = time.time() + 30
    buf = b""
    while time.time() < deadline:
        if proc.poll() is not None:
            logf.close()
            raise TunnelError("cloudflared 提前退出（码 %s）\n%s" % (
                proc.returncode, read_log_tail(log_path)))
        try:
            with open(log_path, "rb") as f:
                f.seek(len(buf))
                buf += f.read()
            m = runtime.TUNNEL_URL_RE.search(buf.decode("utf-8", "replace"))
            if m:
                url = m.group(0)
                break
        except OSError:
            pass
        time.sleep(0.4)
    logf.close()
    if not url:
        try:
            os.killpg(os.getpgid(proc.pid), 15)
        except OSError:
            pass
        tail = read_log_tail(log_path)
        if "429" in tail:
            raise TunnelError(
                "Cloudflare 限流（429）：短期创建的快速隧道太多，请稍后再试；"
                "或在「系统与数据」配置固定域名（不限流、网址永久）")
        raise TunnelError("等待隧道网址超时（30 秒）\n%s" % tail)
    return url, proc


def direct_check(url, timeout):
    """直接访问：任何 HTTP 响应（含 5xx）都算通。"""
    try:
        req = urllib.request.Request(url, method="GET")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:  # noqa: BLE001
        return False


def pinned_check(url, timeout):
    """边缘 IP 直连：用 trycloudflare.com 的边缘 IP + SNI 绕开本地 DNS。"""
    if not shutil.which("curl"):
        return False
    try:
        host = url.split("//", 1)[-1].split("/", 1)[0]
        edge = socket.getaddrinfo("trycloudflare.com", 443,
                                  socket.AF_INET)[0][4][0]
        out = subprocess.run(
            ["curl", "-s", "--resolve", "%s:443:%s" % (host, edge),
             "-o", "/dev/null", "-w", "%{http_code}", "--max-time",
             str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5,
        ).stdout.strip()
        return bool(out) and out != "000"
    except Exception:  # noqa: BLE001
        return False


def verify_public(url, timeout=15, initial_wait=3):
    """返回 (reachable, dns_slow)。预热隧道可传 initial_wait=0。"""
    if initial_wait:
        time.sleep(initial_wait)
    if pinned_check(url, timeout):
        return True, not direct_check(url, 8)
    for _ in range(3):
        if direct_check(url, timeout):
            return True, False
        time.sleep(3)
    return False, False


def pinned_status(url, timeout):
    """边缘 IP 直连，返回 HTTP 状态码（0=无响应）。"""
    if not shutil.which("curl"):
        return 0
    try:
        host = url.split("//", 1)[-1].split("/", 1)[0]
        edge = socket.getaddrinfo("trycloudflare.com", 443,
                                  socket.AF_INET)[0][4][0]
        out = subprocess.run(
            ["curl", "-s", "--resolve", "%s:443:%s" % (host, edge),
             "-o", "/dev/null", "-w", "%{http_code}", "--max-time",
             str(timeout), url],
            capture_output=True, text=True, timeout=timeout + 5,
        ).stdout.strip()
        return int(out) if out and out.isdigit() else 0
    except Exception:  # noqa: BLE001
        return 0


def public_status(url, timeout=6):
    """优先走边缘 IP 校验；没有 curl 时退回普通 HTTP 请求。"""
    if shutil.which("curl"):
        return pinned_status(url, timeout)
    try:
        req = urllib.request.Request(url, method="GET")
        urllib.request.urlopen(req, timeout=timeout)
        return 200
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0
