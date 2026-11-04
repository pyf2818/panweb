// ---------- 动作 ----------
function announce(text) {
  const el = document.getElementById("sr-live");
  if (!el) return;
  el.textContent = "";
  setTimeout(() => { el.textContent = text; }, 30);
}
function copyText(s) {
  const short = s && s.length > 120 ? s.slice(0, 117) + "…" : s;
  const done = () => {
    toast("已复制：" + s);
    announce("已复制 " + (short || "内容") + " 到剪贴板");
  };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(s).then(done, () => fallbackCopy(s, done));
  else fallbackCopy(s, done);
}
function fallbackCopy(s, done) {
  const ta = document.createElement("textarea");
  ta.value = s; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) {
    toast("复制失败，请手动选择", false);
    announce("复制失败，请手动选择");
  }
  ta.remove();
}
function openUrl(url, entryId) {
  if (entryId) {
    fetch("/api/owner-open", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: entryId}),
      keepalive: true
    }).catch(() => {});
  }
  window.open(url, "_blank", "noopener");
}

// ---------- 详情抽屉 ----------
function openDrawer(id) {
  currentDrawerId = id;
  document.getElementById("drawer-mask").classList.add("show");
  document.getElementById("drawer").classList.add("show");
  compatCache = null;
  loadCompat(id);
  loadTimeline(id);
  loadDetail();
  clearInterval(drawerTimer);
  drawerTimer = setInterval(() => { if (currentDrawerId) loadDetail(); }, 2500);
  if (typeof tmFitSoon === "function") setTimeout(tmFitSoon, 260);
}
function closeDrawer() {
  currentDrawerId = null;
  clearInterval(drawerTimer);
  document.getElementById("drawer-mask").classList.remove("show");
  document.getElementById("drawer").classList.remove("show");
  if (typeof tmFitSoon === "function") setTimeout(tmFitSoon, 260);
}
const TIMELINE_LABELS = {publish:"发布", restart:"重启", url_change:"换网址",
  pin_change:"改口令", expire:"到期", stop:"停止", error:"出错"};
function loadTimeline(id) {
  const el = document.getElementById("dw-timeline");
  el.innerHTML = '<div class="feed-empty">正在读取…</div>';
  fetch("/api/history?id=" + encodeURIComponent(id) + "&limit=20")
    .then(r => r.json()).then(d => {
      if (!d.ok) throw new Error();
      const rows = (d.data && d.data.events) || [];
      if (!rows.length) {
        el.innerHTML = '<div class="feed-empty">还没有变更记录；发布、改口令、重建通道或停止后会出现在这里。</div>';
        return;
      }
      el.innerHTML = rows.map(e => {
        const t = new Date(e.ts * 1000);
        const ts = t.toLocaleDateString() + " " + t.toTimeString().slice(0, 8);
        const x = e.details || {};
        const diff = (x.url_before && x.url_after && x.url_before !== x.url_after)
          ? '<span class="v-path" style="color:var(--faint)">' + esc(x.url_before) +
            " → " + esc(x.url_after) + '</span>' : "";
        return '<div class="v-row"><span class="v-time">' + esc(ts) + '</span>' +
          '<span class="v-kind">' + esc(TIMELINE_LABELS[e.type] || e.type) + '</span>' +
          '<span class="v-path">' + esc(e.summary || "") + '</span>' + diff + '</div>';
      }).join("");
    })
    .catch(() => { el.innerHTML = '<div class="feed-empty">时间线读取失败，稍后重试</div>'; });
}
function setChartHours(h) {
  chartHours = h;
  document.getElementById("ct-24").classList.toggle("active", h === 24);
  document.getElementById("ct-168").classList.toggle("active", h === 168);
  loadDetail();
}
function loadDetail() {
  const a = (STATE.apps || []).find(x => x.id === currentDrawerId);
  if (!a) { closeDrawer(); return; }
  fetch("/api/visits?id=" + encodeURIComponent(currentDrawerId) + "&hours=" + chartHours)
    .then(r => r.json()).then(d => { if (d.ok) renderVisits(d.data); });
  const dom = STATE.domain || {};
  document.getElementById("dw-domain").innerHTML = dom.configured
    ? (dom.bound_id === currentDrawerId
        ? '<button class="btn btn-sm" onclick="bindDomain(null)">解绑固定域名</button>'
        : '<button class="btn btn-sm" onclick="bindDomain(' + jsq(currentDrawerId) + ')">设为固定域名应用</button>')
    : "";
  document.getElementById("dw-name").textContent = a.title || a.name;
  document.getElementById("dw-kind").textContent = a.kind === "pages" ? "只读网页" : "端口 " + a.port;
  document.getElementById("dw-url").textContent = a.url;
  const src = a.kind === "pages" ? a.folder : "127.0.0.1:" + a.port;
  const pinTxt = a.pinned ? " · 🔐 已设口令" : "";
  document.getElementById("dw-meta").textContent =
    "来源 " + src + " · 发布于 " + a.started + pinTxt + (a.launched ? " · 由 panweb 启动" : "");
  renderCheckSection(a);
  const pv = a.pv || {total: 0, uv: 0, points: [], last: null, recent: []};
  document.getElementById("dw-pv").textContent = a.proxy_port ? pv.total : "—";
  document.getElementById("dw-uv").textContent = a.proxy_port ? pv.uv : "—";
  document.getElementById("dw-last").textContent =
    pv.last ? new Date(pv.last * 1000).toTimeString().slice(0, 5) : "—";
  document.getElementById("dw-rename").value = a.name;
  document.getElementById("dw-rename").placeholder = a.name;
  const shareUrl = a.share_url || "";
  document.getElementById("dw-share-row").style.display = shareUrl ? "" : "none";
  document.getElementById("dw-share-url").textContent = shareUrl;
  document.getElementById("dw-share-desc-row").style.display = shareUrl ? "flex" : "none";
  const descEl = document.getElementById("dw-share-desc");
  if (document.activeElement !== descEl) descEl.value = a.desc || "";
  const enableBtn = document.getElementById("dw-share-enable");
  if (shareUrl) {
    document.getElementById("dw-share-hint").textContent =
      "收到分享链接的人会先看到应用名、说明、有效期和口令入口，再进入应用。";
    enableBtn.style.display = "none";
  } else if (a.proxy_port && !a.share_token) {
    document.getElementById("dw-share-hint").textContent =
      "这个应用还没有分享页；点「启用分享页」即可生成，网址不变。";
    enableBtn.style.display = "";
  } else {
    document.getElementById("dw-share-hint").textContent =
      "直连发布不记录统计，也没有分享页；重新发布时勾选「分享页 + 访问统计」即可。";
    enableBtn.style.display = "none";
  }
  if (!a.proxy_port) {
    document.getElementById("dw-meta").textContent += " · 直连发布不记录访问统计";
  }
  // 访问明细
  const vl = document.getElementById("dw-visits");
  vl.innerHTML = (pv.recent || []).length ? pv.recent.map(r =>
    '<div class="v-row"><span class="v-time">' +
    new Date(r.ts * 1000).toTimeString().slice(0, 5) + '</span>' +
    '<span class="v-path">' + esc(r.path || "/") + '</span></div>').join("")
    : '<div class="feed-empty">暂无记录</div>';
}

function renderVisits(v) {
  const chart = document.getElementById("dw-chart");
  const maxC = Math.max(1, ...(v.points || []).map(p => p.count));
  chart.innerHTML = (v.points || []).map(p =>
    '<div class="bar' + (p.count === maxC && p.count > 0 ? " hot" : "") + '" style="height:' +
    Math.max(4, Math.round(p.count / maxC * 100)) + '%" title="' + p.count + ' 次"></div>').join("");
  const devs = v.devices || {};
  const keys = Object.keys(devs);
  const chips = [];
  if (v.share) chips.push('<span class="dev-chip">分享页 ' + v.share + '</span>');
  if (v.app) chips.push('<span class="dev-chip">应用打开 ' + v.app + '</span>');
  keys.forEach(k => chips.push('<span class="dev-chip">' + esc(k) + " " + devs[k] + '</span>'));
  document.getElementById("dw-devs").innerHTML = chips.join("");
  const countries = v.countries || {};
  const browsers = v.browsers || {};
  const src = [];
  Object.keys(countries).sort((a, b) => countries[b] - countries[a]).slice(0, 4)
    .forEach(k => src.push('<span class="dev-chip">' + esc(countryName(k)) + " " + countries[k] + '</span>'));
  Object.keys(browsers).sort((a, b) => browsers[b] - browsers[a]).slice(0, 4)
    .forEach(k => src.push('<span class="dev-chip">' + esc(k) + " " + browsers[k] + '</span>'));
  document.getElementById("dw-sources").innerHTML = src.join("");
  document.getElementById("dw-visit-split").textContent = v.total
    ? "分享页浏览 " + (v.share || 0) + " · 应用打开 " + (v.app || 0) + " · 近 " + v.hours + " 小时"
    : "还没有访问记录；把分享链接发出去试试。";
  const vl = document.getElementById("dw-visits");
  vl.innerHTML = (v.recent || []).length ? v.recent.map(r => {
    const meta = [r.device, r.country ? countryName(r.country) : "", r.browser].filter(Boolean).join(" · ");
    return '<div class="v-row"><span class="v-time">' +
      new Date(r.ts * 1000).toTimeString().slice(0, 5) + '</span>' +
      '<span class="v-kind' + (r.kind === "share" ? " share" : "") + '">' +
      (r.kind === "share" ? "分享" : "打开") + '</span>' +
      (meta ? '<span class="v-device" style="color:var(--faint)">' + esc(meta) + '</span>' : '') +
      '<span class="v-path">' + esc(r.path || "/") + '</span></div>';
  }).join("") : '<div class="feed-empty">暂无记录</div>';
}
