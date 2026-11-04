"""P1-7：App/CLI 的 Python 依赖要写准、要在入口拦住过低版本。"""
import os
import unittest

import helpers  # noqa: F401  导入它顺带把 src/ 放进 sys.path
from panweb import discovery, packaging

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class PythonVersionGuardTests(unittest.TestCase):
    def test_cli_launcher_rejects_python_below_39(self):
        text = read("panweb")
        self.assertIn("version_info", text,
                      "CLI 启动器要在 import 前拦住过低版本")
        self.assertIn("3, 9", text)
        self.assertIn("SystemExit", text)

    def test_app_launcher_rejects_python_below_39(self):
        script = packaging.app_launcher_script()
        self.assertIn("version_info", script,
                      "App 双击启动器要给出可读的版本错误")
        self.assertIn("3, 9", script)
        self.assertIn("osascript", script)

    def test_installer_checks_python_version(self):
        text = read("install.sh")
        self.assertIn("python3", text)
        self.assertIn("version_info", text, "install.sh 不能只检查存在性")
        self.assertIn("3.9", text)

    def test_doctor_reports_python_runtime(self):
        data = discovery.core_doctor(force=True)
        info = data.get("python") or {}
        self.assertTrue(info.get("ok"))
        self.assertIn("version", info)
        self.assertIn("path", info)


class ClaimTests(unittest.TestCase):
    def test_docs_do_not_claim_fully_self_contained_app(self):
        self.assertNotIn("自包含 App", read("Makefile"))
        self.assertNotIn("自包含 macOS App", read("docs", "architecture.md"))
        self.assertNotIn("唯一外部依赖", read("README.md"))

    def test_docs_state_python_minimum(self):
        self.assertIn("3.9", read("README.md"))
        self.assertIn("3.9", read("tools", "build_dmg.py"))


if __name__ == "__main__":
    unittest.main()
