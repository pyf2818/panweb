// ---------- 左栏：资产档案 + 时间线 ----------
let selectedAssetId = localStorage.getItem("panweb-selected") || null;
const TIMELINE_CACHE = {};
const TIMELINE_PENDING = {};
let timelineToken = 0;
const GLOBAL_LIMIT = 10;
let GLOBAL_TIMELINE = null;
let GLOBAL_PENDING = false;
let globalToken = 0;
let globalPreview = false;

const ASSET_FILTERS = ["all", "online", "offline", "expired", "hosted"];
const FILTER_LABELS = {
  all: "全部", online: "运行中", offline: "已停止", expired: "已到期",
  hosted: "云端托管",
};
const ASSET_FILTER_KEY = "panweb-asset-filter";
const RAIL_TL_KEY = "panweb-rail-timeline";
let assetFilter = ASSET_FILTERS.includes(localStorage.getItem(ASSET_FILTER_KEY))
  ? localStorage.getItem(ASSET_FILTER_KEY) : "all";
let railTimelineOpen = localStorage.getItem(RAIL_TL_KEY) !== "false";

const EVENT_LABELS = {
  publish: "发布", restart: "重建", url_change: "换网址",
  pin_change: "改口令", expire: "到期", stop: "停止", error: "出错",
};

function assetKey(a, hosted) {
  return hosted ? "h:" + a.name : a.id;
}
function allAssets(apps, hosted, snaps) {
  const out = [];
  (apps || []).forEach(a => out.push({a: a, hosted: false, snapshot: false, id: a.id}));
  (snaps || []).forEach(s => out.push({a: s, hosted: false, snapshot: true, id: s.id}));
  (hosted || []).forEach(a => out.push({
    a: a, hosted: true, snapshot: false, id: assetKey(a, true)}));
  return out;
}
function liveAssets() {
  return allAssets(STATE && STATE.apps, STATE && STATE.hosted,
    STATE && STATE.last_deployments);
}
function findAsset(id) {
  for (const x of liveAssets()) {
    if (x.id === id) return x;
  }
  return null;
}
function findAssetByPort(port) {
  return (STATE && STATE.apps || [])
    .find(a => a.kind === "port" && Number(a.port) === Number(port)) || null;
}
function assetStatus(a, hosted, snapshot) {
  if (hosted) return "hosted";
  if (snapshot) {
    return (a.stop_reason === "expired" || a.stop_reason === "invalid_expires_at")
      ? "expired" : "offline";
  }
  if (a.expires_at && a.expires_at < Date.now() / 1000) return "expired";
  return a.alive ? "online" : "offline";
}
function statusText(state) {
  return {all: "全部", online: "运行中", offline: "已停止", expired: "已到期",
    hosted: "云端托管"}[state] || "未知";
}
function lifecycleText(a, hosted, snapshot) {
  if (hosted) return (a.files || 0) + " 文件 · " + (a.updated || "");
  if (snapshot) return "上次 · " + (a.kind === "pages" ? "文件夹 " + a.folder :
    "端口 " + a.port) + " · 停止于 " + eventTime(a.stopped_at);
  if (a.kind === "pages") return "文件夹 " + a.folder;
  return "端口 " + a.port;
}
function assetActivity(x) {
  if (x.snapshot) return Number(x.a.stopped_at) || 0;
  if (x.hosted) return 0;
  const cached = TIMELINE_CACHE[x.a.id];
  if (cached && cached.length) return Number(cached[0].ts) || 0;
  const t = Date.parse((x.a.started || "").replace(" ", "T"));
  return Number.isFinite(t) ? t / 1000 : 0;
}
function sortAssets(assets) {
  return assets.sort((x, y) => (assetActivity(y) - assetActivity(x)) ||
    (x.id < y.id ? -1 : x.id > y.id ? 1 : 0));
}

function setAssetFilter(f) {
  if (!ASSET_FILTERS.includes(f)) return;
  assetFilter = f;
  try { localStorage.setItem(ASSET_FILTER_KEY, f); } catch (e) { /* 忽略 */ }
  syncFilterChips();
  renderAssetList();
}
function syncFilterChips() {
  document.querySelectorAll("#asset-filters .rail-filter").forEach(b => {
    b.setAttribute("aria-pressed",
      b.dataset.filter === assetFilter ? "true" : "false");
  });
}
function clearAssetFilters() {
  const search = document.getElementById("asset-search");
  if (search) search.value = "";
  setAssetFilter("all");
}

function renderWorkbench(apps, hosted) {
  const assets = sortAssets(allAssets(apps, hosted, STATE.last_deployments || []));
  if (!assets.some(x => x.id === selectedAssetId)) {
    selectedAssetId = assets.length ? assets[0].id : null;
  }
  document.getElementById("asset-count").textContent = String(assets.length);
  syncFilterChips();
  renderAssetList();
  if (selectedAssetId && !globalPreview) loadAssetTimeline(selectedAssetId);
  else loadGlobalTimeline();
  if (typeof renderStage === "function") renderStage();
}

function renderAssetList() {
  const box = document.getElementById("asset-list");
  const q = (document.getElementById("asset-search").value || "").trim().toLowerCase();
  const assets = sortAssets(liveAssets());
  if (!assets.length) {
    box.innerHTML = '<div class="rail-empty rail-empty-guide"><b>还没有发布</b>' +
      '<ol class="rail-steps"><li>选择端口或文件夹</li><li>发布并确认能打开</li>' +
      '<li>把链接或二维码发出去</li></ol>' +
      '<div class="rail-empty-actions"><button class="btn btn-sm" type="button" ' +
      'onclick="openPublish(\'port\')">发布端口</button>' +
      '<button class="btn btn-sm ghost" type="button" ' +
      'onclick="scanPorts(\'left\')">扫描本机端口</button></div></div>';
    return;
  }
  const shown = assets.filter(x => {
    const st = assetStatus(x.a, x.hosted, x.snapshot);
    if (assetFilter !== "all" && st !== assetFilter) return false;
    if (!q) return true;
    const a = x.a;
    return [a.name, a.title, a.folder, a.port, a.url, a.share_url, x.id]
      .filter(Boolean).join(" ").toLowerCase().includes(q);
  });
  if (!shown.length) {
    box.innerHTML = '<div class="rail-empty">' + (q
      ? '没有匹配「' + esc(q) + '」的资产（筛选：' + esc(FILTER_LABELS[assetFilter]) + '）。'
      : '当前筛选「' + esc(FILTER_LABELS[assetFilter]) + '」下没有资产。') +
      '<br><button class="btn btn-sm ghost" type="button" onclick="clearAssetFilters()">清除筛选</button></div>';
    return;
  }
  box.innerHTML = shown.map(x => {
    const a = x.a, st = assetStatus(a, x.hosted, x.snapshot);
    const pv = !x.hosted && a.pv ? "PV " + a.pv.total : "";
    const exp = !x.hosted
      ? (x.snapshot ? (a.expires_text || "") : (a.expires_at ? fmtRemain(a.expires_at) : ""))
      : "";
    const active = x.id === selectedAssetId ? " active" : "";
    return '<div class="asset-item' + active + '" data-id="' + esc(x.id) + '" role="button" ' +
      'tabindex="0" onclick="selectAsset(' + jsq(x.id) + ')" ' +
      'onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();selectAsset(' + jsq(x.id) + ')}">' +
      '<span class="asset-dot ' + st + '"></span>' +
      '<span class="asset-body"><span class="asset-name">' + esc(a.title || a.name) + '</span>' +
      '<span class="asset-meta"><span class="asset-state ' + st + '">' + statusText(st) + '</span>' +
      '<span>' + esc(lifecycleText(a, x.hosted, x.snapshot)) + '</span><span>' +
      esc(exp) + '</span></span></span>' +
      '<span class="asset-pv">' + esc(pv) + '</span></div>';
  }).join("");
}

function selectAsset(id) {
  if (!findAsset(id)) return;
  selectedAssetId = id;
  globalPreview = false;
  localStorage.setItem("panweb-selected", id);
  if (typeof stageResetToPreview === "function") stageResetToPreview();
  renderAssetList();
  loadAssetTimeline(id);
  if (typeof renderViz === "function") renderViz();
  if (typeof renderStage === "function") renderStage();
}

function timelineLabel(type) { return EVENT_LABELS[type] || type; }
function renderTimelineEmpty(text) {
  document.getElementById("asset-timeline").innerHTML =
    '<div class="rail-empty">' + esc(text) + '</div>';
}
function eventTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = n => String(n).padStart(2, "0");
  return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
}
function timelineRows(events) {
  return events.map(e => {
    const detail = e.details ? (e.details.url_after || e.details.reason ||
      e.details.port || "") : "";
    return '<div class="tl-item"><span class="tl-time">' + esc(eventTime(e.ts)) +
      '</span><span class="tl-body"><span class="tl-label"><span class="tl-type">' +
      esc(timelineLabel(e.type)) + '</span> · ' + esc(e.summary || "") + '</span>' +
      (detail ? '<span class="tl-detail">' + esc(detail) + '</span>' : "") + '</span></div>';
  }).join("");
}
function renderTimeline(id, events) {
  if (id !== selectedAssetId) return;
  const found = findAsset(id);
  document.getElementById("timeline-scope").textContent =
    (found && (found.a.title || found.a.name)) || "全局";
  if (!events || !events.length) {
    renderTimelineEmpty("这个资产还没有变更记录。");
    return;
  }
  document.getElementById("asset-timeline").innerHTML = timelineRows(events);
}
function renderGlobalTimeline(events) {
  document.getElementById("timeline-scope").textContent = "全局";
  if (!events || !events.length) {
    renderTimelineEmpty("还没有全局变更记录。");
    return;
  }
  document.getElementById("asset-timeline").innerHTML =
    '<div class="tl-scope-note">最近 ' + events.length + ' 条全局变更</div>' +
    timelineRows(events);
}
function loadGlobalTimeline(force = false) {
  if (!force && GLOBAL_TIMELINE) return renderGlobalTimeline(GLOBAL_TIMELINE);
  if (GLOBAL_PENDING) return;
  GLOBAL_PENDING = true;
  const token = ++globalToken;
  renderTimelineEmpty("正在读取全局时间线…");
  api("/api/history?limit=" + GLOBAL_LIMIT).then(d => {
    GLOBAL_PENDING = false;
    if (!d.ok) {
      return renderTimelineEmpty("时间线读取失败：" +
        (d.error ? d.error.message : "未知错误"));
    }
    GLOBAL_TIMELINE = (d.data && d.data.events) || [];
    if (token === globalToken && (globalPreview || !selectedAssetId)) {
      renderGlobalTimeline(GLOBAL_TIMELINE);
    }
  });
}
function showGlobalTimeline() {
  globalPreview = true;
  if (!railTimelineOpen) toggleRailTimeline();
  GLOBAL_TIMELINE = null;
  loadGlobalTimeline(true);
}
function loadAssetTimeline(id, force = false) {
  const found = findAsset(id);
  if (!found) return renderTimelineEmpty("选择左侧资产后显示变更记录。");
  if (found.hosted) {
    renderTimelineEmpty("云端托管没有本机进程时间线。");
    return;
  }
  if (!force && TIMELINE_CACHE[id]) return renderTimeline(id, TIMELINE_CACHE[id]);
  if (TIMELINE_PENDING[id]) return;
  const token = ++timelineToken;
  TIMELINE_PENDING[id] = true;
  renderTimelineEmpty("正在读取时间线…");
  api("/api/history?id=" + encodeURIComponent(id) + "&limit=20").then(d => {
    TIMELINE_PENDING[id] = false;
    if (!d.ok) return renderTimelineEmpty("时间线读取失败：" +
      (d.error ? d.error.message : "未知错误"));
    TIMELINE_CACHE[id] = d.data.events || [];
    DETAIL_CACHE[id] = d.data.detail || null;
    if (token === timelineToken) {
      renderTimeline(id, TIMELINE_CACHE[id]);
      renderAssetList();
    }
    if (typeof renderViz === "function") renderViz();
  });
}
function reloadTimeline() {
  GLOBAL_TIMELINE = null;
  if (selectedAssetId && !globalPreview) loadAssetTimeline(selectedAssetId, true);
  else loadGlobalTimeline(true);
}

// ---------- 时间线折叠（只存布尔）----------
function applyRailTimeline() {
  const btn = document.getElementById("rail-timeline-btn");
  const body = document.getElementById("asset-timeline");
  if (!btn || !body) return;
  btn.setAttribute("aria-expanded", railTimelineOpen ? "true" : "false");
  body.hidden = !railTimelineOpen;
}
function toggleRailTimeline() {
  railTimelineOpen = !railTimelineOpen;
  try {
    localStorage.setItem(RAIL_TL_KEY, railTimelineOpen ? "true" : "false");
  } catch (e) { /* 忽略 */ }
  applyRailTimeline();
  if (railTimelineOpen) reloadTimeline();
}

// ---------- 空态：扫描本机端口 ----------
function scanCandidateHtml(c) {
  const port = Number(c.port);
  if (!port) return "";
  const meta = [c.title, c.process].filter(Boolean).join(" · ") || "未知应用";
  const used = c.published ? '<span class="scan-tag">已发布</span>' : "";
  return '<button type="button" class="scan-item" onclick="openPublishPort(' + port +
    ')" aria-label="在新建表单中发布端口 ' + port + '">' +
    '<b>:' + esc(String(port)) + "</b><span>" + esc(meta) + "</span>" + used + "</button>";
}
async function scanPorts(target) {
  const holderId = target === "guide" ? "guide-results" :
    (target === "viz" ? "viz-empty" : "asset-list");
  const holder = document.getElementById(holderId);
  if (!holder) return;
  if (target === "viz") {
    holder.innerHTML = "<b>扫描本机端口</b><p>正在检查…</p>";
  } else {
    holder.innerHTML = '<div class="rail-empty">正在扫描本机监听端口…</div>';
  }
  const d = await api("/api/discover");
  if (!d.ok) {
    const msg = (d.error && d.error.message) || "扫描失败";
    if (target === "viz") {
      holder.innerHTML = "<b>扫描失败</b><p>" + esc(msg) + "</p>" +
        '<button class="btn btn-sm" type="button" onclick="scanPorts(\'viz\')">重试</button>';
    } else {
      holder.innerHTML = '<div class="rail-empty">扫描失败：' + esc(msg) +
        '<br><button class="btn btn-sm ghost" type="button" onclick="scanPorts(\'' +
        target + '\')">重试</button></div>';
    }
    return;
  }
  const list = (d.data && d.data.candidates) || [];
  const items = list.map(scanCandidateHtml).filter(Boolean).join("");
  const body = items || '<div class="rail-empty">没有发现可发布的本机端口。</div>';
  if (target === "viz") {
    holder.innerHTML = "<b>发现 " + list.length + " 个端口</b>" +
      '<p class="scan-note">点击端口会填入中栏新建表单。</p>' +
      '<div class="scan-list">' + body + "</div>" +
      '<button class="btn btn-sm ghost" type="button" onclick="scanPorts(\'viz\')">重新扫描</button>';
  } else {
    holder.innerHTML = '<div class="rail-empty"><b>发现 ' + list.length +
      ' 个端口</b><div class="scan-list">' + body + "</div>" +
      '<button class="btn btn-sm ghost" type="button" onclick="scanPorts(\'' +
      target + '\')">重新扫描</button></div>';
  }
}

// ---------- 抽屉 / 视口 ----------
function openRail() {
  document.body.classList.remove("viz-open");
  document.body.classList.add("rail-open");
  if (typeof tmFitSoon === "function") setTimeout(tmFitSoon, 260);
}
function openViz() {
  document.body.classList.remove("rail-open");
  document.body.classList.add("viz-open");
  if (typeof tmFitSoon === "function") setTimeout(tmFitSoon, 260);
}
function closeDrawers() {
  document.body.classList.remove("rail-open", "viz-open");
  if (typeof tmFitSoon === "function") setTimeout(tmFitSoon, 260);
}
document.getElementById("asset-search").addEventListener("input", renderAssetList);
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeDrawers();
});
applyRailTimeline();
syncFilterChips();
