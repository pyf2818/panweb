// ---------- 动作 ----------
function copyText(s) {
  const done = () => toast("已复制：" + s);
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(s).then(done, () => fallbackCopy(s, done));
  else fallbackCopy(s, done);
}
function fallbackCopy(s, done) {
  const ta = document.createElement("textarea");
  ta.value = s; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) { toast("复制失败，请手动选择", false); }
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

// ---------- 发布弹窗 ----------
let pubTab = "port";
function openPublish(tab) {
  if (STATE && STATE.license && STATE.license.activation_required) {
    toast("试用已结束，请先激活买断版", false);
    openLicense();
    return;
  }
  pubTab = tab || "port";
  switchTab(pubTab);
  document.getElementById("in-name").value = "";
  document.getElementById("in-port").value = "";
  document.getElementById("in-folder").value = "";
  document.getElementById("in-project").value = "";
  document.getElementById("in-pin").value = "";
  document.getElementById("in-share").checked = true;
  document.getElementById("in-exp").value = "";
  document.getElementById("in-files").value = "";
  document.getElementById("in-cloudfolder").value = "";
  document.getElementById("detect-line").className = "detect-line";
  selPort = null; selPortRisky = null; detected = null;
  updateRisk();
  document.getElementById("pub-overlay").classList.add("show");
  if (pubTab === "port") loadCandidates();
  setTimeout(() => {
    const el = pubTab === "port" ? "in-port" : pubTab === "pages" ? "in-folder"
      : pubTab === "cloud" ? "in-cloudfolder" : "in-project";
    document.getElementById(el).focus();
  }, 120);
}
function closePublish() { document.getElementById("pub-overlay").classList.remove("show"); }
function switchTab(tab) {
  pubTab = tab;
  ["port", "pages", "project", "cloud"].forEach(t =>
    document.getElementById("tab-" + t).classList.toggle("active", t === tab));
  document.getElementById("pane-port").style.display = tab === "port" ? "" : "none";
  document.getElementById("pane-pages").style.display = tab === "pages" ? "" : "none";
  document.getElementById("pane-project").style.display = tab === "project" ? "" : "none";
  document.getElementById("pane-cloud").style.display = tab === "cloud" ? "" : "none";
  document.getElementById("pin-field").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("share-line").style.display = tab === "cloud" ? "none" : "flex";
  document.getElementById("share-hint").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("in-share").disabled = tab === "pages";
  if (tab === "pages") document.getElementById("in-share").checked = true;
  document.getElementById("share-hint").textContent = tab === "pages"
    ? "文件夹发布默认经由内置代理，分享页与访问统计自动开启。"
    : "分享链接会先展示应用名、说明、有效期和口令入口；取消勾选则直连发布（更快，但无统计）。";
  document.getElementById("in-exp").closest(".field").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("pub-btn").textContent =
    tab === "project" ? "启动并发布" : tab === "cloud" ? "上传并托管" : "发布";
  updateRisk();
}
async function loadCandidates() {
  const list = document.getElementById("cand-list");
  list.innerHTML = '<div class="feed-empty">扫描中…</div>';
  const d = await api("/api/discover");
  if (!d.ok) { list.innerHTML = '<div class="feed-empty">扫描失败</div>'; return; }
  const cands = d.data.candidates;
  if (!cands.length) {
    list.innerHTML = '<div class="feed-empty">没有发现正在运行的应用<br>可先在本地启动项目，或到「启动项目」让 panweb 替你启动</div>';
    return;
  }
  list.innerHTML = cands.map((c, i) =>
    '<div class="cand" data-port="' + c.port + '" data-risky="' + esc(c.risky || "") + '" onclick="selCand(this)">' +
    '<span class="c-port">' + c.port + '</span><span class="c-title">' + esc(c.title) + '</span>' +
    '<span class="c-proc">' + esc(c.process || "") + '</span>' +
    (c.published ? '<span class="c-risk" style="color:var(--accent);background:var(--accent-soft)">已发布</span>' : '') +
    (c.risky ? '<span class="c-risk">⚠ 高危</span>' : '') + '</div>').join("");
}
function selCand(el) {
  document.querySelectorAll(".cand").forEach(x => x.classList.remove("sel"));
  el.classList.add("sel");
  selPort = el.dataset.port;
  selPortRisky = el.dataset.risky || null;
  document.getElementById("in-port").value = selPort;
  updateRisk();
}
function updateRisk() {
  const warn = document.getElementById("risk-warn");
  const check = document.getElementById("risk-check");
  const risky = pubTab === "port" ? selPortRisky : null;
  if (risky) {
    warn.textContent = "⚠ " + risky;
    warn.classList.add("show");
    check.style.display = "flex";
  } else {
    warn.classList.remove("show");
    check.style.display = "none";
    document.getElementById("risk-ack").checked = false;
  }
}

// 项目识别
async function detectProject() {
  const folder = document.getElementById("in-project").value.trim();
  const line = document.getElementById("detect-line");
  if (!folder) return;
  line.className = "detect-line show warn";
  line.textContent = "识别中…";
  const d = await api("/api/detect?folder=" + encodeURIComponent(folder));
  if (!d.ok) {
    line.className = "detect-line show err";
    line.textContent = d.error ? d.error.message : "识别失败";
    detected = null;
    return;
  }
  detected = d.data;
  if (detected.type === "static" || detected.type === "node") {
    line.className = "detect-line show ok";
    line.textContent = "✓ " + detected.detail + "，可以直接启动并发布";
  } else {
    line.className = "detect-line show warn";
    line.textContent = "△ " + detected.detail;
  }
}
let detectTimer = null;
document.addEventListener("input", e => {
  if (e.target && e.target.id === "in-project") {
    clearTimeout(detectTimer);
    detectTimer = setTimeout(detectProject, 700);
  }
});

async function doPublish() {
  const btn = document.getElementById("pub-btn");
  const pin = document.getElementById("in-pin").value.trim() || null;
  const expires = document.getElementById("in-exp").value || null;
  const share = document.getElementById("in-share").checked;
  let path, body;
  if (pubTab === "port") {
    const port = parseInt(document.getElementById("in-port").value, 10);
    if (!port) return toast("请输入或选择一个端口", false);
    if (selPortRisky && String(port) === String(selPort) && !document.getElementById("risk-ack").checked)
      return toast("请先勾选「我了解风险」", false);
    body = {port, name: document.getElementById("in-name").value.trim() || null, pin, expires, share};
    path = "/api/publish";
  } else if (pubTab === "pages") {
    const folder = document.getElementById("in-folder").value.trim();
    if (!folder) return toast("请输入文件夹路径", false);
    body = {folder, name: document.getElementById("in-name").value.trim() || null, pin, expires, share: true};
    path = "/api/pages";
  } else if (pubTab === "cloud") {
    const fileEl = document.getElementById("in-files");
    const folder = document.getElementById("in-cloudfolder").value.trim();
    const name = document.getElementById("in-name").value.trim() || null;
    if (fileEl.files && fileEl.files.length) {
      btn.disabled = true;
      btn.innerHTML = '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><path d="M21 12a9 9 0 11-6.2-8.56"/></svg> 上传中…';
      const files = [];
      for (const f of fileEl.files) {
        const buf = await f.arrayBuffer();
        let bin = "";
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.length; i += 0x8000)
          bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        files.push({path: f.name, content_b64: btoa(bin)});
      }
      body = {name, files};
      path = "/api/host-upload";
    } else if (folder) {
      body = {path: folder, name};
      path = "/api/host";
    } else {
      return toast("请选择文件或填写文件夹路径", false);
    }
  } else {
    const folder = document.getElementById("in-project").value.trim();
    if (!folder) return toast("请输入项目文件夹路径", false);
    if (detected && (detected.type === "python" || detected.type === "unknown"))
      return toast(detected.detail, false);
    body = {folder, name: document.getElementById("in-name").value.trim() || null, share};
    path = "/api/run";
  }
  btn.disabled = true;
  btn.innerHTML = '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><path d="M21 12a9 9 0 11-6.2-8.56"/></svg> ' +
    (pubTab === "project" ? "启动中…（可能需要 1-2 分钟）" : pubTab === "cloud" ? "部署中…（约 30-60 秒）" : "发布中…（约 10 秒）");
  const d = await api(path, body);
  btn.disabled = false;
  btn.textContent = pubTab === "project" ? "启动并发布" : pubTab === "cloud" ? "上传并托管" : "发布";
  if (!d.ok) {
    toast(d.error ? d.error.message : "发布失败", false);
    return;
  }
  closePublish();
  toast("已发布：" + (d.data.share_url || d.data.url));
  await refresh();
}

// ---------- 详情抽屉 ----------
function openDrawer(id) {
  currentDrawerId = id;
  document.getElementById("drawer-mask").classList.add("show");
  document.getElementById("drawer").classList.add("show");
  compatCache = null;
  loadCompat(id);
  loadDetail();
  clearInterval(drawerTimer);
  drawerTimer = setInterval(() => { if (currentDrawerId) loadDetail(); }, 2500);
}
function closeDrawer() {
  currentDrawerId = null;
  clearInterval(drawerTimer);
  document.getElementById("drawer-mask").classList.remove("show");
  document.getElementById("drawer").classList.remove("show");
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
  document.getElementById("dw-name").textContent = a.name;
  document.getElementById("dw-kind").textContent = a.kind === "pages" ? "只读网页" : "端口 " + a.target;
  document.getElementById("dw-url").textContent = a.url;
  const src = a.kind === "pages" ? a.target : "127.0.0.1:" + a.target;
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

