"""在控制台里驱动本机已安装的 Agent 命令行，帮主人把应用发出去。

这里不实现对话逻辑，也不实现任何模型：只负责「起一个本机 Agent 的一次性会话、
把它打印的内容收回来、允许主人随时掐掉」。Agent 二进制只从固定白名单里按 PATH
解析，命令行用 argv 数组构造，绝不经过 shell —— 界面上进来的是选择，不是命令。
"""
import os
import select
import shutil
import subprocess
import threading
import time
import uuid

from .agents import core_agents
from .errors import PanwebError
from .store import log_activity

# 各家 CLI 的非交互模式与"允许它动手"的开关（主人选了直接可执行）
RUNNERS = {
    "claude": {
        "bin": "claude", "name": "Claude Code",
        "argv": ("--print", "--dangerously-skip-permissions"),
        "note": "跳过全部权限检查：它会直接改本机文件、执行发布命令",
    },
    "codex": {
        "bin": "codex", "name": "Codex",
        # --approve-for-me 自带 workspace-write 沙盒；再显式传 --sandbox 会被它拒绝。
        # 主人选的工作目录通常不是 git 仓库，codex 默认不肯跑，所以要 skip-git-repo-check。
        "argv": ("exec", "--approve-for-me", "--skip-git-repo-check"),
        "dash": True,
        "note": "工作区可写 + 自动批准：命令在 codex 的沙盒策略里执行",
    },
    "opencode": {
        "bin": "opencode", "name": "OpenCode",
        "argv": ("run", "--auto"),
        "note": "自动批准未被显式拒绝的权限请求",
    },
}

CONTEXT = (
    "你在 panweb 控制台里和主人对话，帮他把这台电脑上的应用发布到公网。\n"
    "可用命令：panweb discover / publish / pages / run / list / stop / check / compat / status / doctor。\n"
    "规则：默认取最窄的做法；无密码的模型服务、数据库、含个人数据的目录属于高危，动手前先说清风险；"
    "发布出来的网址是公开的；不要把口令或密钥写进对话，也不要读 ~/.panweb/secrets。"
)

MAX_SESSIONS = 8
MAX_RUNNING = 2
MAX_OUTPUT = 200000        # 每个会话最多留 200KB 输出，超了丢最早的
TURN_TIMEOUT = 600.0
DRAIN_GRACE = 3            # 进程退出后再等几个 1 秒周期，看还有没有尾巴
HISTORY_TURNS = 6
HISTORY_CHARS = 6000

_sessions = {}
_order = []
_guard = threading.Lock()


def runner_for(agent_id):
    runner = RUNNERS.get(agent_id)
    if not runner:
        raise PanwebError(2, "not_found", "不支持的 Agent：%s" % agent_id,
                          "可选：%s" % "、".join(sorted(RUNNERS)))
    path = shutil.which(runner["bin"])
    if not path:
        raise PanwebError(3, "dependency_missing",
                          "没找到 %s 命令" % runner["bin"],
                          "先装好这个 Agent，或在终端里确认它的可执行文件在 PATH 里")
    return runner, path


def core_agent_list():
    """可对话的 Agent：二进制在不在、技能装没装、动手意味着什么。"""
    connected = {a["id"]: a.get("connected") for a in core_agents()}
    out = []
    for agent_id, runner in RUNNERS.items():
        path = shutil.which(runner["bin"])
        out.append({"id": agent_id, "name": runner["name"], "ready": bool(path),
                    "path": path, "note": runner["note"],
                    "connected": bool(connected.get(agent_id))})
    return out


def _build_prompt(session, text):
    """把前几轮压缩进本次提问：各家 CLI 的会话续接参数不一致，一次性调用最稳。"""
    turns = session["turns"][-HISTORY_TURNS:]
    past = []
    for turn in turns:
        role = "主人" if turn["role"] == "user" else "你"
        past.append("%s：%s" % (role, (turn["text"] or "").strip()))
    body = "\n".join(past[-6:]) if past else ""
    if len(body) > HISTORY_CHARS:
        body = body[-HISTORY_CHARS:]
    parts = [CONTEXT]
    if body:
        parts.append("此前对话：\n%s" % body)
    parts.append("主人现在说：\n%s" % text)
    return "\n\n".join(parts)


def _validate_cwd(cwd):
    path = os.path.expanduser((cwd or "").strip())
    if not path:
        path = os.path.expanduser("~")
    if not os.path.isdir(path):
        raise PanwebError(2, "invalid_argument",
                          "工作目录不存在：%s" % path,
                          "填一个本机真实存在的目录，Agent 会在那里干活")
    return os.path.realpath(path)


def _append_output(session, chunk):
    with session["lock"]:
        session["out"] = (session["out"] + chunk)[-MAX_OUTPUT:]


def _drain(session, proc):
    """按块收输出。

    不能只等 EOF：Agent 常常留下一个后台钩子进程继承同一根管道，那样正文早就打完了，
    会话却会一直挂在"正在思考"。所以进程一退出、且短时间再无新内容就收工。
    """
    fd = proc.stdout.fileno()
    deadline = time.time() + TURN_TIMEOUT
    quiet = 0
    while True:
        if time.time() > deadline:
            _kill(proc)
            proc.wait()
            return "timeout"
        ready, _, _ = select.select([fd], [], [], 1.0)
        if ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                break
            quiet = 0
            _append_output(session, chunk.decode("utf-8", "replace"))
            continue
        if proc.poll() is not None:
            quiet += 1
            if quiet >= DRAIN_GRACE:
                break
    return proc.wait()


def _run_turn(session, text):
    """一个回合：起进程、收输出、退出后落状态。"""
    runner, binary = runner_for(session["agent"])
    prompt = _build_prompt(session, text)
    # 提示词是位置参数；声明了 dash 的 CLI（codex 用 clap）加 --，
    # 免得主人贴的第一行以短横开头就被当成开关
    argv = [binary] + list(runner["argv"])
    argv += ["--", prompt] if runner.get("dash") else [prompt]
    try:
        proc = subprocess.Popen(
            argv, cwd=session["cwd"], stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True)
    except OSError as e:
        _finish(session, "failed", "%s 启动失败：%s" % (runner["name"], e))
        return
    session["proc"] = proc
    try:
        code = _drain(session, proc)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
    if session.get("stop"):
        # 主人已经按了停止：状态由那边写，这里不能拿退出码把它盖成"空闲"
        _finish(session, "stopped", "主人手动停止了这一轮")
    elif code == "timeout":
        _finish(session, "timeout", "这一轮超过 %d 秒，已停止" % int(TURN_TIMEOUT))
    elif code == 0:
        _finish(session, "idle")
    else:
        _finish(session, "failed", "%s 退出码 %s" % (runner["name"], code))


def _finish(session, status, error=None):
    with session["lock"]:
        session["status"] = status
        session["error"] = error
        session["since"] = None
        session["proc"] = None
    answer = _last_answer(session)
    if answer:
        session["turns"].append({"role": "agent", "text": answer, "ts": time.time()})


def _last_answer(session):
    with session["lock"]:
        text = session["out"]
    return text[-8000:] if text else ""


def _kill(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), 15)
    except OSError:
        try:
            proc.terminate()
        except OSError:
            pass


def _summary(session):
    with session["lock"]:
        return {"id": session["id"], "agent": session["agent"],
                "name": session["name"], "cwd": session["cwd"],
                "status": session["status"], "error": session["error"],
                "turns": len(session["turns"]),
                "bytes": len(session["out"]),
                "since": session["since"], "created": session["created"]}


def _begin_turn(session, text):
    """先把状态改成 running 再起线程：否则调用方立刻查一次会看到"空闲"，以为没干活。"""
    session["turns"].append({"role": "user", "text": text, "ts": time.time()})
    with session["lock"]:
        session["status"] = "running"
        session["error"] = None
        session["since"] = time.time()
        session["stop"] = False
    threading.Thread(target=_run_turn, args=(session, text), daemon=True).start()


def core_agent_start(agent, cwd="", text="", name=""):
    """开一个会话；text 非空就立刻发第一轮。"""
    runner, _ = runner_for(agent)
    workdir = _validate_cwd(cwd)
    with _guard:
        running = sum(1 for s in _sessions.values() if s["status"] == "running")
        if running >= MAX_RUNNING:
            raise PanwebError(3, "busy", "已经有 %d 个 Agent 在跑" % running,
                              "先停掉一个再开新的")
        sid = uuid.uuid4().hex[:6]
        session = {"id": sid, "agent": agent, "name": name or runner["name"],
                   "cwd": workdir, "status": "idle", "error": None,
                   "out": "", "turns": [], "since": None, "proc": None,
                   "stop": False,
                   "created": time.time(), "lock": threading.Lock()}
        _sessions[sid] = session
        _order.append(sid)
        while len(_order) > MAX_SESSIONS:
            old = _order.pop(0)
            victim = _sessions.pop(old, None)
            if victim:
                _kill(victim["proc"])
    log_activity("ui", "在 %s 里开了一个会话（%s）" % (workdir, runner["name"]))
    if text.strip():
        _begin_turn(session, text.strip())
    return _summary(session)


def core_agent_send(session_id, text):
    text = (text or "").strip()
    if not text:
        raise PanwebError(2, "invalid_argument", "要说点什么才能让 Agent 干活")
    session = _sessions.get(session_id)
    if not session:
        raise PanwebError(2, "not_found", "会话不在了", "刷新一下重新开一个")
    if session["status"] == "running":
        raise PanwebError(3, "busy", "这个会话正在回答，先等它说完或点停止")
    _begin_turn(session, text)
    return _summary(session)


def core_agent_output(session_id, after=0):
    session = _sessions.get(session_id)
    if not session:
        raise PanwebError(2, "not_found", "会话不在了", "刷新一下重新开一个")
    summary = _summary(session)
    # 分两次取锁：_summary 自己也要锁，套在里面就是自锁
    with session["lock"]:
        start = max(0, min(int(after or 0), len(session["out"])))
        summary["text"] = session["out"][start:]
        summary["after"] = len(session["out"])
    return summary


def core_agent_stop(session_id):
    session = _sessions.get(session_id)
    if not session:
        raise PanwebError(2, "not_found", "会话不在了")
    with session["lock"]:
        session["stop"] = True
    _kill(session["proc"])
    if session["status"] == "running":
        _finish(session, "stopped", "主人手动停止了这一轮")
    return _summary(session)


def core_agent_sessions():
    with _guard:
        return [_summary(_sessions[sid]) for sid in _order if sid in _sessions]
