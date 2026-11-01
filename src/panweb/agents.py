"""本机 Agent 技能安装与检测。"""
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
