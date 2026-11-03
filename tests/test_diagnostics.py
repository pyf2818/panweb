"""诊断包：该有的要有，凭据一点都不能有。"""
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from helpers import temp_home
from panweb import diagnostics, pins, runtime, store, upstream

SECRETS = ("SuperSecretToken123", "cf-token-abcdefg", "BearerSecret9",
           "hunter2hunter2", "8668")


def seed_home():
    """造一个"什么凭据都有"的数据目录，看包出去之后还剩什么。"""
    store.save_state([{
        "id": "e1", "name": "演示", "kind": "port", "target": 3000,
        "url": "https://a-b-c.trycloudflare.com", "proxy_port": 7001,
        "share_token": "SuperSecretToken123",
        "check": {"verdict": "ok", "signals": []},
    }])
    store.save_domain({"domain": "example.com", "api_token": "cf-token-abcdefg",
                       "zone_id": "zone123", "local_port": 7002})
    meta = store.load_meta()
    meta["password_hint"] = "hunter2hunter2"
    store.save_meta(meta)
    with open(os.path.join(runtime.LOG_DIR, "e1.log"), "w",
              encoding="utf-8") as f:
        # 日志正文没有结构化字段，得靠形态扫描；这几行是真实会出现的泄露形态
        f.write("请求 /?share=SuperSecretToken123\n")
        f.write("Authorization: Bearer BearerSecret9\n")
        f.write("panweb_auth=deadbeefcafebabe\n")
        for i in range(4000):
            f.write("日志行 %d\n" % i)
    auth = upstream.auth_file_path("e1")
    with open(auth, "w", encoding="utf-8") as f:
        json.dump({"kind": "bearer", "token": "BearerSecret9"}, f)
    os.chmod(auth, 0o600)
    pins.write_pin("e1", "8668")


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.ctx = temp_home("panweb-report-")
        self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        store.ensure_private_dirs()
        seed_home()
        self.result = diagnostics.core_report()
        with zipfile.ZipFile(self.result["zip"]) as z:
            self.names = [n.split("/", 1)[-1] for n in z.namelist()]
            self.bodies = dict((n.split("/", 1)[-1],
                                z.read(n).decode("utf-8"))
                               for n in z.namelist())

    def test_zip_contains_the_useful_parts(self):
        for want in ("report.txt", "meta.json", "doctor.json", "system.json",
                     "state.json", "activity.json", "domain.json",
                     "prefs.json", "license.json", "logs/e1.log"):
            self.assertIn(want, self.names, "诊断包少了 %s" % want)
        self.assertGreater(self.result["size"], 1000)
        self.assertEqual(json.loads(self.bodies["meta.json"])["panweb_version"],
                         runtime.PANWEB_VERSION)
        self.assertIn("演示", self.bodies["report.txt"])

    def test_credentials_never_enter_the_package(self):
        blob = "\n".join(self.bodies.values())
        for secret in SECRETS:
            self.assertNotIn(secret, blob, "凭据漏进诊断包：%s" % secret)
        self.assertEqual([n for n in self.names if n.startswith(
            ("secrets", "pins", "visits"))], [], "凭据目录不许进包")
        state = json.loads(self.bodies["state.json"])
        self.assertIn("已省略", state[0]["share_token"])

    def test_log_text_secrets_are_scrubbed(self):
        log = self.bodies["logs/e1.log"]
        self.assertIn("已省略", log)
        self.assertNotIn("deadbeefcafebabe", log, "panweb_auth 会话不能进包")
        self.assertIn("日志行 3999", log, "脱敏不能把整段日志吞掉")

    def test_logs_are_tailed_not_dumped(self):
        with mock.patch.object(diagnostics, "MAX_LOG_BYTES", 2000):
            got = diagnostics.core_report()
        with zipfile.ZipFile(got["zip"]) as z:
            body = z.read([n for n in z.namelist()
                           if n.endswith("logs/e1.log")][0]).decode("utf-8")
        self.assertIn("只保留尾部", body)
        self.assertIn("日志行 3999", body)
        self.assertNotIn("日志行 1\n", body)

    def test_self_audit_blocks_an_unmasked_leak(self):
        """脱敏被改坏时宁可不出包，也不能把凭据打出去。"""
        original = diagnostics.clean
        diagnostics.clean = lambda obj: obj
        self.addCleanup(setattr, diagnostics, "clean", original)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError) as e:
                diagnostics.core_report(tmp)
            self.assertIn("没脱敏", str(e.exception))
            self.assertEqual(os.listdir(tmp), [], "审查失败要删掉坏包")

    def test_self_audit_blocks_unscrubbed_log(self):
        """日志脱敏被绕过时也要拒绝出包，不能只依赖 JSON 字段检查。"""
        original = diagnostics._scrub_text
        diagnostics._scrub_text = lambda text: text
        self.addCleanup(setattr, diagnostics, "_scrub_text", original)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AssertionError) as e:
                diagnostics.core_report(tmp)
            self.assertIn("未脱敏凭据", str(e.exception))
            self.assertEqual(os.listdir(tmp), [], "审查失败要删掉坏包")

    def test_out_dir_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            got = diagnostics.core_report(tmp)
            self.assertTrue(got["zip"].startswith(tmp))
            self.assertTrue(got["zip"].endswith(".zip"))
            self.addCleanup(shutil.rmtree, tmp, True)

    def test_report_works_on_a_bare_install(self):
        """什么都没配过的机器也要出得来包：不能因为缺文件/缺许可而炸。"""
        store.save_state([])
        shutil.rmtree(runtime.LOG_DIR, ignore_errors=True)
        try:
            os.remove(runtime.DOMAIN_FILE)
        except OSError:
            pass
        got = diagnostics.core_report()
        self.assertTrue(os.path.isfile(got["zip"]))


if __name__ == "__main__":
    unittest.main()
