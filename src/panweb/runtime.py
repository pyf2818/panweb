"""运行期路径、常量与资源访问。

所有模块通过本模块读取路径（``runtime.HOME_DIR``），测试用 ``set_home()``
把状态隔离到临时目录。不要在业务模块里缓存路径字符串的副本。
"""
import os
import re
import sys
import time
import zipfile

PANWEB_VERSION = "1.6.0"
STARTED_AT = time.time()

HOME_DIR = os.path.expanduser("~/.panweb")
STATE_FILE = os.path.join(HOME_DIR, "state.json")
STATE_LOCK_FILE = os.path.join(HOME_DIR, "state.lock")
LOG_DIR = os.path.join(HOME_DIR, "logs")
ACTIVITY_FILE = os.path.join(HOME_DIR, "activity.json")
META_FILE = os.path.join(HOME_DIR, "meta.json")
VISITS_DIR = os.path.join(HOME_DIR, "visits")
SECRETS_DIR = os.path.join(HOME_DIR, "secrets")
DAEMON_PID = os.path.join(HOME_DIR, "daemon.pid")
POOL_FILE = os.path.join(HOME_DIR, "pool.json")
DOMAIN_FILE = os.path.join(HOME_DIR, "domain.json")
HOSTING_DIR = os.path.join(HOME_DIR, "hosting")
HOSTED_FILE = os.path.join(HOME_DIR, "hosted.json")
MENUBAR_STATE = os.path.join(HOME_DIR, "menubar-state.json")
LICENSE_FILE = os.path.join(HOME_DIR, "license.json")

UI_DEFAULT_PORT = 7788
MAX_UI_BODY = 64 * 1024 * 1024
MAX_UPLOAD_BYTES = 40 * 1024 * 1024

UNSAFE_PAGE_ROOTS = ("/", "/etc", "/private", "/System", "/Library",
                     "/Applications", "/usr", "/bin", "/sbin", "/var",
                     "/opt", "/Volumes")

CLOUDFLARED_CANDIDATES = [
    "cloudflared",
    "/opt/homebrew/bin/cloudflared",
    "/usr/local/bin/cloudflared",
    os.path.expanduser("~/homebrew/bin/cloudflared"),
]

# Agent 命令行常待的位置：从启动台打开的 App 里 PATH 很短，只靠 which 会误报"未安装"
USER_BIN_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    os.path.expanduser("~/.local/bin"),
    os.path.expanduser("~/.npm-global/bin"),
    os.path.expanduser("~/bin"),
]

TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

SHARE_PATH = "/__panweb/share"
LOGIN_PATH = "/__panweb/login"

KNOWN_PORTS = {
    3000: "React/Next.js 常用端口",
    3001: "前端开发服务",
    3333: "开发服务",
    4200: "Angular 开发服务",
    4321: "Astro 开发服务",
    5000: "Flask/Django 常用端口",
    5173: "Vite 开发服务",
    5174: "Vite 开发服务",
    6800: "Web 服务",
    7860: "Gradio 应用",
    8000: "Python Web 常用端口",
    8080: "Web 服务常用端口",
    8081: "Web 服务",
    8888: "Jupyter 常用端口",
    9000: "Web 服务",
    11434: "Ollama 本地模型服务",
    12393: "ComfyUI 常用端口",
    8188: "ComfyUI 常用端口",
}

RISKY_PORTS = {
    11434: "Ollama 模型服务（无密码，公开后任何人可用你的算力）",
    8188: "ComfyUI（无密码，公开后任何人可用你的算力）",
    12393: "ComfyUI（无密码，公开后任何人可用你的算力）",
    7860: "Gradio 应用（若无需登录请先加密）",
    3306: "MySQL 数据库（绝不应该公开）",
    5432: "PostgreSQL 数据库（绝不应该公开）",
    6379: "Redis（绝不应该公开）",
    27017: "MongoDB（绝不应该公开）",
}


def _path(name):
    return os.path.join(HOME_DIR, name)


def set_home(path):
    """切换状态目录，并同步所有派生路径（测试/便携模式）。"""
    global HOME_DIR, STATE_FILE, STATE_LOCK_FILE, LOG_DIR, ACTIVITY_FILE
    global META_FILE, VISITS_DIR, SECRETS_DIR, DAEMON_PID, POOL_FILE
    global DOMAIN_FILE, HOSTING_DIR, HOSTED_FILE, MENUBAR_STATE, LICENSE_FILE
    HOME_DIR = os.path.abspath(os.path.expanduser(path))
    STATE_FILE = _path("state.json")
    STATE_LOCK_FILE = _path("state.lock")
    LOG_DIR = _path("logs")
    ACTIVITY_FILE = _path("activity.json")
    META_FILE = _path("meta.json")
    VISITS_DIR = _path("visits")
    SECRETS_DIR = _path("secrets")
    DAEMON_PID = _path("daemon.pid")
    POOL_FILE = _path("pool.json")
    DOMAIN_FILE = _path("domain.json")
    HOSTING_DIR = _path("hosting")
    HOSTED_FILE = _path("hosted.json")
    MENUBAR_STATE = _path("menubar-state.json")
    LICENSE_FILE = _path("license.json")


_HOME_ENV = os.environ.get("PANWEB_HOME")
if _HOME_ENV:
    set_home(_HOME_ENV)


def _archive_path():
    """当前包是否运行在 zipapp 内，返回 zip 文件路径。"""
    here = os.path.realpath(__file__)
    marker = ".pyz" + os.sep
    if marker in here:
        return here.split(marker, 1)[0] + ".pyz"
    return None


def is_zipapp():
    return _archive_path() is not None


def resource_root():
    """ui/skill/assets 等资源根目录。App 由 launcher 显式指定。"""
    env = os.environ.get("PANWEB_RESOURCE_ROOT")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    pkg = os.path.dirname(os.path.realpath(__file__))
    return os.path.dirname(os.path.dirname(pkg))


def read_resource(rel):
    """读取资源文件；源码目录与 zipapp 都支持，找不到返回 None。"""
    archive = _archive_path()
    if archive:
        try:
            with zipfile.ZipFile(archive) as z:
                return z.read(rel)
        except (OSError, KeyError, zipfile.BadZipFile):
            return None
    path = os.path.join(resource_root(), rel)
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def ui_dir_candidates():
    return [os.path.join(resource_root(), "ui"),
            os.path.join(HOME_DIR, "ui")]


def entrypoint():
    """可再次执行的 panweb 入口（用于拉起代理/控制台子进程）。"""
    env = os.environ.get("PANWEB_ENTRYPOINT")
    if env and os.path.isfile(env):
        return os.path.realpath(env)
    archive = _archive_path()
    if archive:
        return archive
    argv0 = os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if argv0 and os.path.isfile(argv0):
        base = os.path.basename(argv0)
        if base == "panweb" or base.endswith(".pyz"):
            return argv0
    return None


def self_command(*args):
    """生成本程序子进程的 argv（不使用 shell）。"""
    ep = entrypoint()
    if ep:
        return [sys.executable, ep] + list(args)
    return [sys.executable, "-m", "panweb"] + list(args)


def self_env():
    """子进程环境；继承当前状态目录，模块方式启动时补上包所在目录。"""
    env = os.environ.copy()
    env["PANWEB_HOME"] = HOME_DIR
    pkg = os.path.dirname(os.path.realpath(__file__))
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.path.dirname(pkg) + (os.pathsep + old if old else "")
    return env


def process_signature():
    ep = entrypoint()
    return os.path.basename(ep) if ep else "panweb"
