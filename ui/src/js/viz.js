// ---------- 右栏：部署详情（只消费 /api/state 与 /api/history） ----------
const VIZ_EMPTY_DEFAULT = "<b>等待选择资产</b><p>从左侧选择一个应用或网页，这里会显示链接、二维码、历史网址、状态与操作。</p>";
const NODE_DEFAULT = {state: "unknown", detail: "暂无数据"};
const DETAIL_CACHE = {};
let VIZ_QR_URL = "";

function fmtRemain(expiresAt) {
  if (!expiresAt) return "永久";
  const sec = Math.floor(expiresAt - Date.now() / 1000);
  if (sec <= 0) return "已到期";
  const days = Math.floor(sec / 86400);
  const hours = Math.floor((sec % 86400) / 3600);
  const minutes = Math.floor((sec % 3600) / 60);
  if (days) return "剩余 " + days + " 天 " + hours + " 小时";
  if (hours) return "剩余 " + hours + " 小时 " + minutes + " 分";
  return "剩余 " + Math.max(1, minutes) + " 分钟";
}

function renderDeployment(a) {
  const detail = DETAIL_CACHE[a.id];
  const url = a.url || (detail && detail.url) || "";
  const share = a.share_url || (detail && detail.share_url) || "";
  document.getElementById("dep-url").textContent = url || "尚未生成";
  const shareRow = document.getElementById("dep-share-row");
  document.getElementById("dep-share-url").textContent = share || "未生成分享页";
  shareRow.classList.toggle("is-empty", !share);
  shareRow.querySelectorAll("button").forEach(b => { b.disabled = !share; });

  document.getElementById("dep-pin").textContent = a.pinned ? "需要口令" : "无口令";
  document.getElementById("dep-exp").textContent = fmtRemain(a.expires_at);
  document.getElementById("dep-pub").textContent =
    a.started || (detail && detail.published_at) || "未知";
  const pv = a.proxy_port ? a.pv : null;
  document.getElementById("viz-pv").textContent = pv ? String(pv.total) : "未知";
  document.getElementById("viz-uv").textContent = pv ? String(pv.uv) : "未知";
  document.getElementById("viz-last").textContent = pv ? fmtVisitTime(pv.last) : "未知";
  const count = detail ? detail.rebuild_count : rebuildCount(a.id);
  document.getElementById("viz-rebuilds").textContent =
    count === null || count === undefined ? "未知" : String(count);
  document.getElementById("dep-last-rebuild").textContent = detail
    ? (detail.last_rebuild_at ? fmtVisitTime(detail.last_rebuild_at) : "暂无")
    : "未知";

  const links = document.getElementById("dep-links");
  if (detail === undefined) {
    links.innerHTML = '<div class="rail-empty">读取中…</div>';
  } else if (!detail || !detail.links || !detail.links.length) {
    links.innerHTML = '<div class="rail-empty">还没有历史链接，重建后旧网址会记录在这里。</div>';
  } else {
    links.innerHTML = detail.links.map(l => {
      const current = l.status === "current";
      const tag = current ? "当前" : "已失效";
      const when = current ? "" : fmtVisitTime(l.ts);
      return '<div class="dep-link-item ' + (current ? "current" : "") + '">' +
        '<div class="dep-link-tag"><span class="tag-' + (current ? "current" : "expired") +
        '">' + tag + "</span>" + (when ? "<span>" + esc(when) + "</span>" : "") +
        '<button class="dep-cp" onclick="copyText(' + jsq(l.url) + ')">复制</button></div>' +
        '<div class="u">' + esc(l.url) + "</div></div>";
    }).join("");
  }
  drawVizQr(a, detail);
}

function qrTarget(a, detail) {
  return (detail && detail.share_url) || a.share_url ||
    (detail && detail.url) || a.url || "";
}

function qrSvg(url, cell, margin) {
  const q = qrcode(0, "M");
  q.addData(url);
  q.make();
  return q.createSvgTag({cellSize: cell, margin: margin, scalable: true});
}

function drawVizQr(a, detail) {
  const holder = document.getElementById("viz-qr");
  const target = qrTarget(a, detail);
  document.getElementById("dep-qr-target").textContent =
    target ? (a.share_url || (detail && detail.share_url) ? "扫码打开分享页" : "扫码打开应用") : "未生成网址";
  if (!target || !window.qrcode) {
    holder.innerHTML = '<div class="rail-empty">—</div>';
    return;
  }
  if (VIZ_QR_URL === target && holder.innerHTML) return;
  VIZ_QR_URL = target;
  holder.innerHTML = qrSvg(target, 3, 2);
  holder.title = target;
}

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

function clearDeployment() {
  ["dep-url", "dep-share-url", "dep-pin", "dep-exp", "dep-pub", "viz-pv",
   "viz-uv", "viz-last", "viz-rebuilds", "dep-last-rebuild", "viz-name", "viz-url"]
    .forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = "—";
    });
  document.getElementById("dep-share-row").classList.add("is-empty");
  document.getElementById("dep-links").innerHTML =
    '<div class="rail-empty">还没有历史链接。</div>';
  const qr = document.getElementById("viz-qr");
  qr.innerHTML = "";
  qr.title = "";
  document.getElementById("dep-qr-target").textContent = "—";
  VIZ_QR_URL = "";
  document.getElementById("viz-status").textContent = "未知";
  document.getElementById("viz-status").className = "viz-badge";
}

function renderViz() {
  const empty = document.getElementById("viz-empty");
  const panel = document.getElementById("viz-panel");
  const found = findAsset(selectedAssetId);
  if (!found) {
    empty.hidden = false;
    empty.innerHTML = VIZ_EMPTY_DEFAULT;
    clearDeployment();
    panel.hidden = true;
    return;
  }
  if (found.hosted) {
    empty.hidden = false;
    empty.innerHTML = "<b>云端托管</b><p>这个资产不在这台电脑上运行，没有本机代理 / 隧道 / 源应用节点。</p>";
    clearDeployment();
    panel.hidden = true;
    return;
  }
  empty.hidden = true;
  panel.hidden = false;

  const a = found.a;
  document.getElementById("viz-name").textContent = a.title || a.name || "—";
  document.getElementById("viz-url").textContent = a.url || "尚未生成公网网址";
  renderDeployment(a);

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
}

function currentAsset() {
  const found = findAsset(selectedAssetId);
  return found && !found.hosted ? found.a : null;
}

function vizStop() {
  const a = currentAsset();
  if (!a) return;
  askStop(a.id, a.title || a.name || a.id);
}

function vizCheck() {
  const a = currentAsset();
  if (!a) return;
  doCheck({id: a.id});
}

async function vizRetry() {
  const a = currentAsset();
  if (!a) return;
  if (commandBusy) return toast("有指令正在执行，稍后再试", false);
  setCommandBusy(true);
  addStep("正在检查失联通道并尝试恢复…");
  try {
    const start = await api("/api/recover", {});
    if (!start.ok) {
      const err = start.error || {};
      return addError(err.message || "恢复任务启动失败", err.hint || "稍后重试", null);
    }
    const jobId = start.data && start.data.job;
    for (let i = 0; i < 600; i++) {
      await sleep(700);
      const d = await api("/api/job?id=" + encodeURIComponent(jobId));
      if (!d.ok) return addError("任务读取失败", "控制台可能已重启", null);
      const job = d.data || {};
      if (!job.done) continue;
      if (!job.ok) {
        const err = job.error || {};
        return addError(err.message || "恢复失败", err.hint || "稍后重试", null);
      }
      const result = job.result || {};
      const n = (result.recovered || []).length;
      addResult("<b>通道检查完成</b><div class=\"err-hint\">检查 " +
        esc(String(result.checked || 0)) + " 个异常条目，恢复 " + esc(String(n)) +
        " 个" + (n ? "；网址可能已更新，详情已刷新" : "；当前条目无需重建") + "</div>");
      await refresh(true);
      reloadTimeline();
      return;
    }
    addError("等待超时", "恢复仍在后台运行，稍后刷新状态。", null);
  } finally {
    setCommandBusy(false);
  }
}

async function vizSetPin() {
  const a = currentAsset();
  if (!a) return;
  const input = document.getElementById("viz-pin-input");
  const pin = (input.value || "").trim();
  if (pin && pin.length < 4) {
    input.value = "";
    return addError("口令太短", "至少 4 位；留空表示移除口令", null);
  }
  if (!pin && !confirm("留空会移除访问口令，网址将变为公开。确定继续？")) return;
  if (commandBusy) return toast("有指令正在执行，稍后再试", false);
  setCommandBusy(true);
  addStep(pin ? "正在更新访问口令…" : "正在移除访问口令…");
  input.value = "";
  try {
    const d = await api("/api/pin", {id: a.id, pin: pin || null});
    if (!d.ok) {
      const err = d.error || {};
      return addError(err.message || "改口令失败", err.hint || "稍后重试", null);
    }
    const next = (d.data && d.data.entry) || {};
    const changed = next.url && a.url && next.url !== a.url;
    addResult("<b>口令已" + (pin ? "更新" : "移除") + "</b>" +
      (changed ? "<div class=\"err-hint\">公网网址已变化，旧网址已记入历史链接。</div>" : ""));
    await refresh(true);
    reloadTimeline();
  } finally {
    setCommandBusy(false);
  }
}

function openQrZoom() {
  const a = currentAsset();
  if (!a) return;
  const target = qrTarget(a, DETAIL_CACHE[a.id]);
  if (!target || !window.qrcode) return;
  const holder = document.getElementById("qr-zoom");
  holder.innerHTML = qrSvg(target, 8, 4);
  document.getElementById("qr-target-url").textContent = target;
  document.getElementById("qr-overlay").classList.add("show");
}

function closeQrZoom() {
  document.getElementById("qr-overlay").classList.remove("show");
}

function downloadVizQr() {
  const a = currentAsset();
  if (!a) return;
  const target = qrTarget(a, DETAIL_CACHE[a.id]);
  if (!target || !window.qrcode) return toast("还没有可下载的二维码", false);
  const q = qrcode(0, "M");
  q.addData(target);
  q.make();
  const cell = 8, margin = 3, count = q.getModuleCount();
  const size = (count + margin * 2) * cell;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, size, size);
  ctx.fillStyle = "#000";
  for (let r = 0; r < count; r++) {
    for (let c = 0; c < count; c++) {
      if (q.isDark(r, c)) ctx.fillRect((c + margin) * cell, (r + margin) * cell, cell, cell);
    }
  }
  canvas.toBlob(blob => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "panweb-qr-" + (a.id || "app") + ".png";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1500);
  }, "image/png");
}

document.addEventListener("keydown", e => {
  if (e.key === "Escape") closeQrZoom();
});

// 页面不可见时不再让装饰动效耗电；低性能设备直接静态化
document.addEventListener("visibilitychange", () => {
  document.body.classList.toggle("page-hidden", document.hidden);
});
if (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4) {
  document.body.classList.add("low-power");
}
