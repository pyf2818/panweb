// ---------- 左栏：资产档案 + 时间线 ----------
let selectedAssetId = localStorage.getItem("panweb-selected") || null;
const TIMELINE_CACHE = {};
const TIMELINE_PENDING = {};
let timelineToken = 0;

const EVENT_LABELS = {
  publish: "发布", restart: "重建", url_change: "换网址",
  pin_change: "改口令", expire: "到期", stop: "停止", error: "出错",
};

function assetKey(a, hosted) {
  return hosted ? "h:" + a.name : a.id;
}
function allAssets(apps, hosted) {
  return [{list: apps || [], hosted: false}, {list: hosted || [], hosted: true}]
    .flatMap(g => g.list.map(a => ({a, hosted: g.hosted, id: assetKey(a, g.hosted)})));
}
function findAsset(id) {
  for (const x of allAssets(STATE && STATE.apps, STATE && STATE.hosted)) {
    if (x.id === id) return x;
  }
  return null;
}
function findAssetByPort(port) {
  return (STATE && STATE.apps || []).find(a => Number(a.target) === Number(port)) || null;
}
function assetStatus(a, hosted) {
  if (hosted) return "hosted";
  if (a.expires_at && a.expires_at < Date.now() / 1000) return "expired";
  return a.alive ? "online" : "offline";
}
function statusText(state) {
  return {online: "运行中", offline: "已停止", expired: "已到期", hosted: "云端托管"}[state] || "未知";
}
function lifecycleText(a, hosted) {
  if (hosted) return (a.files || 0) + " 文件 · " + (a.updated || "");
  if (a.kind === "pages") return "文件夹 " + a.target;
  return "端口 " + a.target;
}

function renderWorkbench(apps, hosted) {
  const assets = allAssets(apps, hosted);
  if (!assets.some(x => x.id === selectedAssetId)) {
    selectedAssetId = assets.length ? assets[0].id : null;
  }
  document.getElementById("asset-count").textContent = String(assets.length);
  renderAssetList();
  if (selectedAssetId) loadAssetTimeline(selectedAssetId);
  else renderTimelineEmpty("还没有资产。输入「发布 3000」或点击「高级发布」。");
}

function renderAssetList() {
  const box = document.getElementById("asset-list");
  const q = (document.getElementById("asset-search").value || "").trim().toLowerCase();
  const assets = allAssets(STATE && STATE.apps, STATE && STATE.hosted);
  const shown = assets.filter(x => {
    if (!q) return true;
    const a = x.a;
    return [a.name, a.title, a.target, a.url, a.share_url, x.id]
      .filter(Boolean).join(" ").toLowerCase().includes(q);
  });
  if (!assets.length) {
    box.innerHTML = '<div class="rail-empty">还没有发布。<br><button class="btn btn-sm" ' +
      'onclick="openPublish(\'port\')">高级发布</button></div>';
    return;
  }
  if (!shown.length) {
    box.innerHTML = '<div class="rail-empty">没有匹配「' + esc(q) + '」的资产。</div>';
    return;
  }
  box.innerHTML = shown.map(x => {
    const a = x.a, st = assetStatus(a, x.hosted);
    const pv = !x.hosted && a.pv ? "PV " + a.pv.total : "";
    const exp = !x.hosted && a.expires_at ? " · " + fmtRemain(a.expires_at) : "";
    const active = x.id === selectedAssetId ? " active" : "";
    return '<div class="asset-item' + active + '" data-id="' + esc(x.id) + '" role="button" ' +
      'tabindex="0" onclick="selectAsset(' + jsq(x.id) + ')" ' +
      'onkeydown="if(event.key===\'Enter\'||event.key===\' \'){event.preventDefault();selectAsset(' + jsq(x.id) + ')}">' +
      '<span class="asset-dot ' + st + '"></span>' +
      '<span class="asset-body"><span class="asset-name">' + esc(a.title || a.name) + '</span>' +
      '<span class="asset-meta"><span class="asset-state ' + st + '">' + statusText(st) + '</span>' +
      '<span>' + esc(lifecycleText(a, x.hosted)) + '</span><span>' + esc(exp) + '</span></span></span>' +
      '<span class="asset-pv">' + esc(pv) + '</span></div>';
  }).join("");
}

function selectAsset(id) {
  if (!findAsset(id)) return;
  selectedAssetId = id;
  localStorage.setItem("panweb-selected", id);
  renderAssetList();
  loadAssetTimeline(id);
  if (typeof renderViz === "function") renderViz();
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
function renderTimeline(id, events) {
  if (id !== selectedAssetId) return;
  if (!events || !events.length) {
    renderTimelineEmpty("这个资产还没有变更记录。");
    return;
  }
  document.getElementById("asset-timeline").innerHTML = events.map(e => {
    const detail = e.details ? (e.details.url_after || e.details.reason || e.details.port || "") : "";
    return '<div class="tl-item"><span class="tl-time">' + esc(eventTime(e.ts)) + '</span>' +
      '<span class="tl-body"><span class="tl-label"><span class="tl-type">' +
      esc(timelineLabel(e.type)) + '</span> · ' + esc(e.summary || "") + '</span>' +
      (detail ? '<span class="tl-detail">' + esc(detail) + '</span>' : "") + '</span></div>';
  }).join("");
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
    if (token === timelineToken) renderTimeline(id, TIMELINE_CACHE[id]);
    if (typeof renderViz === "function") renderViz();
  });
}
function reloadTimeline() {
  if (selectedAssetId) loadAssetTimeline(selectedAssetId, true);
}

// ---------- 抽屉 / 视口 ----------
function openRail() {
  document.body.classList.remove("viz-open");
  document.body.classList.add("rail-open");
}
function openViz() {
  document.body.classList.remove("rail-open");
  document.body.classList.add("viz-open");
}
function closeDrawers() {
  document.body.classList.remove("rail-open", "viz-open");
}
document.getElementById("asset-search").addEventListener("input", renderAssetList);
document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeDrawers();
});
