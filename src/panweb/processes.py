"""进程、端口与 cloudflared 探测；以及 panweb 自身端口的识别与回收。"""
import http.client
import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request

from . import runtime
from .store import load_domain, load_state


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pid_cmdline(pid):
    if not pid:
        return ""
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def kill_process(pid, expected=()):
    """仅在命令行匹配预期时终止进程，降低 pid 复用误杀风险。"""
    if not pid or not pid_alive(pid):
        return False
    cmd = pid_cmdline(pid)
    if expected and not any(x in cmd for x in expected):
        return False
    try:
        pgid = os.getpgid(pid)
    except OSError:
        pgid = None
    try:
        if pgid == pid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def stop_process(proc, expected=(), timeout=3):
    """终止并回收自己拉起的子进程；控制台是长驻服务，不能留僵尸。"""
    if proc is None:
        return
    kill_process(proc.pid, expected)
    deadline = time.time() + timeout
    while proc.poll() is None and time.time() < deadline:
        time.sleep(0.05)
    if proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass


def find_cloudflared():
    bundled = os.environ.get("PANWEB_CLOUDFLARED")
    if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
        return bundled
    for c in runtime.CLOUDFLARED_CANDIDATES:
        if os.path.isabs(c):
            path = c if os.path.isfile(c) and os.access(c, os.X_OK) else None
        else:
            path = shutil.which(c)
        if path:
            return path
    return None


def port_listening(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def probe_server(port, timeout=1.0):
    """读取 HTTP 服务的 Server 头（HEAD 请求，避免副作用）。"""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("HEAD", "/", headers={"User-Agent": "panweb-guard"})
        resp = conn.getresponse()
        server = resp.getheader("Server") or ""
        conn.close()
        return server
    except Exception:  # noqa: BLE001
        return ""


def probe_http(port):
    """返回 (title, server_header)，用于发现与自我保护。"""
    try:
        req = urllib.request.Request("http://127.0.0.1:%d/" % port,
                                     headers={"User-Agent": "panweb-discover"})
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            server = resp.headers.get("Server", "") or ""
            body = resp.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        server = (e.headers.get("Server", "") if e.headers else "") or ""
        return None, server
    except Exception:  # noqa: BLE001
        return None, ""
    m = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
    title = " ".join(m.group(1).split())[:80] if m else None
    return title, server


def internal_ports():
    """panweb 自己创建的代理/固定域名转发端口。"""
    ports = set()
    for e in load_state():
        for key in ("proxy_port", "local_port"):
            try:
                if e.get(key):
                    ports.add(int(e[key]))
            except (TypeError, ValueError):
                pass
    try:
        d = load_domain() or {}
        if d.get("local_port"):
            ports.add(int(d["local_port"]))
    except Exception:  # noqa: BLE001
        pass
    return ports


def is_panweb_service(port):
    return probe_server(port).lower().startswith("panweb-")


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def listening_ports():
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-w"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    ports = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 9 or ":" not in parts[8]:
            continue
        addr = parts[8].rsplit(":", 1)
        try:
            port = int(addr[1])
            pid = int(parts[1]) if parts[1].isdigit() else None
        except ValueError:
            continue
        ports.setdefault(port, pid)
    return sorted(ports.items())


def cleanup_orphan_proxies():
    """回收 ppid=1 的内置代理（控制台异常退出留下的孤儿）。"""
    state_ids = {e.get("id") for e in load_state()}
    try:
        out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="],
                             capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    signature = runtime.process_signature()
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)$", line)
        if not m:
            continue
        pid, ppid, cmd = int(m.group(1)), int(m.group(2)), m.group(3)
        if ppid != 1 or "--internal-proxy" not in cmd:
            continue
        if signature not in cmd and "panweb" not in cmd:
            continue
        em = re.search(r"--entry-id\s+(\S+)", cmd)
        if em and em.group(1) in state_ids:
            continue
        kill_process(pid, ("--internal-proxy",))


def wait_port(port, seconds=6.0):
    deadline = time.time() + seconds
    while time.time() < deadline and not port_listening(port):
        time.sleep(0.2)
    return port_listening(port)
