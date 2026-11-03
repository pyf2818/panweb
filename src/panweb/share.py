"""分享页、登录页与分享令牌。"""
import html
import re
import secrets
import time

from .store import load_state, save_state, state_lock

LOGIN_PAGE = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>访问验证</title><style>
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px 16px;font-family:-apple-system,"PingFang SC",sans-serif;
background:radial-gradient(600px 320px at 80% -10%,rgba(77,160,143,.14),transparent),radial-gradient(420px 260px at -8% 108%,rgba(185,151,91,.1),transparent),#f7f6f2;color:#22312e}
.card{background:#fff;border:1px solid #e9e6de;border-radius:18px;padding:32px 32px 28px;width:min(340px,100%);
box-shadow:0 2px 4px rgba(34,49,46,.05),0 18px 40px -18px rgba(34,49,46,.22);text-align:center}
.g{width:46px;height:46px;border-radius:14px;background:#33796b;color:#fff;display:grid;place-items:center;
margin:0 auto 14px;font-size:20px;box-shadow:0 8px 18px -8px rgba(51,121,107,.6)}
h1{font-size:17px;line-height:1.4;margin:0 0 6px}p{font-size:12.5px;line-height:1.6;color:#8a968f;margin:0 0 18px}
input{width:100%;padding:12px 13px;font-size:16px;border:1px solid #e9e6de;border-radius:10px;
outline:none;text-align:center;letter-spacing:.3em;box-sizing:border-box;background:#fff;color:#22312e}
input:focus{border-color:#33796b;box-shadow:0 0 0 3px rgba(51,121,107,.12)}
button{width:100%;margin-top:12px;padding:12px;border:none;border-radius:10px;background:#33796b;
color:#fff;font-size:14px;font-weight:600;cursor:pointer}button:hover{background:#2a6558}
.e{color:#b4544a;font-size:12px;margin-top:10px;min-height:16px}
@media(max-width:420px){body{padding:18px 12px}.card{padding:26px 22px 22px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="card"><div class="g">◈</div>
<h1>这个应用设置了访问口令</h1><p>输入主人分享的口令后即可打开</p>
<form method="POST" action="/__panweb/login"><input name="pw" type="password" placeholder="访问口令" autofocus>
<button>进入</button><div class="e">__PANWEB_ERR__</div></form></div></body></html>"""

SHARE_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__ · panweb</title>
<meta name="description" content="__DESC_ATTR__">
<meta name="robots" content="noindex,nofollow">
<meta property="og:type" content="website">
<meta property="og:site_name" content="panweb">
<meta property="og:title" content="__NAME__">
<meta property="og:description" content="__DESC_ATTR__">
<meta property="og:url" content="__SHARE_URL_ATTR__">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#f7f6f2">
<style>
:root{--bg:#f7f6f2;--card:#fff;--ink:#22312e;--muted:#8a968f;--line:#e9e6de;--accent:#33796b;--accent-deep:#2a6558;--soft:#e9f2ee;--gold:#b9975b;--danger:#b4544a;--warn:#a9752c;--faint:#a6b0aa;--mono:"SF Mono",ui-monospace,Menlo,monospace;--serif:"Songti SC","STSong",Georgia,serif}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:28px 16px;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans SC",sans-serif;-webkit-font-smoothing:antialiased;background:radial-gradient(700px 380px at 82% -12%,rgba(77,160,143,.15),transparent),radial-gradient(520px 320px at -5% 105%,rgba(185,151,91,.11),transparent),var(--bg)}
.card{position:relative;width:min(460px,100%);padding:26px 28px 22px;background:var(--card);border:1px solid var(--line);border-radius:24px;box-shadow:0 2px 4px rgba(34,49,46,.04),0 30px 70px -30px rgba(34,49,46,.25);overflow:hidden;animation:rise .5s cubic-bezier(.2,.8,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(10px)}}
.card:before{content:"";position:absolute;inset:0 0 auto;height:4px;background:linear-gradient(90deg,var(--accent),#7fb3a5,var(--gold))}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:26px}
.brand{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}
.brand b{color:var(--accent-deep);font-weight:600}
.mark{width:28px;height:28px;border-radius:9px;background:var(--accent);color:#fff;display:grid;place-items:center;font-size:14px}
.origin{font-size:10.5px;color:var(--faint);letter-spacing:.04em;text-align:right}
.icon{width:58px;height:58px;margin-bottom:16px;border-radius:18px;background:linear-gradient(145deg,#eef6f2,#dcebe4);border:1px solid #d8e7e0;color:var(--accent-deep);display:grid;place-items:center;font-family:var(--serif);font-size:28px;font-weight:600;line-height:1;box-shadow:0 10px 22px -16px rgba(51,121,107,.7)}
h1{margin:0 0 9px;font-family:var(--serif);font-size:clamp(24px,6vw,28px);font-weight:600;line-height:1.28;letter-spacing:.01em;word-break:break-word}
.desc{margin:0 0 18px;font-size:13.5px;line-height:1.72;color:#6d7a73;white-space:pre-wrap;word-break:break-word}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:22px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:5px 9px;border:1px solid var(--line);border-radius:999px;background:#f7f6f2;color:var(--muted);font-size:11.5px;white-space:nowrap}
.chip.ok{color:var(--accent-deep);background:var(--soft);border-color:#d8e7e0}
.chip.ok .dot{animation:live 1.8s ease-in-out infinite;box-shadow:0 0 0 3px rgba(51,121,107,.14)}
@keyframes live{50%{transform:scale(.7);opacity:.55}}
.chip.warn{color:var(--warn);background:#fbf5e9;border-color:#efe1c8}
.chip.bad{color:var(--danger);background:#fbf0ee;border-color:#efd6d2}
.dot{width:6px;height:6px;border-radius:50%;background:currentColor;display:inline-block}
.btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;min-height:47px;padding:12px 16px;border:0;border-radius:13px;background:var(--accent);color:#fff;font-size:14.5px;font-weight:600;text-decoration:none;cursor:pointer;transition:background .16s}
.btn:hover{background:var(--accent-deep)}
.btn.disabled,.btn:disabled{background:#dfe4e1;color:#98a39d;cursor:not-allowed}
form{margin:0}
input{width:100%;height:47px;margin-bottom:9px;padding:0 14px;border:1px solid var(--line);border-radius:12px;background:#fff;color:var(--ink);font-size:15px;text-align:center;letter-spacing:.25em;outline:none}
input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(51,121,107,.12)}
.hint{margin-top:10px;font-size:11.5px;line-height:1.6;color:var(--faint);text-align:center}
.err{min-height:16px;margin-top:9px;color:var(--danger);font-size:12px;text-align:center}
.closed{padding:13px 15px;border:1px dashed var(--line);border-radius:12px;background:#faf9f5;color:#7f8b84;font-size:12.5px;line-height:1.7;text-align:center}
.note{margin:0 0 15px;padding:10px 13px;border:1px dashed var(--line);border-radius:12px;background:#faf9f5;color:#7f8b84;font-size:11.5px;line-height:1.7;text-align:left}
.foot{margin-top:22px;padding-top:15px;border-top:1px dashed var(--line);font-size:10.5px;line-height:1.75;color:var(--faint);text-align:center}
.foot b{color:var(--accent-deep);font-weight:600}
@media(max-width:420px){body{padding:18px 12px}.card{padding:22px 20px 18px;border-radius:20px}h1{font-size:24px}.origin{display:none}.btn{min-height:50px}.foot{margin-top:18px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<main class="card">
  <div class="top">
    <div class="brand"><span class="mark">◈</span><b>panweb</b></div>
    <div class="origin">本机发布 · 直接连接</div>
  </div>
  <div class="icon">__INITIAL__</div>
  <h1>__NAME__</h1>
  <p class="desc">__DESC_TEXT__</p>
  <div class="chips">
    <span class="chip __STATUS_CLASS__"><span class="dot"></span>__STATUS_TEXT__</span>
    <span class="chip">__EXPIRY_TEXT__</span>
    __PIN_CHIP__
  </div>
  __NOTE__
  __ACTION__
  <div class="err">__ERR__</div>
  <div class="foot"><b>panweb</b> · 免费、零服务器的本机发布台<br>访问统计不保存原始 IP · 链接过期后自动失效</div>
</main>
</body>
</html>"""


def new_share_token():
    return secrets.token_urlsafe(9)


def fmt_share_expiry(expires_at):
    if not expires_at:
        return "长期有效"
    remain = expires_at - time.time()
    if remain <= 0:
        return "已于 %s 过期" % time.strftime("%m-%d %H:%M",
                                             time.localtime(expires_at))
    if remain < 3600:
        return "剩余 %d 分钟" % max(1, int(remain // 60 + 0.999))
    if remain < 86400:
        return "剩余 %d 小时" % max(1, int(remain // 3600 + 0.999))
    return "剩余 %d 天" % max(1, int(remain // 86400 + 0.999))


def share_note(entry, pin=False):
    """给访客的一句话说明：只说他会遇到什么，不泄露本机内部构造。"""
    check = entry.get("check") or {}
    codes = set()
    for sig in check.get("signals") or []:
        if isinstance(sig, dict):
            codes.add(sig.get("code"))
    if check.get("verdict") == "blocked":
        return "主人刚自检过：这个应用现在还没准备好，请稍等几分钟刷新，或联系主人。"
    if entry.get("auth_kind"):
        return ("进入应用后如还要账号，那是应用自己的登录；主人已经替你带上，"
                "通常可以直接使用。")
    if "app_login" in codes:
        return ("这个应用需要它自己的账号：上面的口令只决定你能不能打开网址，"
                "进去后仍要登录应用本身（账号请向主人索取）。")
    if "ws_blocked" in codes:
        return "这个应用依赖实时连接；如果页面长时间没有变化，刷新一次再试。"
    if check.get("verdict") == "warn" and not pin:
        return "首次打开可能慢一点；页面卡住就刷新一次。"
    return ""


def build_share_page(entry, share_url, token="", expired=False, offline=False,
                     pin=False, err=""):
    name = (entry.get("name") or "panweb").strip() or "panweb"
    desc = (entry.get("desc") or "").strip()
    if not desc:
        desc = ("这是一个从本机发布的静态网页。" if entry.get("kind") == "pages"
                else "这是一个从本机发布的实时应用。")
        desc += "打开即可访问，无需安装。"
    initial = name[:1].upper() if name[:1].isascii() else name[:1]
    if expired:
        status_class, status_text = "bad", "链接已过期"
        action = ('<div class="closed">这个分享链接已经过期。'
                  '请向发布者索取新的链接。</div>')
    elif offline:
        status_class, status_text = "warn", "应用暂时离线"
        action = ('<button class="btn disabled" disabled>应用暂时离线</button>'
                  '<div class="hint">本机应用当前没有响应，稍后刷新页面再试。</div>')
    else:
        status_class, status_text = "ok", "在线"
        if pin:
            action = (
                '<form method="POST" action="/__panweb/login?share=%s">'
                '<input type="hidden" name="next" value="/">'
                '<input name="pw" type="password" placeholder="访问口令" '
                'autocomplete="current-password" autofocus>'
                '<button class="btn" type="submit">输入口令并打开 →</button>'
                '<div class="hint">口令由发布者提供</div></form>'
                % html.escape(token, quote=True))
        else:
            action = '<a class="btn" href="/">打开应用 →</a>'
    pin_chip = ('<span class="chip">口令保护</span>' if pin
                else '<span class="chip">公开访问</span>')
    note = "" if (expired or offline) else share_note(entry, pin)
    if note and (entry.get("check") or {}).get("verdict") == "blocked":
        # 本机端口活着但访客打不开时，别让绿色「在线」和提示文字互相打脸
        status_class, status_text = "warn", "主人自检未通过"
    values = {
        "NAME": html.escape(name, quote=True),
        "INITIAL": html.escape(initial),
        "DESC_TEXT": html.escape(desc),
        "DESC_ATTR": html.escape(" ".join(desc.split())[:160], quote=True),
        "SHARE_URL_ATTR": html.escape(share_url, quote=True),
        "STATUS_CLASS": status_class,
        "STATUS_TEXT": status_text,
        "EXPIRY_TEXT": fmt_share_expiry(entry.get("expires_at")),
        "PIN_CHIP": pin_chip,
        "NOTE": ('<div class="note">%s</div>' % html.escape(note)) if note else "",
        "ACTION": action,
        "ERR": html.escape(err or ""),
    }
    return re.sub(r"__([A-Z_]+)__", lambda m: values.get(m.group(1), ""),
                  SHARE_PAGE)


def ensure_share_tokens():
    """旧版静态网页条目补充分享令牌；端口条目保持用户是否选择分享。"""
    with state_lock():
        entries = load_state()
        changed = False
        for e in entries:
            if e.get("kind") == "pages" and e.get("proxy_port") \
                    and not e.get("share_token"):
                e["share_token"] = new_share_token()
                changed = True
        if changed:
            save_state(entries)
