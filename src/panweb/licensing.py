"""买断制离线许可：试用、激活、机器绑定与更新权益。

许可密钥格式：PWV1.<base64url(payload)>.<base64url(signature)>
签名算法：RSA PKCS#1 v1.5 + SHA-256（公钥内置，无联网校验）。
未配置公钥的构建为开发模式，不限制功能；发行版由构建者注入公钥。
"""
import base64
import hashlib
import hmac
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import uuid

from . import runtime
from .errors import PanwebError
from .store import save_json, state_lock

PRODUCT = "panweb"
KEY_PREFIX = "PWV1"
TRIAL_DAYS = max(1, int(os.environ.get("PANWEB_TRIAL_DAYS", "14") or 14))
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
LICENSE_OFF = os.environ.get("PANWEB_LICENSE_OFF") == "1"
LICENSE_PUBKEY_PATH = "assets/license_public_key.pem"

_PUBKEY_CACHE = {}


class LicenseError(Exception):
    pass


def _pem_der(pem):
    m = re.search(r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----",
                  pem or "", re.S)
    if not m:
        raise LicenseError("公钥格式不正确")
    try:
        return base64.b64decode("".join(m.group(1).split()))
    except (ValueError, base64.binascii.Error):
        raise LicenseError("公钥无法解码")


def _tlv(data, pos=0):
    if pos + 2 > len(data):
        raise LicenseError("公钥 DER 不完整")
    tag = data[pos]
    pos += 1
    first = data[pos]
    pos += 1
    if first & 0x80:
        n = first & 0x7F
        if n == 0 or pos + n > len(data):
            raise LicenseError("公钥 DER 长度非法")
        length = int.from_bytes(data[pos:pos + n], "big")
        pos += n
    else:
        length = first
    if pos + length > len(data):
        raise LicenseError("公钥 DER 越界")
    return tag, data[pos:pos + length], pos + length


def parse_public_key(pem):
    """解析 SubjectPublicKeyInfo → (n, e)。"""
    cached = _PUBKEY_CACHE.get(pem)
    if cached:
        return cached
    der = _pem_der(pem)
    tag, seq, _ = _tlv(der, 0)
    if tag != 0x30:
        raise LicenseError("公钥不是 SEQUENCE")
    tag, _alg, pos = _tlv(seq, 0)
    if tag != 0x30:
        raise LicenseError("公钥缺少算法标识")
    tag, bits, pos = _tlv(seq, pos)
    if tag != 0x03 or not bits or bits[0] != 0:
        raise LicenseError("公钥 BIT STRING 非法")
    tag, rsa, _ = _tlv(bits[1:], 0)
    if tag != 0x30:
        raise LicenseError("公钥缺少 RSA 参数")
    tag, n_raw, pos = _tlv(rsa, 0)
    if tag != 0x02:
        raise LicenseError("公钥缺少模数")
    tag, e_raw, _ = _tlv(rsa, pos)
    if tag != 0x02:
        raise LicenseError("公钥缺少指数")
    n = int.from_bytes(n_raw, "big")
    e = int.from_bytes(e_raw, "big")
    if n.bit_length() < 1024 or e < 3:
        raise LicenseError("公钥强度不足")
    _PUBKEY_CACHE[pem] = (n, e)
    return n, e


def public_key_pem():
    raw = (os.environ.get("PANWEB_LICENSE_PUBKEY") or "").strip()
    if raw:
        if os.path.isfile(raw):
            try:
                with open(raw, "r", encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                return None
        elif "BEGIN PUBLIC KEY" not in raw and len(raw) > 100:
            raw = ("-----BEGIN PUBLIC KEY-----\n" + raw
                   + "\n-----END PUBLIC KEY-----")
    else:
        data = runtime.read_resource(LICENSE_PUBKEY_PATH)
        if not data:
            return None
        raw = data.decode("utf-8", "replace")
    try:
        parse_public_key(raw)
        return raw
    except LicenseError:
        return None


def machine_id():
    """硬件/系统指纹的截断哈希；不上传、不保存原始标识。"""
    env = os.environ.get("PANWEB_MACHINE_ID")
    if env:
        return hashlib.sha256(("env:" + env).encode()).hexdigest()[:24]
    raw = ""
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5).stdout
            m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            if m:
                raw = m.group(1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not raw:
        raw = "%s|%s|%s" % (platform.system(), platform.machine(),
                            uuid.getnode())
    import getpass
    raw += "|" + (getpass.getuser() or "")
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:24]


def _b64d(text):
    text = text.strip()
    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + pad)
    except (ValueError, base64.binascii.Error):
        raise LicenseError("许可密钥编码不正确")


def verify_license_key(key):
    """验证签名并返回 payload；失败抛 LicenseError。"""
    pem = public_key_pem()
    if not pem:
        raise LicenseError("此构建未配置许可公钥")
    text = (key or "").strip()
    if text.startswith(KEY_PREFIX + "."):
        text = text[len(KEY_PREFIX) + 1:]
    if text.count(".") != 1:
        raise LicenseError("许可密钥格式不正确")
    payload_b64, sig_b64 = text.split(".", 1)
    try:
        payload_bytes = _b64d(payload_b64)
        sig = _b64d(sig_b64)
    except LicenseError:
        raise
    n, e = parse_public_key(pem)
    k = (n.bit_length() + 7) // 8
    if len(sig) > k:
        raise LicenseError("许可签名长度不正确")
    digest = hashlib.sha256(
        (KEY_PREFIX + "." + payload_b64).encode("ascii")).digest()
    try:
        em = pow(int.from_bytes(sig, "big"), e, n).to_bytes(k, "big")
    except (ValueError, OverflowError):
        raise LicenseError("许可签名无效")
    pad_len = k - 3 - len(SHA256_DIGEST_INFO) - len(digest)
    if pad_len < 8:
        raise LicenseError("许可公钥长度不足")
    expected = (b"\x00\x01" + b"\xff" * pad_len + b"\x00"
                + SHA256_DIGEST_INFO + digest)
    if not hmac.compare_digest(em, expected):
        raise LicenseError("许可签名校验失败")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise LicenseError("许可内容不是合法 JSON")
    if not isinstance(payload, dict):
        raise LicenseError("许可内容格式不正确")
    if payload.get("product") != PRODUCT or payload.get("v") != 1:
        raise LicenseError("这不是 panweb 的许可密钥")
    if not payload.get("license_id"):
        raise LicenseError("许可缺少编号")
    return payload


def _load_file():
    try:
        with open(runtime.LICENSE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_file(data):
    with state_lock():
        save_json(runtime.LICENSE_FILE, data)


def _fmt_date(ts):
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(ts)))
    except (TypeError, ValueError, OverflowError):
        return ""


def _dev_status():
    return {"mode": "development", "configured": False, "can_publish": True,
            "activation_required": False, "edition": None, "license_id": None,
            "machine": machine_id(), "devices": None,
            "updates_until": None, "updates_until_text": "",
            "updates_active": True, "trial_ends": None,
            "trial_ends_text": "", "trial_days_left": None,
            "message": "开发版 · 未启用许可校验",
            "hint": "发行构建注入公钥后自动启用试用与激活"}


def license_status(start_trial=True):
    """返回许可状态。配置公钥后首次调用即开始试用。"""
    if LICENSE_OFF or not public_key_pem():
        return _dev_status()
    data = _load_file()
    rec = data.get("license")
    base = {"configured": True, "machine": machine_id(),
            "trial_ends": None, "trial_ends_text": "",
            "trial_days_left": None, "edition": None, "license_id": None,
            "devices": None, "updates_until": None,
            "updates_until_text": "", "updates_active": False,
            "activation_required": False}
    if rec:
        try:
            payload = verify_license_key(rec.get("key"))
        except LicenseError as e:
            return dict(base, mode="invalid", can_publish=False,
                        activation_required=True,
                        message="许可无效：%s" % e,
                        hint="重新运行 panweb license activate <密钥>")
        if rec.get("machine") and rec["machine"] != base["machine"]:
            return dict(base, mode="invalid", can_publish=False,
                        activation_required=True,
                        message="许可已绑定其他设备",
                        hint="在旧设备运行 panweb license deactivate，"
                             "或用同一密钥在本机重新激活")
        updates_until = float(payload.get("updates_until") or 0)
        now = time.time()
        return dict(base, mode="active", can_publish=True,
                    edition=payload.get("edition") or "pro",
                    license_id=payload.get("license_id"),
                    buyer=payload.get("buyer") or "",
                    devices=payload.get("devices"),
                    updates_until=updates_until or None,
                    updates_until_text=_fmt_date(updates_until),
                    updates_active=(now < updates_until) if updates_until else False,
                    activated_at=rec.get("activated_at"),
                    message=("已激活 · 永久使用"
                             + (" · 更新至 %s" % _fmt_date(updates_until)
                                if updates_until else "")),
                    hint=("更新服务已到期，当前版本可继续使用"
                          if updates_until and now >= updates_until else ""))
    now = time.time()
    started = data.get("trial_started")
    if start_trial and not started:
        data["trial_started"] = now
        _save_file(data)
        started = now
    try:
        started = float(started or now)
    except (TypeError, ValueError):
        started = now
    ends = started + TRIAL_DAYS * 86400
    left = math.ceil((ends - now) / 86400)
    if now >= ends:
        return dict(base, mode="expired", can_publish=False,
                    activation_required=True, trial_ends=ends,
                    trial_ends_text=_fmt_date(ends), trial_days_left=0,
                    message="试用已结束",
                    hint="购买后运行 panweb license activate <密钥> 继续使用")
    return dict(base, mode="trial", can_publish=True,
                activation_required=False, trial_ends=ends,
                trial_ends_text=_fmt_date(ends), trial_days_left=max(0, left),
                message="试用中 · 剩余 %d 天" % max(0, left),
                hint="购买后运行 panweb license activate <密钥>")


def activate_license(key):
    pem = public_key_pem()
    if not pem:
        raise PanwebError(3, "license_not_configured",
                          "此构建未启用许可校验",
                          "开发版无需激活；发行版需内置许可公钥")
    try:
        payload = verify_license_key(key)
    except LicenseError as e:
        raise PanwebError(2, "invalid_license", str(e),
                          "检查密钥是否完整复制，或联系卖家重新签发")
    data = _load_file()
    data["license"] = {
        "key": (key or "").strip(),
        "payload": payload,
        "machine": machine_id(),
        "activated_at": time.time(),
    }
    _save_file(data)
    return license_status(start_trial=False)


def deactivate_license():
    data = _load_file()
    removed = data.pop("license", None)
    _save_file(data)
    return {"removed": bool(removed), "status": license_status(start_trial=False)}


def require_publish_license():
    status = license_status()
    if status.get("can_publish"):
        return status
    raise PanwebError(10, "license_required", status.get("message") or "需要激活",
                      status.get("hint") or
                      "购买后运行 panweb license activate <密钥>")
