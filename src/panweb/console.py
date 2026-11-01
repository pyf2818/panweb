"""控制台守护进程管理：后台启动/停止。"""
import json
import os
import subprocess
import time

from . import runtime
from .browser import open_browser
from .cliio import emit_fail
from .errors import PanwebError
from .processes import (kill_process, pid_alive, pid_cmdline,
                        port_listening, probe_server)
from .store import ensure_private_dir


def _pid_is_panweb_ui(pid):
    cmd = pid_cmdline(pid)
    return bool(cmd) and "panweb" in cmd and " ui" in cmd


def daemon_pid():
    try:
        with open(runtime.DAEMON_PID, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if pid_alive(pid) and _pid_is_panweb_ui(pid):
        return pid
    try:
        os.remove(runtime.DAEMON_PID)
    except OSError:
        pass
    return None


def cmd_console(args):
    if args.action == "start":
        running = daemon_pid()
        if not running and port_listening(args.port):
            if probe_server(args.port).lower().startswith("panweb-ui"):
                url = "http://127.0.0.1:%d" % args.port
                if args.json:
                    print(json.dumps({"ok": True, "data": {
                        "url": url, "pid": None, "already": True}},
                        ensure_ascii=False))
                else:
                    print("✅ 控制台已在前台/其他方式运行：%s" % url)
                if args.open:
                    open_browser(url)
                return
            raise PanwebError(9, "port_in_use",
                              "端口 %d 已被其他程序占用" % args.port,
                              "换一个端口：panweb console start --port 7799")
        if running:
            url = "http://127.0.0.1:%d" % args.port
            if not args.json:
                print("✅ 控制台已在运行：%s（pid %d）" % (url, running))
            else:
                print(json.dumps({"ok": True, "data": {
                    "url": url, "pid": running, "already": True}},
                    ensure_ascii=False))
            if args.open:
                open_browser(url)
            return
        ensure_private_dir(runtime.HOME_DIR)
        logf = open(os.path.join(runtime.HOME_DIR, "ui-daemon.log"), "ab",
                    buffering=0)
        proc = subprocess.Popen(
            runtime.self_command("ui", "--no-open", "--port", str(args.port)),
            stdout=logf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env=runtime.self_env())
        logf.close()
        deadline = time.time() + 8
        while time.time() < deadline and not port_listening(args.port):
            time.sleep(0.2)
        if not port_listening(args.port):
            emit_fail(PanwebError(
                9, "daemon_failed", "控制台启动失败",
                "查看日志：%s" % os.path.join(runtime.HOME_DIR, "ui-daemon.log")),
                args.json)
        with open(runtime.DAEMON_PID, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))
        url = "http://127.0.0.1:%d" % args.port
        if args.open:
            open_browser(url)
        if args.json:
            print(json.dumps({"ok": True, "data": {"url": url,
                                                   "pid": proc.pid}},
                             ensure_ascii=False))
        else:
            print("✅ 控制台已在后台运行：%s（pid %d，关闭终端不影响）"
                  % (url, proc.pid))
            print("   停止：panweb console stop")
    else:
        pid = daemon_pid()
        if not pid:
            if args.json:
                print(json.dumps({"ok": True, "data": {
                    "stopped": True, "was": None}}, ensure_ascii=False))
            else:
                print("控制台当前没有在后台运行")
            return
        kill_process(pid, ("panweb",))
        deadline = time.time() + 5
        while pid_alive(pid) and time.time() < deadline:
            time.sleep(0.2)
        try:
            os.remove(runtime.DAEMON_PID)
        except OSError:
            pass
        if args.json:
            print(json.dumps({"ok": True, "data": {"stopped": True,
                                                   "was": pid}},
                             ensure_ascii=False))
        else:
            print("✅ 控制台已停止（pid %d）" % pid)
