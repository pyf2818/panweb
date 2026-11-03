"""macOS 签名与公证：配了身份就真签，没配就退回 ad-hoc 并说清楚差别。

买断分发要过 Gatekeeper，只有 Developer ID 签名 + 苹果公证（notarization）才做得到；
ad-hoc 签名只是少弹一次窗。凭据全部走环境变量，绝不写进仓库或产物：

  PANWEB_SIGN_IDENTITY      Developer ID Application: 名字 (TEAMID)
  PANWEB_NOTARY_PROFILE     xcrun notarytool store-credentials 存的 profile 名
  或用 App Store Connect API 密钥三件套：
  PANWEB_APPLE_KEY_ID / PANWEB_APPLE_ISSUER_ID / PANWEB_APPLE_P8（.p8 路径）
"""
import os
import subprocess
import sys
import tempfile

ENTITLEMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <!-- 我们要 exec 第三方 cloudflared 二进制，也要跑 Python 脚本：
       开了 hardened runtime 就必须放宽库校验，否则子进程起不来 -->
  <key>com.apple.security.cs.disable-library-validation</key><true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
</dict></plist>
"""


def identity():
    return (os.environ.get("PANWEB_SIGN_IDENTITY") or "").strip()


def notary_args():
    """公证凭据：优先 keychain profile，其次 API 密钥三件套；都没有返回 None。"""
    profile = (os.environ.get("PANWEB_NOTARY_PROFILE") or "").strip()
    if profile:
        return ["--keychain-profile", profile]
    keys = [os.environ.get(k, "").strip() for k in
            ("PANWEB_APPLE_KEY_ID", "PANWEB_APPLE_ISSUER_ID", "PANWEB_APPLE_P8")]
    if all(keys) and os.path.isfile(keys[2]):
        return ["--key", keys[2], "--key-id", keys[0], "--issuer", keys[1]]
    return None


def _run(argv, timeout=600):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return proc.returncode == 0, (proc.stderr or proc.stdout or "").strip()


def _entitlements_file():
    fd, path = tempfile.mkstemp(prefix="panweb-ent-", suffix=".plist")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(ENTITLEMENTS)
    return path


def sign(target, sign_id=None):
    """签名一个 .app 或 .dmg。没配身份时用 ad-hoc（-），并如实回报。"""
    sign_id = sign_id or identity()
    adhoc = not sign_id
    who = "-" if adhoc else sign_id
    steps = []
    if not adhoc and target.endswith(".app"):
        # 先里后外：--deep 已被苹果废弃，且我们的包结构本来就很简单
        inner = [os.path.join(target, "Contents", "MacOS", "panweb-launcher"),
                 os.path.join(target, "Contents", "Resources", "cloudflared")]
        for path in inner:
            if os.path.exists(path):
                ok, err = _run(["codesign", "--force", "--timestamp",
                                "--options", "runtime", "-s", who, path])
                steps.append({"target": os.path.basename(path), "ok": ok,
                              "error": err or None})
                if not ok:
                    return {"signed": False, "identity": who, "ad_hoc": adhoc,
                            "steps": steps,
                            "message": "内层签名失败，外层不再签"}
    argv = ["codesign", "--force", "--timestamp", "-s", who]
    ent = None
    if not adhoc:
        argv += ["--options", "runtime"]
        ent = _entitlements_file()
        argv += ["--entitlements", ent]
    argv.append(target)
    ok, err = _run(argv)
    if ent:
        try:
            os.remove(ent)
        except OSError:
            pass
    if not ok and adhoc:
        # ad-hoc 失败（比如没有 codesign）不能把整个构建搞崩，如实记下来
        return {"signed": False, "identity": who, "ad_hoc": True,
                "steps": steps, "message": err[-400:]}
    return {"signed": ok, "identity": who, "ad_hoc": adhoc, "steps": steps,
            "message": None if ok else err[-400:]}


def describe(result):
    if result.get("signed") and not result.get("ad_hoc"):
        return "已用 Developer ID 签名"
    if result.get("signed"):
        return "ad-hoc 签名（未走苹果公证，用户首次打开需右键→打开）"
    return "签名失败：%s" % result.get("message")


def notarize(target):
    """提交公证并等待结果，成功后 staple 装订。没配凭据就跳过并说明。"""
    args = notary_args()
    if not args:
        return {"notarized": False,
                "message": "未配置 PANWEB_NOTARY_PROFILE / PANWEB_APPLE_*，跳过公证"}
    if sys.platform != "darwin":
        return {"notarized": False, "message": "公证只能在 macOS 上做"}
    ok, out = _run(["xcrun", "notarytool", "submit", target, "--wait",
                    "--output-format", "json"] + args, timeout=1800)
    if not ok:
        return {"notarized": False, "message": "公证提交失败：%s" % out[-400:]}
    ok, out = _run(["xcrun", "spctl", "--assess", "-vvv", "--type", "open",
                    target], timeout=120)
    verdict = out[-400:]
    ok2, out2 = _run(["xcrun", "stapler", "staple", target], timeout=120)
    return {"notarized": ok2, "assess": verdict,
            "message": None if ok2 else "装订失败：%s" % out2[-400:]}
