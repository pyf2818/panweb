"""打开系统默认浏览器。"""
import subprocess
import sys


def open_browser(url):
    try:
        cmd = ["open", url] if sys.platform == "darwin" else ["xdg-open", url]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except OSError:
        pass
