import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

from helpers import ROOT

SCRIPT = ROOT / "panweb"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="panweb-cli-")
        self.env = os.environ.copy()
        self.env["HOME"] = self.home
        self.env["PANWEB_CLOUDFLARED"] = shutil.which("false") or "/bin/false"
        # 清掉外部可能带进来的 PANWEB_HOME，doctor 才会按临时 HOME 推导路径；
        # 否则开发机上设置的 PANWEB_HOME 会穿透到子进程，污染真实状态目录。
        self.env.pop("PANWEB_HOME", None)
        self.env.pop("PANWEB_LICENSE_PUBKEY", None)
        self.env.pop("PANWEB_MACHINE_ID", None)
        self.env.pop("PANWEB_LICENSE_OFF", None)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True, env=self.env,
                              timeout=30)

    def test_json_error_contract(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        out = self.run_cli("publish", str(port), "--json")
        self.assertEqual(out.returncode, 8)
        payload = json.loads(out.stderr.strip().splitlines()[-1])
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["type"], "port_not_serving")
        self.assertEqual(out.stdout.strip(), "")

    def test_unsafe_folder_is_rejected(self):
        out = self.run_cli("pages", "/", "--json")
        self.assertEqual(out.returncode, 2)
        payload = json.loads(out.stderr.strip().splitlines()[-1])
        self.assertEqual(payload["error"]["type"], "unsafe_folder")

    def test_stop_all_is_idempotent(self):
        out = self.run_cli("stop", "all", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["stopped"], [])

    def test_version(self):
        out = self.run_cli("--version")
        self.assertEqual(out.returncode, 0)
        self.assertIn("1.6.0", out.stdout)

    def test_help_lists_commands(self):
        out = self.run_cli("--help")
        self.assertEqual(out.returncode, 0)
        for cmd in ("publish", "pages", "run", "list", "stop", "ui",
                    "license", "check", "compat", "report", "update"):
            self.assertIn(cmd, out.stdout)

    def test_license_status_development(self):
        out = self.run_cli("license", "status", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["mode"], "development")
        self.assertTrue(payload["data"]["can_publish"])

    def test_doctor_json_state_dir(self):
        out = self.run_cli("doctor", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        payload = json.loads(out.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["data"]["state_dir"].startswith(self.home))


class CompatCliTests(unittest.TestCase):
    """compat / check：命令行改得动设置，但密钥不会从任何输出里漏出来。"""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="panweb-compat-cli-")
        self.state_dir = os.path.join(self.home, ".panweb")
        os.makedirs(os.path.join(self.state_dir, "secrets"), exist_ok=True)
        self.seed({"id": "cli1", "name": "命令行测试", "kind": "port",
                   "target": 9, "proxy_port": 17788,
                   "url": "http://127.0.0.1:9"})
        self.env = os.environ.copy()
        self.env["HOME"] = self.home
        self.env["PANWEB_HOME"] = self.state_dir
        self.env.pop("PANWEB_LICENSE_PUBKEY", None)

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def seed(self, entry):
        with open(os.path.join(self.state_dir, "state.json"), "w",
                  encoding="utf-8") as f:
            json.dump([entry], f)

    def read_state(self):
        with open(os.path.join(self.state_dir, "state.json"),
                  encoding="utf-8") as f:
            return json.load(f)[0]

    def run_cli(self, *args, **kw):
        text = kw.pop("text_input", None)
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True, env=self.env,
                              input=text, timeout=60)

    def test_missing_entry_is_not_found(self):
        out = self.run_cli("compat", "nope", "--json")
        self.assertEqual(out.returncode, 2)
        payload = json.loads(out.stderr.strip().splitlines()[-1])
        self.assertEqual(payload["error"]["type"], "not_found")

    def test_bearer_token_stays_out_of_stdout(self):
        out = self.run_cli("compat", "cli1", "--bearer", "sup3r-s3cret",
                           "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)["data"]
        self.assertEqual(data["auth"]["kind"], "bearer")
        self.assertNotIn("sup3r-s3cret", out.stdout)
        self.assertEqual(self.read_state()["auth_kind"], "bearer")
        secret = os.path.join(self.state_dir, "secrets", "cli1.auth.json")
        with open(secret, encoding="utf-8") as f:
            self.assertIn("sup3r-s3cret", f.read())
        self.assertEqual(os.stat(secret).st_mode & 0o777, 0o600)

    def test_header_name_is_shown_but_value_is_not(self):
        out = self.run_cli("compat", "cli1", "--header", "X-Api-Key",
                           "--value", "k-9999", "--json")
        data = json.loads(out.stdout)["data"]
        self.assertEqual(data["auth"]["name"], "X-Api-Key")
        self.assertNotIn("k-9999", out.stdout)

    def test_host_mode_is_persisted(self):
        out = self.run_cli("compat", "cli1", "--host-mode", "tunnel", "--json")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["data"]["host_mode"], "tunnel")
        self.assertEqual(self.read_state()["host_mode"], "tunnel")

    def test_clear_auth(self):
        self.run_cli("compat", "cli1", "--bearer", "tk", "--json")
        out = self.run_cli("compat", "cli1", "--clear-auth", "--json")
        self.assertIsNone(json.loads(out.stdout)["data"]["auth"])
        self.assertNotIn("auth_kind", self.read_state())

    def test_auth_stdin_reads_the_secret_off_a_pipe(self):
        out = self.run_cli("compat", "cli1", "--auth-stdin", "--json",
                           text_input="bearer\nsk-from-stdin\n")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout)["data"]["auth"]["kind"], "bearer")
        secret = os.path.join(self.state_dir, "secrets", "cli1.auth.json")
        with open(secret, encoding="utf-8") as f:
            self.assertIn("sk-from-stdin", f.read())

    def test_auth_stdin_conflicts_with_argv(self):
        out = self.run_cli("compat", "cli1", "--auth-stdin", "--bearer", "x",
                           "--json", text_input="bearer\ny\n")
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertEqual(json.loads(out.stderr.strip().splitlines()[-1])
                         ["error"]["type"], "invalid_argument")
        self.assertFalse(os.path.exists(os.path.join(
            self.state_dir, "secrets", "cli1.auth.json")))

    def test_direct_publish_refuses_settings_it_cannot_apply(self):
        self.seed({"id": "cli2", "name": "直连", "kind": "port",
                   "target": 9, "url": "http://127.0.0.1:9"})
        read = self.run_cli("compat", "cli2", "--json")
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertFalse(json.loads(read.stdout)["data"]["proxied"])
        out = self.run_cli("compat", "cli2", "--bearer", "tk", "--json")
        self.assertEqual(out.returncode, 3, out.stderr)
        payload = json.loads(out.stderr.strip().splitlines()[-1])
        self.assertEqual(payload["error"]["type"], "not_supported")
        self.assertIn("直连", payload["error"]["message"])
        self.assertFalse(os.path.exists(os.path.join(
            self.state_dir, "secrets", "cli2.auth.json")))

    def test_check_reports_blocked_and_exits_nonzero(self):
        out = self.run_cli("check", "cli1", "--json")
        self.assertEqual(out.returncode, 1, out.stdout)
        data = json.loads(out.stdout)["data"]
        self.assertEqual(data["verdict"], "blocked")
        self.assertIn("unreachable", [s["code"] for s in data["signals"]])

    def test_check_no_fix_leaves_host_mode_alone(self):
        out = self.run_cli("check", "cli1", "--no-fix", "--json")
        self.assertEqual(out.returncode, 1, out.stdout)
        self.assertNotIn("host_mode", self.read_state())


if __name__ == "__main__":
    unittest.main()
