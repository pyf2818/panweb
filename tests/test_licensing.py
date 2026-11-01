import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from helpers import ROOT, temp_home
from panweb import licensing, runtime, store
from panweb.errors import PanwebError


class LicensingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.mkdtemp(prefix="panweb-keys-")
        tool = str(ROOT / "tools" / "license_tool.py")
        subprocess.run([sys.executable, tool, "keygen", "--out", cls.keys],
                       check=True, capture_output=True, text=True)
        cls.pub = os.path.join(cls.keys, "public.pem")
        cls.key_file = os.path.join(cls.keys, "license.key")
        subprocess.run([sys.executable, tool, "issue",
                        "--private-key", os.path.join(cls.keys, "private.pem"),
                        "--license-id", "PW-TEST-1",
                        "--buyer", "test@example.com",
                        "--devices", "2",
                        "--updates-days", "365",
                        "--out", cls.key_file],
                       check=True, capture_output=True, text=True)
        with open(cls.key_file, "r", encoding="ascii") as f:
            cls.key = f.read().strip()
        cls.key_no_updates = os.path.join(cls.keys, "license-noupdate.key")
        subprocess.run([sys.executable, tool, "issue",
                        "--private-key", os.path.join(cls.keys, "private.pem"),
                        "--license-id", "PW-TEST-2",
                        "--updates-days", "0",
                        "--out", cls.key_no_updates],
                       check=True, capture_output=True, text=True)
        with open(cls.key_no_updates, "r", encoding="ascii") as f:
            cls.key_no_updates = f.read().strip()
        cls.saved_env = {k: os.environ.get(k) for k in
                         ("PANWEB_LICENSE_PUBKEY", "PANWEB_MACHINE_ID",
                          "PANWEB_LICENSE_OFF")}
        os.environ["PANWEB_LICENSE_PUBKEY"] = cls.pub
        os.environ["PANWEB_MACHINE_ID"] = "machine-A"
        os.environ.pop("PANWEB_LICENSE_OFF", None)

    @classmethod
    def tearDownClass(cls):
        for key, value in cls.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(cls.keys, ignore_errors=True)

    def test_dev_mode_without_public_key(self):
        with temp_home("panweb-lic-dev-"):
            with mock.patch.object(licensing, "public_key_pem",
                                   return_value=None):
                status = licensing.license_status()
            self.assertEqual(status["mode"], "development")
            self.assertTrue(status["can_publish"])
            self.assertFalse(status["activation_required"])

    def test_trial_starts_then_expires(self):
        with temp_home("panweb-lic-trial-"):
            status = licensing.license_status()
            self.assertEqual(status["mode"], "trial")
            self.assertTrue(status["can_publish"])
            self.assertTrue(os.path.isfile(runtime.LICENSE_FILE))
            with open(runtime.LICENSE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            data["trial_started"] = time.time() - 15 * 86400
            store.save_json(runtime.LICENSE_FILE, data)
            status = licensing.license_status()
            self.assertEqual(status["mode"], "expired")
            self.assertFalse(status["can_publish"])
            with self.assertRaises(PanwebError) as ctx:
                licensing.require_publish_license()
            self.assertEqual(ctx.exception.exit_code, 10)
            self.assertEqual(ctx.exception.err_type, "license_required")

    def test_activate_and_machine_binding(self):
        with temp_home("panweb-lic-active-"):
            status = licensing.activate_license(self.key)
            self.assertEqual(status["mode"], "active")
            self.assertTrue(status["can_publish"])
            self.assertEqual(status["license_id"], "PW-TEST-1")
            self.assertEqual(status["devices"], 2)
            self.assertTrue(status["updates_active"])
            os.environ["PANWEB_MACHINE_ID"] = "machine-B"
            try:
                status = licensing.license_status()
                self.assertEqual(status["mode"], "invalid")
                self.assertFalse(status["can_publish"])
            finally:
                os.environ["PANWEB_MACHINE_ID"] = "machine-A"
            result = licensing.deactivate_license()
            self.assertTrue(result["removed"])

    def test_updates_entitlement_does_not_block_running(self):
        with temp_home("panweb-lic-upd-"):
            status = licensing.activate_license(self.key_no_updates)
            self.assertEqual(status["mode"], "active")
            self.assertFalse(status["updates_active"])
            self.assertTrue(status["can_publish"])

    def test_tampered_key_is_rejected(self):
        with temp_home("panweb-lic-bad-"):
            parts = self.key.split(".")
            payload = parts[1]
            idx = len(payload) // 2
            replacement = "A" if payload[idx] != "A" else "B"
            bad = parts[0] + "." + payload[:idx] + replacement + payload[idx + 1:] \
                + "." + parts[2]
            with self.assertRaises(PanwebError) as ctx:
                licensing.activate_license(bad)
            self.assertEqual(ctx.exception.err_type, "invalid_license")

    def test_no_public_key_rejects_activation(self):
        with temp_home("panweb-lic-nokey-"):
            with mock.patch.object(licensing, "public_key_pem",
                                   return_value=None):
                with self.assertRaises(PanwebError) as ctx:
                    licensing.activate_license(self.key)
            self.assertEqual(ctx.exception.err_type, "license_not_configured")


if __name__ == "__main__":
    unittest.main()
