#!/usr/bin/env python3
"""panweb 离线许可签发工具（卖家侧，勿随发行版分发私钥）。

用法：
  python3 tools/license_tool.py keygen --out keys
  python3 tools/license_tool.py issue --private-key keys/private.pem \
      --buyer alice@example.com --license-id PW-2026-0001
  python3 tools/license_tool.py verify --key PWV1.xxx --public-key keys/public.pem

发行版构建：
  cp keys/public.pem assets/license_public_key.pem
  python3 tools/build_ui.py
  panweb install-app
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

KEY_PREFIX = "PWV1"


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def run(cmd, **kwargs):
    out = subprocess.run(cmd, capture_output=True, **kwargs)
    if out.returncode != 0:
        raise SystemExit((out.stderr or out.stdout or b"").decode(
            "utf-8", "replace")[:800])
    return out


def cmd_keygen(args):
    os.makedirs(args.out, exist_ok=True)
    private = os.path.join(args.out, "private.pem")
    public = os.path.join(args.out, "public.pem")
    if os.path.exists(private) and not args.force:
        raise SystemExit("私钥已存在：%s（加 --force 覆盖）" % private)
    run(["openssl", "genpkey", "-algorithm", "RSA",
         "-pkeyopt", "rsa_keygen_bits:%d" % args.bits, "-out", private])
    os.chmod(private, 0o600)
    run(["openssl", "pkey", "-in", private, "-pubout", "-out", public])
    print("✅ 已生成密钥：", file=sys.stderr)
    print("   私钥（保密）：%s" % private, file=sys.stderr)
    print("   公钥（内置）：%s" % public, file=sys.stderr)
    print("   下一步：cp %s assets/license_public_key.pem" % public,
          file=sys.stderr)


def cmd_issue(args):
    now = int(time.time())
    updates_until = (now + args.updates_days * 86400
                     if args.updates_days > 0 else 0)
    license_id = args.license_id or ("PW-" + uuid.uuid4().hex[:12].upper())
    payload = {
        "v": 1,
        "product": "panweb",
        "edition": args.edition,
        "license_id": license_id,
        "issued_at": now,
        "updates_until": updates_until,
        "devices": args.devices,
        "buyer": args.buyer or "",
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    payload_b64 = b64u(raw)
    signed = (KEY_PREFIX + "." + payload_b64).encode("ascii")
    sig = run(["openssl", "dgst", "-sha256", "-sign", args.private_key],
              input=signed).stdout
    key = KEY_PREFIX + "." + payload_b64 + "." + b64u(sig)
    if args.out:
        with open(args.out, "w", encoding="ascii") as f:
            f.write(key + "\n")
        print("✅ 已签发：%s" % args.out, file=sys.stderr)
        print("   许可编号：%s" % license_id, file=sys.stderr)
        print("   更新权益至：%s" % (
            time.strftime("%Y-%m-%d", time.localtime(updates_until))
            if updates_until else "无"), file=sys.stderr)
        print(key, file=sys.stderr)
    else:
        print(key)


def cmd_verify(args):
    from panweb.licensing import LicenseError, parse_public_key
    pem = args.public_key
    if os.path.isfile(pem):
        with open(pem, "r", encoding="utf-8") as f:
            pem = f.read()
    key = args.key
    if os.path.isfile(key):
        with open(key, "r", encoding="ascii") as f:
            key = f.read().strip()
    os.environ["PANWEB_LICENSE_PUBKEY"] = pem
    from panweb.licensing import verify_license_key
    try:
        payload = verify_license_key(key)
    except LicenseError as e:
        raise SystemExit("❌ %s" % e)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("✅ 签名有效", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="panweb 许可签发工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("keygen", help="生成 RSA 密钥对")
    p.add_argument("--out", default="keys", help="输出目录（默认 keys）")
    p.add_argument("--bits", type=int, default=2048)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_keygen)

    p = sub.add_parser("issue", help="签发许可密钥")
    p.add_argument("--private-key", required=True)
    p.add_argument("--license-id", default="")
    p.add_argument("--buyer", default="", help="买家标识（邮箱/订单号）")
    p.add_argument("--edition", default="pro")
    p.add_argument("--devices", type=int, default=2)
    p.add_argument("--updates-days", type=int, default=365,
                   help="更新权益天数（0=不含更新）")
    p.add_argument("--out", help="写入文件；省略则打印到 stdout")
    p.set_defaults(func=cmd_issue)

    p = sub.add_parser("verify", help="验证许可密钥")
    p.add_argument("--key", required=True)
    p.add_argument("--public-key", required=True)
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
