let STATE = null;
let selPort = null;
let selPortRisky = null;
let stopTarget = null;
let detected = null; // 项目识别结果
let currentDrawerId = null;
let drawerTimer = null;
let chartHours = 24;
let lastNotifyTs = parseFloat(localStorage.getItem("panweb-notify-ts")) || 0;
let readTs = parseFloat(localStorage.getItem("panweb-read-ts")) || 0;
let lastPushTs = lastNotifyTs;

// ---------- 工具 ----------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
// 内联事件里使用：JSON.stringify 生成双引号 JS 字符串，再做 HTML 转义，
// 浏览器实体解码后仍是合法的双引号字符串，用户数据无法闭合引号注入代码。
function jsq(v) {
  return esc(JSON.stringify(String(v ?? "")));
}
function toast(msg, ok = true) {
  const t = document.createElement("div");
  t.className = "toast " + (ok ? "ok" : "err");
  t.innerHTML = '<span class="msg">' + esc(msg) + "</span>";
  document.getElementById("toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .4s"; setTimeout(() => t.remove(), 400); }, 3600);
}
let lastSkewAt = 0;
async function api(path, body) {
  try {
    const opt = body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {};
    const r = await fetch(path, opt);
    const d = await r.json();
    // 页面是每次从磁盘读的，Python 却是进程启动时加载的：新页面配旧进程会一路"未知路径"，
    // 只报"未知路径"没人知道该重启，所以这里把话说明白（一分钟最多提醒一次）
    if (d && d.ok === false && d.error && d.error.type === "not_found" &&
        /^未知路径/.test(d.error.message || "") && Date.now() - lastSkewAt > 60000) {
      lastSkewAt = Date.now();
      toast("控制台还是旧进程：这个功能要重启才生效（系统页 → 停止控制台，再 panweb console start）", false);
    }
    return d;
  } catch (e) {
    return {ok: false, error: {type: "network", message: "控制台连接失败，请确认 panweb 仍在运行"}};
  }
}

// ---------- 数据 ----------
function refresh(showToast = false) {
  return refreshInner(showToast);
}
let lastApiErrorAt = 0;
async function refreshInner(showToast = false) {
  const d = await api("/api/state");
  if (!d.ok) {
    if (Date.now() - lastApiErrorAt > 15000) {
      lastApiErrorAt = Date.now();
      toast(d.error ? d.error.message : "读取状态失败", false);
    }
    return;
  }
  STATE = d.data;
  render();
  checkNotifs();
  fx.sync(STATE);
  if (showToast) toast("已刷新");
}
function render() {
  const {doctor, apps, stats, activity} = STATE;

  // 状态 pill + 侧栏环境
  const ready = doctor.ready;
  const ver = doctor.cloudflared_version ? doctor.cloudflared_version.replace("cloudflared version ", "").split(" (")[0] : null;
  const pill = document.getElementById("env-pill");
  pill.innerHTML = ready ? "<b>● 就绪</b>&nbsp;cloudflared " + esc(ver || "") : "<b>○ 未就绪</b>&nbsp;缺 cloudflared";
  pill.classList.toggle("warn", !ready);
  document.getElementById("side-dot").classList.toggle("bad", !ready);
  document.getElementById("side-state").textContent = ready ? "通道就绪" : "通道未就绪";
  document.getElementById("side-ver").textContent = ver ? "cloudflared " + ver : "brew install cloudflared";
  document.getElementById("side-dir").textContent = doctor.state_dir;
  renderLicense();

  // 工作台：左栏资产 + 中栏对话 + 右栏进程
  const hosted = STATE.hosted || [];
  if (typeof renderWorkbench === "function") renderWorkbench(apps, hosted);
  if (typeof renderViz === "function") renderViz();

  // 动态页：统计 + 时间线
  const cnt = k => activity.filter(f => f.kind === k).length;
  document.getElementById("fs-pub").textContent = cnt("publish");
  document.getElementById("fs-stop").textContent = cnt("stop");
  document.getElementById("fs-heal").textContent = activity.filter(f => (f.text || "").includes("自动恢复")).length;
  document.getElementById("feed-list").innerHTML =
    activity.length ? activity.map(feedItem).join("") : '<div class="feed-empty">暂无动态</div>';
  renderVisitFeed(STATE.visits_recent || []);

  updateSub();
}

function fmtRemain(ts) {
  const sec = ts - Date.now() / 1000;
  if (sec <= 0) return "已到期";
  if (sec < 3600) return Math.max(1, Math.ceil(sec / 60)) + " 分钟";
  if (sec < 86400) return Math.ceil(sec / 3600) + " 小时";
  return Math.ceil(sec / 86400) + " 天";
}
function hostedCard(h) {
  return '<div class="card app-card">' +
    '<div class="app-top">' +
      '<div class="app-ic" style="background:var(--gold-soft);color:var(--gold)">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 17.6A5 5 0 0018 8h-1.3A8 8 0 104 15.2"/></svg></div>' +
      '<div class="app-name">' + esc(h.name) + '</div>' +
      '<span class="kind-badge" style="color:var(--gold);border-color:var(--gold)">🌐 云端托管</span>' +
    '</div>' +
    '<div class="url-row"><span class="u" onclick="openUrl(' + jsq(h.url) + ')" title="点击打开">' + esc(h.url) + '</span>' +
      '<button class="cp" onclick="copyText(' + jsq(h.url) + ')" title="复制网址"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg></button></div>' +
    '<div class="app-meta">' + esc(h.files) + ' 个文件 · 更新于 ' + esc(h.updated) + ' · <span style="color:var(--accent-deep)">关机可访问</span></div>' +
    '<div class="app-actions">' +
      '<button class="btn btn-sm" onclick="openUrl(' + jsq(h.url) + ')">打开</button>' +
      '<button class="btn btn-sm" onclick="copyText(' + jsq(h.url) + ')">复制</button>' +
      '<span style="flex:1"></span>' +
      '<button class="btn btn-sm" onclick="redeployHost(' + jsq(h.name) + ')">重新部署</button>' +
    '</div></div>';
}
async function redeployHost(name) {
  toast("重新部署中…（约 30-60 秒）");
  const d = await api("/api/host-redeploy", {name});
  if (!d.ok) return toast(d.error ? d.error.message : "部署失败", false);
  toast("已重新部署：" + d.data.url);
  await refresh();
}
function appCard(a) {
  const src = a.kind === "pages" ? esc(a.folder) : "127.0.0.1:" + a.port;
  const launched = a.launched ? '<span class="launched-tag">· 由 panweb 启动</span>' : "";
  const pv = a.pv || {total: 0, uv: 0};
  const shareUrl = a.share_url || "";
  const pvText = a.proxy_port
    ? pv.uv + ' 位访客 · ' + pv.total + ' 次访问' + (shareUrl ? ' · 有分享页' : '')
    : '直连发布 · 未统计 PV';
  const aliveTxt = a.alive === false ? '<span style="color:var(--danger)">· 恢复中…</span>' : "";
  return '<div class="card app-card" id="app-' + esc(a.id) + '">' +
    '<div class="app-top">' +
      '<div class="app-ic">' + (a.kind === "pages"
        ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>'
        : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a13.5 13.5 0 010 18M12 3a13.5 13.5 0 000 18"/></svg>') + '</div>' +
      '<div class="app-name">' + esc(a.title || a.name) + '</div>' +
      '<span class="kind-badge">' + (a.kind === "pages" ? "只读网页" : "端口 " + a.port) + '</span>' +
      checkBadge(a) +
    '</div>' +
    (a.risky ? '<div class="risky-badge">⚠ ' + esc(a.risky) + '</div>' : '') +
    '<div class="url-row"><span class="u" onclick="openUrl(' + jsq(a.url) + ',' + jsq(a.id) + ')" title="点击打开">' + esc(a.url) + '</span>' +
      '<button class="cp" onclick="copyText(' + jsq(a.url) + ')" title="复制网址"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 012-2h10"/></svg></button></div>' +
    '<div class="app-meta">' + pvText + ' · ' + (a.pinned ? "🔐 口令保护 · " : "") + (a.auth_kind ? "🔑 代填上游凭据 · " : "") + (a.expires_at ? '<span class="badge-exp' + (a.expires_at - Date.now()/1000 < 3600 ? " soon" : "") + '">⏳ 剩余 ' + fmtRemain(a.expires_at) + '</span> · ' : "") + esc(a.started) + ' ' + launched + aliveTxt + '</div>' +
    '<div class="qr-panel" id="qr-' + esc(a.id) + '"><div class="q" id="qrs-' + esc(a.id) + '"></div><div class="t">扫码直达应用；给客户看请用「分享链接」</div></div>' +
    '<div class="app-actions">' +
      '<button class="btn btn-sm" onclick="openDrawer(' + jsq(a.id) + ')">详情</button>' +
      '<button class="btn btn-sm" onclick="toggleQr(' + jsq(a.id) + ')">二维码</button>' +
      (shareUrl ? '<button class="btn btn-sm" onclick="copyText(' + jsq(shareUrl) + ')">分享链接</button>' : '') +
      '<button class="btn btn-sm" onclick="openUrl(' + jsq(a.url) + ',' + jsq(a.id) + ')">打开</button>' +
      '<span style="flex:1"></span>' +
      '<button class="btn btn-sm btn-danger" onclick="askStop(' + jsq(a.id) + ',' + jsq(a.name) + ')">停止</button>' +
    '</div></div>';
}
function toggleQr(id) {
  const panel = document.getElementById("qr-" + id);
  const opening = !panel.classList.contains("open");
  document.querySelectorAll(".qr-panel.open").forEach(p => p.classList.remove("open"));
  if (opening) {
    panel.classList.add("open");
    const holder = document.getElementById("qrs-" + id);
    if (!holder.dataset.done && window.qrcode) {
      const app = (STATE.apps || []).find(x => x.id === id);
      if (app) {
        try {
          const q = qrcode(0, "M");
          q.addData(app.url);
          q.make();
          holder.innerHTML = q.createSvgTag({cellSize: 2, margin: 0, scalable: true});
          holder.firstElementChild.style.width = "118px";
          holder.firstElementChild.style.height = "118px";
          holder.dataset.done = "1";
        } catch (e) { holder.textContent = "生成二维码失败，请复制网址"; }
      }
    }
  }
}
function feedItem(f) {
  const cls = f.kind === "publish" ? "fi-publish" : f.kind === "stop" ? "fi-stop" : "fi-ui";
  const ic = f.kind === "stop"
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 6L9 17l-5-5"/></svg>';
  return '<div class="feed-item"><div class="feed-ic ' + cls + '">' + ic + '</div>' +
    '<div class="feed-body"><div class="feed-text">' + esc(f.text) + '</div>' +
    (f.detail ? '<div class="feed-detail">' + esc(f.detail) + '</div>' : '') + '</div>' +
    '<div class="feed-time">' + esc(f.ts ? f.ts.slice(5, 16) : "") + '</div></div>';
}
const COUNTRY_NAMES = {
  CN: "中国", HK: "中国香港", TW: "中国台湾", MO: "中国澳门",
  US: "美国", JP: "日本", KR: "韩国", SG: "新加坡", GB: "英国",
  DE: "德国", FR: "法国", CA: "加拿大", AU: "澳大利亚", IN: "印度",
};
function countryName(code) { return code ? (COUNTRY_NAMES[code] || code) : ""; }
function renderVisitFeed(items) {
  const el = document.getElementById("visit-feed");
  if (!items || !items.length) {
    el.innerHTML = '<div class="feed-empty">暂无访客 · 分享链接被打开后会显示在这里</div>';
    return;
  }
  el.innerHTML = '<div class="visit-feed-head">访客动态 <span class="live-pill">实时</span></div>' +
    items.map(v => {
      const share = v.kind === "share";
      const text = share
        ? "打开了「" + esc(v.name) + "」的分享页"
        : "正在看「" + esc(v.name) + "」";
      const meta = [v.device, countryName(v.country), v.browser].filter(Boolean).map(esc).join(" · ");
      const t = v.ts ? new Date(v.ts * 1000).toTimeString().slice(0, 5) : "";
      return '<div class="visit-feed-item">' +
        '<div class="visit-feed-ic' + (share ? " share" : "") + '">' + (share ? "↗" : "◉") + '</div>' +
        '<div class="visit-feed-body"><div class="visit-feed-text">' + text + '</div>' +
        (meta ? '<div class="visit-feed-meta">' + meta + '</div>' : '') + '</div>' +
        '<div class="visit-feed-time">' + esc(t) + '</div></div>';
    }).join("");
}

// ---------- 通知中心 ----------
function checkNotifs() {
  const acts = (STATE.activity || []);
  const unreadItems = acts.filter(f => {
    const ts = new Date(f.ts.replace(" ", "T")).getTime() || 0;
    return ts > readTs;
  });
  const badge = document.getElementById("bell-badge");
  badge.style.display = unreadItems.length ? "grid" : "none";
  badge.textContent = unreadItems.length;
  // 系统通知（仅重要事件 + 已授权 + 未推送过）
  if (window.Notification && Notification.permission === "granted") {
    acts.filter(f => {
      const ts = new Date(f.ts.replace(" ", "T")).getTime() || 0;
      return ts > lastPushTs && (f.kind === "stop" || (f.text || "").includes("自动恢复") || (f.text || "").includes("到期"));
    }).forEach(f => {
      try { new Notification("panweb", {body: f.text}); } catch (e) {}
    });
  }
  const newest = acts.length ? new Date(acts[0].ts.replace(" ", "T")).getTime() : 0;
  if (newest > lastPushTs) lastPushTs = newest;
  localStorage.setItem("panweb-notify-ts", String(lastPushTs));
  // 铃铛面板内容
  const list = document.getElementById("bell-list");
  list.innerHTML = unreadItems.length
    ? unreadItems.slice(0, 10).map(f =>
        '<div class="bell-item">' + esc(f.text) + '<div class="t">' + esc(f.ts) + '</div></div>').join("")
    : '<div class="feed-empty">暂无新通知</div>';
}
function toggleBell(e) {
  if (e) e.stopPropagation();
  document.getElementById("bell-panel").classList.toggle("show");
  checkNotifs();
}
function markAllRead() {
  readTs = Date.now();
  localStorage.setItem("panweb-read-ts", String(readTs));
  checkNotifs();
}
function askNotifyPerm() {
  if (!window.Notification) return toast("此浏览器不支持系统通知", false);
  Notification.requestPermission().then(p => {
    if (p === "granted") { toast("系统通知已开启"); new Notification("panweb", {body: "通知已开启，通道恢复和到期收回会提醒你"}); }
    else toast("未授权系统通知", false);
    const b = document.getElementById("notify-perm-btn");
    if (b) b.textContent = p === "granted" ? "已开启" : "未授权";
  });
}
document.addEventListener("click", e => {
  const p = document.getElementById("bell-panel");
  if (p.classList.contains("show") && !p.contains(e.target) && e.target.closest("#bell-btn") === null)
    p.classList.remove("show");
});

