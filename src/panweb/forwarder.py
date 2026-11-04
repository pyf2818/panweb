"""本地 TCP 转发器与预热隧道池（控制台内秒级发布）。"""
import json
import os
import socket
import socketserver
import threading
import time
import uuid

from . import runtime
from .processes import free_port, kill_process, pid_alive, stop_process
from .store import save_json
from .tunnel import start_tunnel


def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def duplex(a, b, join_timeout=2):
    """双向搬运 a↔b，并保证两侧 fd 都被归还。

    ``pipe`` 只负责半关闭：并发地关 fd 会让另一个线程踩到复用后的 fd，
    所以由本函数等两个方向都收束后再关。隧道每来一个访客就是一次调用，
    关不掉就是每个访客漏两个 fd。
    """
    t = threading.Thread(target=pipe, args=(b, a), daemon=True)
    t.start()
    try:
        pipe(a, b)
    finally:
        t.join(timeout=join_timeout)
        if not t.is_alive():
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass


class Forwarder:
    """预热隧道的固定入口 → 实际应用端口。"""

    def __init__(self, listen_port):
        self.listen_port = listen_port
        self.dest_port = None
        self.server = None
        self.thread = None
        self.control = None
        self._control_path = None

    def start(self):
        parent = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                if not parent.dest_port:
                    return
                try:
                    up = socket.create_connection(
                        ("127.0.0.1", parent.dest_port), timeout=10)
                except OSError:
                    return
                duplex(self.request, up)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", self.listen_port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def retarget(self, dest_port):
        self.dest_port = dest_port

    def enable_control(self, entry_id):
        """开一条 unix socket，让别的进程（CLI）也能关掉这个转发器。

        常驻控制台里的 ``FORWARDERS`` 只对本进程可见；``panweb stop`` 是另一个
        进程，没有这个入口就只能杀掉隧道却留着转发器占端口。
        """
        if not entry_id:
            return False
        os.makedirs(runtime.FORWARDERS_DIR, exist_ok=True)
        path = os.path.join(runtime.FORWARDERS_DIR, "%s.sock" % entry_id)
        _clear_stale_socket(path)
        self._close_control()
        parent = self

        class ControlHandler(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    cmd = self.request.recv(64).decode("utf-8", "replace").strip()
                    if cmd != "stop":
                        return
                    self.request.sendall(b"ok\n")
                except OSError:
                    return
                # stop() 会 shutdown 控制服务本身，不能在这个服务线程里直接跑。
                threading.Thread(target=parent.stop, daemon=True).start()

        class ControlServer(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

        try:
            self.control = ControlServer(path, ControlHandler)
        except OSError:
            self.control = None
            return False
        self._control_path = path
        try:
            os.chmod(path, 0o600)  # 只有当前用户能发停止指令
        except OSError:
            pass
        threading.Thread(target=self.control.serve_forever, daemon=True).start()
        return True

    def _close_control(self):
        ctrl, self.control = self.control, None
        path, self._control_path = self._control_path, None
        if ctrl:
            try:
                ctrl.shutdown()
                ctrl.server_close()
            except (OSError, AttributeError):
                pass
        if path:
            _unlink(path)

    def stop(self):
        self._close_control()
        try:
            self.server.shutdown()
            self.server.server_close()
        except (OSError, AttributeError):
            pass
        # 会话线程里 socket 可能已经关掉；base server 的关闭是幂等的。
        self.server = None


FORWARDERS = {}  # entry_id -> Forwarder（仅常驻进程内有意义）
CURRENT_POOL = None  # 仅控制台常驻进程设置


def _unlink(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _socket_path(entry_id):
    return os.path.join(runtime.FORWARDERS_DIR, "%s.sock" % entry_id)


def _clear_stale_socket(path):
    """绑定前清掉崩溃遗留的 socket 文件；还活着的绝不碰。"""
    if not os.path.exists(path):
        return
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        probe.connect(path)  # 能连上说明有进程在听，别动它
        return
    except OSError:
        _unlink(path)
    finally:
        probe.close()


def stop_remote(entry_id):
    """请持有该转发器的进程自行关闭；本地没有实例时使用。"""
    if not entry_id:
        return False
    path = _socket_path(entry_id)
    if not os.path.exists(path):
        return False
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        sock.connect(path)
        sock.sendall(b"stop\n")
        reply = sock.recv(16)
    except OSError:
        _unlink(path)  # 连不上就是陈旧 socket
        return False
    finally:
        sock.close()
    if reply.strip() != b"ok":
        return False
    _unlink(path)
    return True


def cleanup_forwarder_sockets():
    """控制台重启后回收上一进程遗留的控制 socket。"""
    try:
        names = os.listdir(runtime.FORWARDERS_DIR)
    except OSError:
        return
    for name in names:
        if name.endswith(".sock"):
            _clear_stale_socket(os.path.join(runtime.FORWARDERS_DIR, name))


class TunnelPool:
    """预热快速隧道：发布时直接取用，省去等待。"""

    def __init__(self, cf_bin, size=1):
        self.cf = cf_bin
        self.size = size
        self.items = []
        self.lock = threading.Lock()

    def _persist(self):
        save_json(runtime.POOL_FILE,
                  [{"pid": i["pid"], "port": i["port"], "url": i["url"]}
                   for i in self.items])

    def _spawn_one(self):
        listen_port = free_port()
        log_path = os.path.join(runtime.LOG_DIR,
                                "pool-%s.log" % uuid.uuid4().hex[:6])
        url, proc = start_tunnel(self.cf, listen_port, log_path)
        fw = Forwarder(listen_port)
        try:
            fw.start()
        except OSError:
            stop_process(proc, ("cloudflared",))
            raise
        item = {"port": listen_port, "url": url, "pid": proc.pid,
                "forwarder": fw}
        with self.lock:
            self.items.append(item)
            self._persist()
        return item

    def prewarm(self):
        def worker():
            while True:
                with self.lock:
                    missing = self.size - len(self.items)
                if missing <= 0:
                    return
                try:
                    self._spawn_one()
                except Exception:  # noqa: BLE001
                    time.sleep(30)
                    return

        threading.Thread(target=worker, daemon=True).start()

    def acquire(self):
        """取一条预热隧道。进程已经不在了就顺手回收，别把坏隧道发给发布。"""
        with self.lock:
            while self.items:
                item = self.items.pop(0)
                if pid_alive(item.get("pid")):
                    self._persist()
                    return item
                kill_process(item.get("pid"), ("cloudflared",))
                fw = item.get("forwarder")
                if fw:
                    fw.stop()
            self._persist()
        return None

    def shutdown(self):
        with self.lock:
            items, self.items = list(self.items), []
            self._persist()
        for item in items:
            kill_process(item.get("pid"), ("cloudflared",))
            fw = item.get("forwarder")
            if fw:
                fw.stop()


def cleanup_pool_state():
    """回收上一次控制台异常退出时遗留的预热隧道。"""
    try:
        with open(runtime.POOL_FILE, "r", encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        items = []
    for item in items if isinstance(items, list) else []:
        kill_process(item.get("pid"), ("cloudflared",))
    try:
        os.remove(runtime.POOL_FILE)
    except OSError:
        pass


def acquire_pooled_tunnel(port, entry_id=None):
    """控制台内优先用预热隧道（秒回）；返回 dict 或 None。"""
    if not CURRENT_POOL:
        return None
    item = CURRENT_POOL.acquire()
    if not item:
        return None
    item["forwarder"].retarget(port)
    if entry_id:
        item["forwarder"].enable_control(entry_id)
        FORWARDERS[entry_id] = item["forwarder"]
    CURRENT_POOL.prewarm()  # 立刻补充下一条
    return item
