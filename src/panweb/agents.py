"""本机 Agent 的技能安装、命令行白名单与检测。"""
import os
import re
import shutil

from . import runtime
from .errors import PanwebError
from .store import log_activity

AGENT_TARGETS = [
    {"id": "claude", "name": "Claude Code", "detect": "~/.claude",
     "skills": "~/.claude/skills", "letter": "C", "color": "#d97757"},
    {"id": "codex", "name": "Codex", "detect": "~/.codex",
     "skills": "~/.codex/skills", "letter": "X", "color": "#3d3d3d"},
    {"id": "zcode", "name": "ZCode", "detect": "~/.zcode",
     "skills": "~/.zcode/skills", "letter": "Z", "color": "#33796b"},
    {"id": "agents", "name": "通用 Agent 目录", "detect": "~/.agents",
     "skills": "~/.agents/skills", "letter": "A", "color": "#b9975b"},
    {"id": "opencode", "name": "OpenCode", "detect": "~/.config/opencode",
     "skills": "~/.config/opencode/skills", "letter": "O", "color": "#4c7dd0"},
]

AGENT_GUIDE = """把这台电脑的 panweb 发布技能装给你：

技能目录：
  {src}

请把该目录完整复制到你的技能目录（例如 ~/.agents/skills/ 或你自己的 skills 目录），
之后你就可以用这些话帮我发布本机应用：
  - 把 3000 端口发出去
  - 发布这个文件夹：<路径>
  - 帮我启动 /path/to/project 并发布到公网
注意：发布后网址是公开的；给我无密码服务加口令时用 --pin。
"""


def skill_source_dir():
    """panweb-publish 技能源目录（仓库内优先，回退已安装副本）。"""
    here = os.path.join(runtime.resource_root(), "skill", "panweb-publish")
    if os.path.isfile(os.path.join(here, "SKILL.md")):
        return here
    installed = os.path.expanduser("~/.agents/skills/panweb-publish")
    if os.path.isfile(os.path.join(installed, "SKILL.md")):
        return installed
    return None


def _read_skill_version():
    src = skill_source_dir()
    if not src:
        return None
    try:
        with open(os.path.join(src, "SKILL.md"), "r", encoding="utf-8") as f:
            m = re.search(r'^version:\s*"?([^"\n]+)"?', f.read(), re.M)
            return m.group(1).strip() if m else None
    except OSError:
        return None


def core_agents():
    """检测本机 Agent 与 panweb 技能接入状态。"""
    version = _read_skill_version()
    out = []
    for t in AGENT_TARGETS:
        detect = os.path.isdir(os.path.expanduser(t["detect"]))
        skills_dir = os.path.expanduser(t["skills"])
        target = os.path.join(skills_dir, "panweb-publish")
        connected = os.path.isfile(os.path.join(target, "SKILL.md"))
        out.append({"id": t["id"], "name": t["name"], "letter": t["letter"],
                    "color": t["color"], "detected": detect,
                    "connected": connected,
                    "skills_dir": skills_dir, "version": version})
    return out


def core_agent_connect(agent_id):
    """把 panweb-publish 技能复制到指定 Agent 的技能目录（只写技能目录）。"""
    src = skill_source_dir()
    if not src:
        raise PanwebError(3, "skill_missing", "找不到技能源目录",
                          "先运行 install.sh 安装技能")
    for t in AGENT_TARGETS:
        if t["id"] == agent_id:
            dst = os.path.join(os.path.expanduser(t["skills"]),
                               "panweb-publish")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            log_activity("ui", "已为 %s 安装 panweb 技能" % t["name"], dst)
            return {"id": agent_id, "dir": dst}
    raise PanwebError(2, "not_found", "未知的 Agent：%s" % agent_id)


def core_agent_disconnect(agent_id):
    for t in AGENT_TARGETS:
        if t["id"] == agent_id:
            dst = os.path.join(os.path.expanduser(t["skills"]),
                               "panweb-publish")
            if os.path.isdir(dst):
                shutil.rmtree(dst)
                log_activity("ui", "已从 %s 移除 panweb 技能" % t["name"], dst)
            return {"id": agent_id, "removed": True}
    raise PanwebError(2, "not_found", "未知的 Agent：%s" % agent_id)


# 交互模式下"允许它动手"的开关（主人选了直接可执行）
TERMINALS = {
    "claude": {
        "bin": "claude", "name": "Claude Code",
        "argv": ("--dangerously-skip-permissions",),
        "note": "跳过全部权限检查：它会直接改本机文件、执行发布命令",
    },
    "codex": {
        "bin": "codex", "name": "Codex",
        "argv": ("--approve-for-me",),
        "note": "工作区可写 + 自动批准：命令在 codex 的沙盒策略里执行",
    },
    "opencode": {
        "bin": "opencode", "name": "OpenCode",
        "argv": ("--auto",),
        "note": "自动批准未被显式拒绝的权限请求",
    },
}


def find_agent_binary(name):
    """从 PATH 加常见安装目录找 Agent 二进制：从启动台打开的 App 里 PATH 很短。"""
    path = shutil.which(name)
    if path:
        return path
    for d in runtime.USER_BIN_DIRS:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def terminal_for(agent_id):
    item = TERMINALS.get(agent_id)
    if not item:
        raise PanwebError(2, "not_found", "不支持的终端 Agent：%s" % agent_id,
                          "可选：%s" % "、".join(sorted(TERMINALS)))
    path = find_agent_binary(item["bin"])
    if not path:
        raise PanwebError(3, "dependency_missing",
                          "没找到 %s 命令" % item["bin"],
                          "先装好这个 Agent；~/.local/bin、/opt/homebrew/bin "
                          "这些常见位置也会一起找")
    return item, path


def core_terminal_agents():
    """能开真终端的 Agent：二进制在不在、panweb 技能装没装、动手意味着什么。"""
    connected = {a["id"]: a.get("connected") for a in core_agents()}
    out = []
    for agent_id, item in TERMINALS.items():
        path = find_agent_binary(item["bin"])
        out.append({"id": agent_id, "name": item["name"], "ready": bool(path),
                    "path": path, "note": item["note"],
                    "connected": bool(connected.get(agent_id))})
    return out
