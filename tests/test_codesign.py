"""签名与公证：没配身份要能退回 ad-hoc，配了就要按"先里后外"签到位。"""
import os
import tempfile
import unittest
from unittest import mock

import helpers  # noqa: F401  导入它顺带把 src/ 放进 sys.path
from panweb import codesign


class Recorder:
    """假命令执行器：只记 argv，不真调 codesign/notarytool。"""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or ()

    def __call__(self, argv, timeout=600):
        joined = " ".join(argv)
        self.calls.append(argv)
        if "--entitlements" in argv:        # 临时文件在签完就被删，趁还在读一份
            path = argv[argv.index("--entitlements") + 1]
            try:
                with open(path, encoding="utf-8") as f:
                    self.entitlements = f.read()
            except OSError:
                self.entitlements = ""
        if any(f in joined for f in self.fail_on):
            return False, "boom: %s" % joined[:60]
        return True, ""


def fake_app():
    tmp = tempfile.mkdtemp(prefix="panweb-app-")
    app = os.path.join(tmp, "panweb.app")
    os.makedirs(os.path.join(app, "Contents", "MacOS"))
    os.makedirs(os.path.join(app, "Contents", "Resources"))
    with open(os.path.join(app, "Contents", "MacOS", "panweb-launcher"),
              "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\necho hi\n")
    with open(os.path.join(app, "Contents", "Resources", "cloudflared"),
              "w", encoding="utf-8") as f:
        f.write("binary\n")
    return app


class SignTests(unittest.TestCase):
    def tearDown(self):
        for key in ("PANWEB_SIGN_IDENTITY",):
            os.environ.pop(key, None)

    def test_adhoc_when_no_identity(self):
        rec = Recorder()
        with mock.patch.object(codesign, "_run", rec):
            out = codesign.sign("/tmp/panweb.app")
        self.assertTrue(out["signed"])
        self.assertTrue(out["ad_hoc"])
        self.assertEqual(out["identity"], "-")
        self.assertIn("-s", rec.calls[0])
        self.assertEqual(rec.calls[0][rec.calls[0].index("-s") + 1], "-")
        self.assertNotIn("--options", rec.calls[0], "ad-hoc 不该开 hardened runtime")
        self.assertEqual(codesign.describe(out),
                         "ad-hoc 签名（未走苹果公证，用户首次打开需右键→打开）")

    def test_developer_id_signs_inside_out(self):
        app = fake_app()
        os.environ["PANWEB_SIGN_IDENTITY"] = "Developer ID Application: Anlan (T1)"
        rec = Recorder()
        with mock.patch.object(codesign, "_run", rec):
            out = codesign.sign(app)
        self.assertTrue(out["signed"])
        self.assertFalse(out["ad_hoc"])
        self.assertEqual(len(rec.calls), 3, "两个内层 + 一个外层")
        self.assertTrue(rec.calls[0][-1].endswith("panweb-launcher"))
        self.assertTrue(rec.calls[1][-1].endswith("cloudflared"))
        outer = rec.calls[2]
        self.assertEqual(outer[-1], app)
        self.assertIn("--options", outer)
        self.assertIn("runtime", outer)
        self.assertIn("--entitlements", outer)
        self.assertIn("--timestamp", outer)
        self.assertEqual(outer[outer.index("-s") + 1],
                         "Developer ID Application: Anlan (T1)")
        ent = outer[outer.index("--entitlements") + 1]
        self.assertIn("disable-library-validation", rec.entitlements,
                      "要 exec 第三方 cloudflared，库校验必须放宽")
        self.assertFalse(os.path.exists(ent), "临时 entitlements 文件要收掉")
        self.assertIn("Developer ID", codesign.describe(out))

    def test_inner_failure_stops_before_the_outer_signing(self):
        app = fake_app()
        os.environ["PANWEB_SIGN_IDENTITY"] = "Developer ID Application: X (T2)"
        rec = Recorder(fail_on=("cloudflared",))
        with mock.patch.object(codesign, "_run", rec):
            out = codesign.sign(app)
        self.assertFalse(out["signed"])
        self.assertEqual(len(rec.calls), 2, "内层失败就不该再签外层")
        self.assertIn("内层签名失败", out["message"])

    def test_adhoc_failure_does_not_explode(self):
        rec = Recorder(fail_on=("codesign",))
        with mock.patch.object(codesign, "_run", rec):
            out = codesign.sign("/tmp/whatever.app")
        self.assertFalse(out["signed"])
        self.assertTrue(out["ad_hoc"])
        self.assertIn("签名失败", codesign.describe(out))

    def test_dmg_skips_inner_pass(self):
        rec = Recorder()
        with mock.patch.object(codesign, "_run", rec):
            codesign.sign("/tmp/panweb.dmg", sign_id="Developer ID: X")
        self.assertEqual(len(rec.calls), 1, "dmg 只签自己")


class NotaryTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in
                      ("PANWEB_NOTARY_PROFILE", "PANWEB_APPLE_KEY_ID",
                       "PANWEB_APPLE_ISSUER_ID", "PANWEB_APPLE_P8")}
        for k in self.saved:
            os.environ.pop(k, None)
        self.addCleanup(lambda: [os.environ.__setitem__(k, v)
                                 for k, v in self.saved.items() if v])

    def test_no_credentials_means_skip(self):
        self.assertIsNone(codesign.notary_args())
        out = codesign.notarize("/tmp/panweb.dmg")
        self.assertFalse(out["notarized"])
        self.assertIn("跳过公证", out["message"])

    def test_keychain_profile_preferred(self):
        os.environ["PANWEB_NOTARY_PROFILE"] = "panweb-notary"
        self.assertEqual(codesign.notary_args(),
                         ["--keychain-profile", "panweb-notary"])

    def test_api_key_triple(self):
        with tempfile.NamedTemporaryFile(suffix=".p8") as key:
            os.environ.update({"PANWEB_APPLE_KEY_ID": "K1",
                               "PANWEB_APPLE_ISSUER_ID": "I1",
                               "PANWEB_APPLE_P8": key.name})
            args = codesign.notary_args()
        self.assertEqual(args[:2], ["--key", key.name])
        self.assertIn("K1", args)
        self.assertIn("I1", args)

    def test_incomplete_api_key_is_ignored(self):
        os.environ["PANWEB_APPLE_KEY_ID"] = "K1"
        self.assertIsNone(codesign.notary_args())

    def test_submit_wait_staple_sequence(self):
        os.environ["PANWEB_NOTARY_PROFILE"] = "p"
        rec = Recorder()
        with mock.patch.object(codesign, "_run", rec), \
             mock.patch.object(codesign.sys, "platform", "darwin"):
            out = codesign.notarize("/tmp/panweb.dmg")
        self.assertTrue(out["notarized"])
        verbs = [c[1] for c in rec.calls]
        self.assertEqual(verbs, ["notarytool", "spctl", "stapler"])
        self.assertIn("--wait", rec.calls[0])


if __name__ == "__main__":
    unittest.main()
