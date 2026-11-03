"""把本机 Agent 的**真终端**（伪终端 PTY）挂进控制台：网页里看到的就是它自己的画面。

界面进来的是"选哪个 Agent"和键盘字节，不是命令：二进制只从白名单解析，argv 固定
拼装，绝不经过 shell。子进程跑在 PTY 从端上，画面字节原样用 SSE 推给 xterm.js，
键盘输入写回主端，窗口尺寸用 TIOCSWINSZ 告诉它——所以彩色、进度条、快捷键、
分页器这些交互式的东西都能照原样用。
"""
import base64
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import threading
import time
import uuid

from . import runtime
from .agents import terminal_for
from .errors import PanwebError
from .processes import stop_process
from .store import log_activity

MAX_TERMS = 4
KEEP_DEAD = 1              # 退出后的终端留一个，画面还能翻回去看
MAX_BUFFER = 300000        # 每个终端最多留 300KB 画面字节，超了丢最早的
MAX_INPUT = 32768          # 一次键盘/粘贴写入的上限
READ_SIZE = 32768
FRAME_BYTES = 24576        # 每帧 SSE 的原始字节数
HEARTBEAT = 15.0
WRITE_TIMEOUT = 5.0
MIN_COLS, MAX_COLS = 20, 400
MIN_ROWS, MAX_ROWS = 6, 200
PUMP_TICK = 1.0            # 读线程的呼吸：关掉会话后最多 1 秒内自己收工

_sessions = {}
_order = []
_guard = threading.Lock()
_stopping = False          # 控制台正在退出：别再开新的 Agent，否则会留成孤儿


def _validate_cwd(cwd):
    path = os.path.expanduser((cwd or "").strip())
    if not path:
        path = os.path.expanduser("~")
    if not os.path.isdir(path):
        raise PanwebError(2, "invalid_argument",
                          "工作目录不存在：%s" % path,
                          "填一个本机真实存在的目录，Agent 会在那里干活")
    return os.path.realpath(path)


def _size(cols, rows):
    try:
        cols, rows = int(cols or 0), int(rows or 0)
    except (TypeError, ValueError):
        cols = rows = 0
    if cols <= 0:
        cols = 100
    if rows <= 0:
        rows = 30
    return (min(MAX_COLS, max(MIN_COLS, cols)), min(MAX_ROWS, max(MIN_ROWS, rows)))


def _child_env(workdir, binary, sid):
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["PWD"] = workdir
    env["PANWEB_TERM"] = sid           # 让 Agent 知道自己在 panweb 的终端里
    # 追加而不是前置：从启动台打开的 App 里 PATH 很短，得让 ~/.local/bin 这些兜底；
    # 前置会让谁在 ~/bin 里放个同名二进制就劫持了 Agent 自己调用的命令
    extra = [d for d in [os.path.dirname(binary)] + runtime.USER_BIN_DIRS
             if d and os.path.isdir(d)]
    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + extra)
    return env


def _summary(session):
    with session["cond"]:
        return {"id": session["id"], "agent": session["agent"],
                "name": session["name"], "cwd": session["cwd"],
                "alive": session["alive"], "exit_code": session["exit_code"],
                "cols": session["cols"], "rows": session["rows"],
                "created": session["created"], "bytes": session["end"],
                "start": session["start"]}


def _prune_locked():
    """开新终端前收掉多余的已退出会话；还活着的绝不偷偷杀，满了就明说。"""
    dead = [sid for sid in _order if sid in _sessions
            and not _sessions[sid]["alive"]]
    for sid in dead[:-KEEP_DEAD] if len(dead) > KEEP_DEAD else []:
        _sessions.pop(sid, None)
        _order.remove(sid)


def _new_id():
    while True:                     # 6 位十六进制会撞：撞了别把活着的会话顶掉
        sid = uuid.uuid4().hex[:6]
        if sid not in _sessions:
            return sid


def _discard(session, slave_fd=None):
    """开终端开到一半失败：fd 与子进程都不许留下。注册表归调用方管——
    这里再拿一次 _guard 就是自锁（_guard 不可重入，open 的失败路径正持着它）。"""
    if slave_fd is not None:
        try:
            os.close(slave_fd)
        except OSError:
            pass
    proc = session.get("proc")
    if proc is not None:
        stop_process(proc, expected=(session["bin"],))
    with session["io"]:
        if session["master"] is not None:
            try:
                os.close(session["master"])
            except OSError:
                pass
            session["master"] = None


def core_terminal_open(agent, cwd="", cols=0, rows=0):
    """在 PTY 里拉起一个交互式 Agent 终端。"""
    item, binary = terminal_for(agent)
    workdir = _validate_cwd(cwd)
    cols, rows = _size(cols, rows)
    with _guard:
        if _stopping:
            raise PanwebError(3, "busy", "控制台正在退出，别开新终端")
        _prune_locked()
        if len(_sessions) >= MAX_TERMS:
            raise PanwebError(3, "busy", "已经有 %d 个终端在跑" % len(_sessions),
                              "先关掉一个再开新的")
        master, slave = pty.openpty()
        sid = _new_id()
        session = {"id": sid, "agent": agent, "name": item["name"],
                   "bin": os.path.basename(binary), "cwd": workdir,
                   "proc": None, "pid": None, "master": master,
                   "cols": cols, "rows": rows, "alive": True,
                   "exit_code": None, "buf": b"", "start": 0, "end": 0,
                   "created": time.time(), "closed": False,
                   "cond": threading.Condition(), "io": threading.Lock()}
        try:
            fcntl.ioctl(master, termios.TIOCSWINSZ,
                        struct.pack("HHHH", rows, cols, 0, 0))
            # 主端非阻塞：卡死的子进程不能把控制台的请求线程钉在写调用上
            os.set_blocking(master, False)
            session["proc"] = subprocess.Popen(
                [binary] + list(item["argv"]), cwd=workdir,
                stdin=slave, stdout=slave, stderr=slave,
                env=_child_env(workdir, binary, sid),
                close_fds=True, start_new_session=True)
            session["pid"] = session["proc"].pid
            os.close(slave)
            slave = None
        except (OSError, ValueError) as e:
            _discard(session, slave)
            raise PanwebError(9, "launch_failed",
                              "%s 启动失败：%s" % (item["name"], e))
        _sessions[sid] = session
        _order.append(sid)
    try:
        threading.Thread(target=_pump, args=(session,), daemon=True).start()
    except RuntimeError as e:         # 线程耗尽：不能留个没人读的终端在跑
        _discard(session)
        with _guard:
            _sessions.pop(sid, None)
            if sid in _order:
                _order.remove(sid)
        raise PanwebError(9, "launch_failed", "终端读线程起不来：%s" % e)
    log_activity("ui", "在 %s 里开了一个真终端（%s）" % (workdir, item["name"]))
    return _summary(session)


def _pump(session):
    """读线程：PTY 主端 → 环形缓冲，并在退出时收尾。"""
    fd = session["master"]
    while True:
        if session["closed"]:
            break                   # 主人已经关掉这个终端了，别再赖着
        try:
            if not select.select([fd], [], [], PUMP_TICK)[0]:
                continue
            chunk = os.read(fd, READ_SIZE)
        except BlockingIOError:
            continue                # select 说可读但已被取空
        except OSError:
            break                   # 从端没人了，或主端已关
        if not chunk:
            break
        with session["cond"]:
            _push(session, chunk)
            session["cond"].notify_all()
    try:
        code = session["proc"].wait(timeout=5)
    except subprocess.TimeoutExpired:
        code = None
        stop_process(session["proc"], expected=(session["bin"],))
    except OSError:
        code = None
    with session["cond"]:
        session["alive"] = False
        session["exit_code"] = code
        session["cond"].notify_all()
    with session["io"]:                # 主端只能由读线程关：写和改尺寸都在这把锁里
        if session["master"] is not None:
            try:
                os.close(session["master"])
            except OSError:
                pass
            session["master"] = None


def _push(session, chunk):
    session["buf"] += chunk
    session["end"] += len(chunk)
    overflow = len(session["buf"]) - MAX_BUFFER
    if overflow > 0:
        session["buf"] = session["buf"][overflow:]
        session["start"] += overflow


def _live(session):
    return session["alive"] and not session.get("closed")


def core_terminal_input(session_id, data):
    """把前端来的字节写进 PTY 主端——那就是键盘。"""
    session = _get(session_id)
    if not isinstance(data, str):
        raise PanwebError(2, "invalid_argument", "键盘数据要写成 base64 字符串")
    try:
        raw = base64.b64decode(data or "", validate=True)
    except ValueError:                # 非 ASCII、长度不对都算这一类
        raise PanwebError(2, "invalid_argument", "键盘数据不是合法的 base64")
    if len(raw) > MAX_INPUT:
        raise PanwebError(2, "too_large",
                          "一次最多发 %d 字节" % MAX_INPUT,
                          "长内容分几次粘贴")
    if raw:
        _write(session, raw)
    return _summary(session)


def _write(session, raw):
    """写进主端就是"敲键盘"。主端是非阻塞的，所以这里绝不会在内核里等——
    粘长文写不完就等可写时机，超过 WRITE_TIMEOUT 明说，不占着锁装死。"""
    deadline = time.time() + WRITE_TIMEOUT
    view = memoryview(raw)
    with session["io"]:
        fd = session["master"]
        if fd is None:
            raise PanwebError(3, "exited", "这个终端里的程序已经退出了",
                              "重新开一个终端")
        while view:
            try:
                written = os.write(fd, bytes(view[:4096]))
            except BlockingIOError:
                written = 0
            except OSError as e:
                raise PanwebError(3, "exited", "写入终端失败：%s" % e)
            if written:
                view = view[written:]
                continue
            if time.time() > deadline:
                raise PanwebError(3, "blocked",
                                  "终端暂时不收输入（程序可能卡住了）",
                                  "等它一下，或关掉重开")
            select.select([], [fd], [], 0.1)


def core_terminal_resize(session_id, cols, rows):
    session = _get(session_id)
    cols, rows = _size(cols, rows)
    with session["io"]:
        if session["master"] is not None:
            try:
                fcntl.ioctl(session["master"], termios.TIOCSWINSZ,
                            struct.pack("HHHH", rows, cols, 0, 0))
            except OSError:
                pass
            else:   # 只有真改成功了才记账，否则网页与 PTY 的格数又会各说各话
                session["cols"], session["rows"] = cols, rows
    return _summary(session)


def core_terminal_close(session_id):
    session = _get(session_id)
    with _guard:
        if session_id in _sessions:
            _sessions.pop(session_id, None)
            if session_id in _order:
                _order.remove(session_id)
    with session["cond"]:
        session["closed"] = True        # 先让读线程知道，它最多一秒就自己收工
        session["cond"].notify_all()
    stop_process(session["proc"], expected=(session["bin"],))
    proc = session["proc"]
    if proc.poll() is None:             # node 这类会挡 SIGTERM 的，整组 KILL
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except OSError:
            proc.kill()
    log_activity("ui", "关掉了 %s 的终端" % session["name"])
    return {"closed": True, "id": session_id}


def core_terminal_sessions():
    with _guard:
        return [_summary(_sessions[sid]) for sid in _order if sid in _sessions]


def close_all_terms():
    """控制台退出时别把 Agent 留在后台。"""
    global _stopping
    _stopping = True
    with _guard:
        sids = list(_order)
    for sid in sids:
        try:
            core_terminal_close(sid)
        except PanwebError:
            pass


def _get(session_id):
    with _guard:
        session = _sessions.get(session_id)
    if not session:
        raise PanwebError(2, "not_found", "终端不在了", "重新开一个")
    return session


def _emit(handler, payload=None, note=None, event_id=None):
    """一帧 SSE。前端断了就返回 False，让推流自己收工。"""
    try:
        if note:
            body = "%s\n\n" % note
        else:
            body = "data: %s\n\n" % json.dumps(payload, ensure_ascii=False)
        if event_id is not None:
            body = "id: %d\n%s" % (event_id, body)
        handler.wfile.write(body.encode("utf-8"))
        handler.wfile.flush()
        return True
    except OSError:
        return False


def _cursor(handler, after):
    """补发起点：查询参数优先，其次是浏览器自动重连带来的 Last-Event-ID。"""
    try:
        cursor = max(0, int(after or 0))
    except (TypeError, ValueError):
        cursor = 0
    if cursor:
        return cursor
    try:
        return max(0, int(handler.headers.get("Last-Event-ID") or 0))
    except ValueError:
        return 0


def core_terminal_stream(handler, session_id, after=0):
    """SSE 推流：先补发游标之后的画面，再实时跟发，进程退出时收尾。"""
    session = _get(session_id)            # 查不到会话要在发头之前，才能回 JSON
    cursor = _cursor(handler, after)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Accel-Buffering", "no")
    handler._security_headers()
    handler.end_headers()
    try:
        _stream_loop(handler, session, cursor)
    except Exception:                     # noqa: BLE001
        # 头已经发出去了，再走 api_error 会往流里塞第二个状态行；断线就断线
        pass


def _stream_loop(handler, session, offset):
    if not _emit(handler, {"meta": _summary(session)}):
        return
    while True:
        with session["cond"]:
            offset, gap = _clamp(offset, session)
            chunk = session["buf"][offset - session["start"]:][:FRAME_BYTES]
            if not chunk and _live(session):
                session["cond"].wait(HEARTBEAT)
                offset, gap = _clamp(offset, session)
                chunk = session["buf"][offset - session["start"]:][:FRAME_BYTES]
            running = _live(session)
            exit_code = session["exit_code"]
            total = session["end"]
        if chunk:
            payload = {"o": offset + len(chunk),
                       "d": base64.b64encode(chunk).decode()}
            if gap:                       # 缓冲转了一圈把旧的丢了，得让前端重开画面
                payload["gap"] = True
            offset += len(chunk)
            if not _emit(handler, payload, event_id=offset):
                return
        elif not running:
            _emit(handler, {"exit": exit_code, "o": total}, event_id=total)
            return
        elif not _emit(handler, note=": ping"):
            return


def _clamp(offset, session):
    """把游标夹进 [start, end]；夹过就说明中间有字节被环形缓冲丢掉了。"""
    if offset < session["start"]:
        return session["start"], True
    if offset > session["end"]:
        return session["end"], False      # 客户端跑到了前面：等它自己追上来
    return offset, False
