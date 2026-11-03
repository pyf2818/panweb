import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

from helpers import ROOT


class BuildTests(unittest.TestCase):
    def test_ui_build_matches_sources(self):
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "build_ui.py"),
                              "--check"], capture_output=True, text=True,
                             timeout=30)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def _max_lines(self, pattern, limit, label):
        for path in sorted(ROOT.glob(pattern)):
            if path.name.startswith("._"):
                continue  # macOS AppleDouble 伴生文件
            lines = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(lines, limit,
                                 "%s 过大（%d 行 > %d）" % (label, lines, limit))

    def test_no_giant_modules(self):
        """巨型文件守不住也测不出来；这里是硬上限。

        豁免：ui/index.html（build_ui.py 的生成物）、ui/vendor/（第三方库原文，
        不做拆改）、docs 与 README（长文属正常）。
        """
        launcher = (ROOT / "panweb").read_text(encoding="utf-8")
        self.assertLessEqual(len(launcher.splitlines()), 50)
        self._max_lines("src/panweb/*.py", 500, "后端模块")
        self._max_lines("ui/src/js/*.js", 400, "前端脚本")
        self._max_lines("ui/src/styles/*.css", 400, "前端样式")
        self._max_lines("ui/src/partials/*.html", 400, "前端片段")
        self._max_lines("tools/*.py", 220, "工具脚本")
        self._max_lines("tests/*.py", 320, "测试模块")

    def test_generated_ui_is_marked(self):
        """产物必须自我声明「生成文件，请勿手改」，否则没人知道该改哪里。"""
        html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn("请勿直接编辑", html.splitlines()[1])
        self.assertIn("ui/src/", html.splitlines()[1])
        self.assertNotIn("<!--__PANWEB_PAGES__-->", html)

    def test_zipapp_builds_and_runs(self):
        with tempfile.TemporaryDirectory(prefix="panweb-pyz-test-") as tmp:
            out = pathlib.Path(tmp) / "panweb.pyz"
            build = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "build_zipapp.py"),
                 "--out", str(out)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([sys.executable, str(out), "--version"],
                                 capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("1.6.0", run.stdout)

            with zipfile.ZipFile(out) as z:
                names = z.namelist()
                junk = [n for n in names
                        if os.path.basename(n).startswith("._")
                        or "__pycache__" in n or n.endswith(".pyc")
                        or os.path.basename(n) == ".DS_Store"]
                self.assertEqual(junk, [], "分发物里混进了伴生/缓存文件")
                packaged = {os.path.basename(n) for n in names
                            if n.startswith("panweb/") and n.endswith(".py")}
                source = {p.name for p in (ROOT / "src" / "panweb").glob("*.py")
                          if not p.name.startswith("._")}
                self.assertEqual(source - packaged, set(),
                                 "zipapp 少了后端模块")
                self.assertTrue(any(n.endswith("ui/index.html") for n in names),
                                "zipapp 少了控制台产物")

    def test_all_modules_import(self):
        code = (
            "import pkgutil, importlib, panweb\n"
            "for m in pkgutil.iter_modules(panweb.__path__):\n"
            "    if m.name != '__main__':\n"
            "        importlib.import_module('panweb.' + m.name)\n"
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True,
                             env={"PYTHONPATH": str(ROOT / "src")},
                             timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
