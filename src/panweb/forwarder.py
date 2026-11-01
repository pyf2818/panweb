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

    def stop(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except (OSError, AttributeError):
            pass


FORWARDERS = {}  # entry_id -> Forwarder（仅常驻进程内有意义）
CURRENT_POOL = None  # 仅控制台常驻进程设置


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
        FORWARDERS[entry_id] = item["forwarder"]
    CURRENT_POOL.prewarm()  # 立刻补充下一条
    return item
