"""部署与路径边界：.nojekyll 必须落盘，敏感目录及其子目录必须拒绝。"""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import helpers  # noqa: F401
from helpers import temp_home
from panweb import hosting, safety
from panweb.errors import PanwebError


class NoJekyllTests(unittest.TestCase):
    def test_core_host_writes_nojekyll_before_git(self):
        with temp_home("panweb-host-"):
            src = tempfile.mkdtemp(prefix="panweb-src-")
            with open(os.path.join(src, "index.html"), "w", encoding="utf-8") as f:
                f.write("<h1>hi</h1>")

            def fake_build(_src, stage, _name):
                os.makedirs(stage, exist_ok=True)
                with open(os.path.join(stage, "index.html"), "w") as f:
                    f.write("built")
                return 1

            reply = SimpleNamespace(returncode=0, stdout="owner\n", stderr="")
            with mock.patch.object(hosting, "require_publish_license"), \
                    mock.patch.object(hosting, "gh_logged_in", return_value=True), \
                    mock.patch.object(hosting, "build_site", side_effect=fake_build), \
                    mock.patch.object(hosting, "_gh", return_value=reply), \
                    mock.patch.object(hosting, "load_hosted",
                                      return_value=[{"repo": "owner/panweb-nojekyll"}]), \
                    mock.patch.object(hosting, "save_hosted"), \
                    mock.patch.object(hosting, "log_activity"), \
                    mock.patch.object(hosting.subprocess, "run",
                                      return_value=SimpleNamespace(returncode=0,
                                                                   stdout="",
                                                                   stderr="")):
                result = hosting.core_host(src, name="nojekyll")
            stage = os.path.join(hosting.runtime.HOSTING_DIR, "nojekyll")
            self.assertTrue(os.path.isfile(os.path.join(stage, ".nojekyll")),
                            "GitHub Pages 会丢 _next/_astro，必须写空 .nojekyll")
            self.assertTrue(result["url"].endswith("/"))


class SensitiveFolderTests(unittest.TestCase):
    SENSITIVE = ("~/.ssh", "~/.ssh/keys", "~/.aws", "~/.aws/credentials",
                 "~/.gnupg", "~/.config", "~/.panweb", "~/.kube",
                 "~/.docker", "~/Library/Keychains",
                 "~/Library/Keychains/login.keychain-db")

    def test_sensitive_prefixes_and_children_are_rejected(self):
        for path in self.SENSITIVE:
            with self.subTest(path=path):
                with self.assertRaises(PanwebError):
                    safety.check_pages_folder(os.path.expanduser(path))

    def test_ordinary_temp_folder_is_allowed(self):
        folder = tempfile.mkdtemp(prefix="panweb-safe-")
        safety.check_pages_folder(folder)


if __name__ == "__main__":
    unittest.main()
