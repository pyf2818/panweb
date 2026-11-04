// ---------- 右栏：进程可视化（只消费 /api/state 与历史缓存） ----------
const VIZ_EMPTY_DEFAULT = "<b>等待选择资产</b><p>从左侧选择一个应用，这里会显示内置代理、cloudflared 隧道与源应用的实时状态。</p>";
const NODE_DEFAULT = {state: "unknown", detail: "暂无数据"};

function setVizNode(key, node) {
  const el = document.getElementById("viz-node-" + key);
  const data = node || NODE_DEFAULT;
  el.className = "viz-node " + (data.state || "unknown");
  el.querySelector(".viz-detail").textContent = data.detail || "未知";
}
function setVizLink(id, flowing) {
  document.getElementById(id).classList.toggle("flow", !!flowing);
}
function fmtVisitTime(ts) {
  if (!ts) return "暂无";
  const d = new Date(ts * 1000);
  const p = n => String(n).padStart(2, "0");
  return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
}
function rebuildCount(id) {
  if (!TIMELINE_CACHE[id]) return null;
  return TIMELINE_CACHE[id].filter(e => e.type === "restart" ||
    e.type === "url_change").length;
}

function renderViz() {
  const empty = document.getElementById("viz-empty");
  const panel = document.getElementById("viz-panel");
  const found = findAsset(selectedAssetId);
  if (!found) {
    empty.hidden = false;
    empty.innerHTML = VIZ_EMPTY_DEFAULT;
    panel.hidden = true;
    return;
  }
  if (found.hosted) {
    empty.hidden = false;
    empty.innerHTML = "<b>云端托管</b><p>这个资产不在这台电脑上运行，没有本机代理 / 隧道 / 源应用节点。</p>";
    panel.hidden = true;
    return;
  }
  empty.hidden = true;
  panel.hidden = false;

  const a = found.a;
  document.getElementById("viz-name").textContent = a.title || a.name || "—";
  document.getElementById("viz-url").textContent = a.url || "尚未生成公网网址";

  const expired = a.expires_at && a.expires_at < Date.now() / 1000;
  const badge = document.getElementById("viz-status");
  if (expired) {
    badge.textContent = "已到期";
    badge.className = "viz-badge expired";
  } else if (a.alive) {
    badge.textContent = "在线";
    badge.className = "viz-badge online";
  } else {
    badge.textContent = "已停止";
    badge.className = "viz-badge offline";
  }

  const nodes = a.nodes || {};
  setVizNode("proxy", nodes.proxy);
  setVizNode("tunnel", nodes.tunnel);
  setVizNode("source", nodes.source);
  setVizLink("viz-link-proxy", !!(nodes.proxy && nodes.proxy.state === "online" &&
    nodes.tunnel && nodes.tunnel.state === "online"));
  setVizLink("viz-link-source", !!(nodes.tunnel && nodes.tunnel.state === "online" &&
    nodes.source && nodes.source.state === "online"));

  const pv = a.pv || null;
  document.getElementById("viz-pv").textContent = pv ? String(pv.total) : "未知";
  document.getElementById("viz-uv").textContent = pv ? String(pv.uv) : "未知";
  document.getElementById("viz-last").textContent = pv ? fmtVisitTime(pv.last) : "未知";
  const rebuilds = rebuildCount(a.id);
  document.getElementById("viz-rebuilds").textContent =
    rebuilds === null ? "未知" : String(rebuilds);

  const visits = (STATE && STATE.visits_recent || []).filter(v => v.id === a.id);
  const vbox = document.getElementById("viz-visitors");
  vbox.innerHTML = visits.length ? visits.slice(0, 8).map(v => {
    return '<div class="viz-visitor"><span class="v-name">' + esc(v.name || "应用") +
      " · " + esc(v.path || "/") + "</span><span class=\"v-meta\">" +
      esc(v.device || "") + (v.browser ? "/" + esc(v.browser) : "") +
      " · " + esc(fmtVisitTime(v.ts)) + "</span></div>";
  }).join("") : '<div class="rail-empty">暂无最近访客</div>';
}

// 页面不可见时不再让装饰动效耗电；低性能设备直接静态化
document.addEventListener("visibilitychange", () => {
  document.body.classList.toggle("page-hidden", document.hidden);
});
if (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4) {
  document.body.classList.add("low-power");
}
