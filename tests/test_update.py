"""更新机制：先看许可窗口再谈版本，下载要如实报错、不许悄悄替换正在跑的 App。"""
import hashlib
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

import helpers  # noqa: F401  导入它顺带把 src/ 放进 sys.path
from panweb import runtime, update
from panweb.errors import PanwebError


def release(tag="v9.9.9", names=("panweb-9.9.9-arm64.dmg",
                                 "panweb-9.9.9-x86_64.dmg"), body="修了几个坑",
            with_sums=True):
    assets = [{"name": n, "browser_download_url": "https://dl.test/%s" % n,
               "size": 4096} for n in names]
    if with_sums:
        assets.append({"name": "SHA256SUMS", "size": 100,
                       "browser_download_url": "https://dl.test/SHA256SUMS"})
    return {"tag_name": tag, "name": tag, "body": body, "assets": assets}


def lic(active=True, until="2027-03-01", mode="active"):
    return {"mode": mode, "updates_active": active, "updates_until_text": until}


class FakeResp:
    """假的 HTTP 响应：按块吐出固定字节，够 _download 读干净。"""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read(self, size=-1):
        chunk = self.data[self.pos:self.pos + size]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class BrokenResp(FakeResp):
    """吐出一小段后断掉，模拟下载中途网络中断。"""

    def __init__(self, data, fail_after=100):
        super().__init__(data)
        self.fail_after = fail_after

    def read(self, size=-1):
        if self.pos >= self.fail_after:
            raise OSError("connection reset")
        return super().read(min(size, self.fail_after - self.pos))


class VersionTests(unittest.TestCase):
    def test_common_tag_shapes(self):
        self.assertEqual(update.parse_version("v1.6.0"), (1, 6, 0))
        self.assertEqual(update.parse_version("1.10.2"), (1, 10, 2))
        self.assertEqual(update.parse_version("1.6"), (1, 6, 0))
        self.assertEqual(update.parse_version("版本 2.3.4 起"), (2, 3, 4))

    def test_unparsable_is_lowest(self):
        for bad in ("", None, "latest", "nightly"):
            self.assertEqual(update.parse_version(bad), (0, 0, 0))

    def test_1_10_beats_1_9(self):
        self.assertGreater(update.parse_version("v1.10.0"),
                           update.parse_version("v1.9.0"))


class AssetTests(unittest.TestCase):
    def test_matching_arch_first(self):
        with mock.patch.object(update.platform, "machine",
                               return_value="x86_64"):
            got = update.pick_asset(release())
        self.assertEqual(got["name"], "panweb-9.9.9-x86_64.dmg")
        self.assertEqual(got["kind"], "dmg")

    def test_any_dmg_when_no_arch_hit(self):
        with mock.patch.object(update.platform, "machine",
                               return_value="arm64"):
            got = update.pick_asset(release(names=("panweb-9.9.9-x86_64.dmg",)))
        self.assertEqual(got["name"], "panweb-9.9.9-x86_64.dmg")

    def test_fallback_to_pyz(self):
        got = update.pick_asset({"assets": [
            {"name": "panweb.pyz",
             "browser_download_url": "https://dl.test/panweb.pyz", "size": 10}]})
        self.assertEqual(got["kind"], "pyz")

    def test_nothing_usable(self):
        self.assertIsNone(update.pick_asset({"assets": [{"name": "src.zip"}]}))
        self.assertIsNone(update.pick_asset({}))


class StatusTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(update, "license_status", return_value=lic())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_newer_release_is_reported(self):
        with mock.patch.object(update, "_get_json", return_value=release()):
            out = update.core_update_status()
        self.assertTrue(out["newer"])
        self.assertEqual(out["latest"], "v9.9.9")
        self.assertEqual(out["current"], runtime.PANWEB_VERSION)
        self.assertTrue(out["updates_active"])
        self.assertIsNotNone(out["asset"])

    def test_same_tag_is_not_newer(self):
        tag = "v%s" % runtime.PANWEB_VERSION
        with mock.patch.object(update, "_get_json",
                               return_value=release(tag=tag)):
            out = update.core_update_status()
        self.assertFalse(out["newer"])
        self.assertIsNone(out["asset"], "没新版本就不该给出升级包")

    def test_older_release_does_not_downgrade(self):
        with mock.patch.object(update, "_get_json",
                               return_value=release(tag="v0.1.0")):
            self.assertFalse(update.core_update_status()["newer"])

    def test_unreleased_repo_says_so(self):
        err = urllib.error.HTTPError("u", 404, "Not Found", {}, None)
        with mock.patch.object(update, "_get_json", side_effect=err):
            with self.assertRaises(PanwebError) as ctx:
                update.core_update_status()
        self.assertEqual(ctx.exception.err_type, "not_found")

    def test_network_failure_is_honest(self):
        with mock.patch.object(update, "_get_json",
                               side_effect=urllib.error.URLError("dns down")):
            with self.assertRaises(PanwebError) as ctx:
                update.core_update_status()
        self.assertEqual(ctx.exception.err_type, "network")

    def test_junk_response_rejected(self):
        with mock.patch.object(update, "_get_json", return_value=[1, 2]):
            with self.assertRaises(PanwebError) as ctx:
                update.core_update_status()
        self.assertEqual(ctx.exception.err_type, "network")

    def test_bad_repo_slug_is_argument_error(self):
        with mock.patch.dict(os.environ, {"PANWEB_RELEASE_REPO": "../etc/passwd"}):
            with self.assertRaises(PanwebError) as ctx:
                update.latest_release()
        self.assertEqual(ctx.exception.err_type, "invalid_argument")


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.ctx = helpers.temp_home("panweb-update-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        # release() 的摘要清单按 arm64 命名；固定 fixture 架构，避免 x86_64
        # runner 选到另一个 dmg 后把校验错误伪装成下载/地址错误。
        patcher = mock.patch.object(update.platform, "machine",
                                    return_value="arm64")
        patcher.start()
        self.addCleanup(patcher.stop)
        # 真打开 dmg 会在测试机上挂载磁盘镜像，必须拦掉
        patcher = mock.patch.object(update, "_open_quietly", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, payload=b"x" * 4096, lic_state=None, rel=None, sums=None,
             resp=None):
        urls = []
        if sums is None and isinstance(payload, bytes):
            sums = "%s  panweb-9.9.9-arm64.dmg\n" % hashlib.sha256(
                payload).hexdigest()
        if sums is None:
            sums = "%s  panweb-9.9.9-arm64.dmg\n" % ("0" * 64)

        def spy(req, timeout=0):
            urls.append(req.full_url)
            if isinstance(payload, Exception):
                raise payload
            if req.full_url.endswith("SHA256SUMS"):
                return FakeResp(sums.encode("utf-8"))
            return resp or FakeResp(payload)

        patchers = [mock.patch.object(update, "license_status",
                                      return_value=lic_state or lic()),
                    mock.patch.object(update, "_get_json",
                                      return_value=rel or release()),
                    mock.patch("urllib.request.urlopen", side_effect=spy)]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        try:
            return update.core_update_apply(), urls
        except PanwebError as e:
            return e, urls

    def test_license_window_blocks_upgrade(self):
        err, urls = self._run(lic_state=lic(active=False, until="2024-01-01"))
        self.assertIsInstance(err, PanwebError, str(err))
        self.assertEqual(err.err_type, "license_expired")
        self.assertEqual(err.exit_code, 5)
        self.assertEqual(urls, [], "更新权益过期就不该发起下载")

    def test_happy_path_lands_and_hashes(self):
        result, urls = self._run()
        self.assertNotIsInstance(result, PanwebError, str(result))
        self.assertTrue(result["downloaded"].endswith("panweb-9.9.9-arm64.dmg"))
        self.assertEqual(result["size"], 4096)
        self.assertEqual(result["sha256"],
                         hashlib.sha256(b"x" * 4096).hexdigest())
        self.assertTrue(os.path.isfile(result["downloaded"]))
        self.assertTrue(result["verified"])
        self.assertTrue(urls[0].startswith("https://"), "升级包必须走 HTTPS")

    def test_missing_checksum_manifest_is_refused(self):
        with mock.patch.object(update.platform, "machine",
                               return_value="arm64"):
            err, urls = self._run(rel=release(with_sums=False))
        self.assertIsInstance(err, PanwebError, str(err))
        self.assertEqual(err.err_type, "checksum")
        self.assertEqual(urls, [], "拿不到 SHA256SUMS 就不能下载升级包")
        out = os.path.join(runtime.HOME_DIR, "update")
        self.assertEqual(os.listdir(out), [], "拒绝时不能留下临时文件")

    def test_size_mismatch_is_discarded(self):
        err, _ = self._run(payload=b"x" * 100)
        self.assertIsInstance(err, PanwebError, str(err))
        self.assertEqual(err.err_type, "checksum")
        out = os.path.join(runtime.HOME_DIR, "update")
        self.assertEqual(os.listdir(out), [], "半截包不能留在本机")

    def test_plain_http_asset_is_refused(self):
        bad = release()
        bad["assets"][0]["browser_download_url"] = "http://dl.test/a.dmg"
        err, urls = self._run(rel=bad)
        self.assertIsInstance(err, PanwebError, str(err))
        self.assertEqual(err.err_type, "not_found")
        self.assertEqual(urls, [], "http 地址不能出现在下载里")

    def test_no_newer_release_does_not_download(self):
        tag = "v%s" % runtime.PANWEB_VERSION
        result, urls = self._run(rel=release(tag=tag))
        self.assertNotIsInstance(result, PanwebError, str(result))
        self.assertIsNone(result["downloaded"])
        self.assertEqual(urls, [])

    def test_checksum_mismatch_is_discarded(self):
        rel = release()
        rel["assets"].append({
            "name": "SHA256SUMS", "browser_download_url":
            "https://dl.test/SHA256SUMS", "size": 100})
        with mock.patch.object(update.platform, "machine",
                               return_value="arm64"):
            err, urls = self._run(
                rel=rel, sums="%s  panweb-9.9.9-arm64.dmg\n" % ("0" * 64))
        self.assertIsInstance(err, PanwebError, str(err))
        self.assertEqual(err.err_type, "checksum")
        self.assertIn("SHA256SUMS", urls[0])
        out = os.path.join(runtime.HOME_DIR, "update")
        self.assertEqual(os.listdir(out), [], "校验失败不能留下安装包")

    def test_checksum_match_is_reported_verified(self):
        rel = release()
        rel["assets"].append({
            "name": "SHA256SUMS", "browser_download_url":
            "https://dl.test/SHA256SUMS", "size": 100})
        digest = hashlib.sha256(b"x" * 4096).hexdigest()
        with mock.patch.object(update.platform, "machine",
                               return_value="arm64"):
            result, _ = self._run(
                rel=rel, sums="%s  panweb-9.9.9-arm64.dmg\n" % digest)
        self.assertNotIsInstance(result, PanwebError, str(result))
        self.assertTrue(result["verified"])
        self.assertEqual(result["sha256"], digest)

    def test_download_failure_leaves_no_part_file(self):
        err, _ = self._run(payload=urllib.error.URLError("断了"))
        self.assertIsInstance(err, PanwebError, str(err))
        self.assertEqual(err.err_type, "network")
        out = os.path.join(runtime.HOME_DIR, "update")
        self.assertEqual(os.listdir(out), [], "下载中断不能留下 .part")

    def test_mid_download_failure_removes_part_file(self):
        err, _ = self._run(resp=BrokenResp(b"x" * 4096))
        self.assertIsInstance(err, PanwebError, str(err))
        self.assertEqual(err.err_type, "network")
        out = os.path.join(runtime.HOME_DIR, "update")
        self.assertEqual(os.listdir(out), [], "读到一半断掉也要清掉 .part")


class ShaTests(unittest.TestCase):
    def test_digest_of_known_bytes(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"panweb")
            path = f.name
        self.addCleanup(os.unlink, path)
        self.assertEqual(update.sha256_of(path),
                         hashlib.sha256(b"panweb").hexdigest())


if __name__ == "__main__":
    unittest.main()
