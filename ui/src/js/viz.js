// ---------- 右栏：部署详情（只消费 /api/state 与 /api/history） ----------
const NODE_DEFAULT = {state: "unknown", detail: "暂无数据"};
const DETAIL_CACHE = {};
let VIZ_QR_URL = "";
let VIZ_VISITS_ID = "";

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

function vizSubject() {
  const snap = typeof currentSnapshot === "function" ? currentSnapshot() : null;
  if (snap) return {snap: snap, detail: DETAIL_CACHE[snap.id]};
  const a = currentAsset();
  return a ? {a: a, detail: DETAIL_CACHE[a.id]} : null;
}

function subjectUrl(subject) {
  const {a, snap, detail} = subject;
  return (snap && snap.url) || (a && a.url) || (detail && detail.url) || "";
}
function subjectShare(subject) {
  const {a, snap, detail} = subject;
  return (snap && snap.share_url) || (a && a.share_url) ||
    (detail && detail.share_url) || "";
}

function renderBase(subject, badgeText, badgeClass, subText) {
  document.getElementById("viz-name").textContent =
    (subject.snap && subject.snap.title) || (subject.a && (subject.a.title || subject.a.name)) || "—";
  document.getElementById("viz-url").textContent =
    subjectUrl(subject) || "尚未生成公网网址";
  document.getElementById("viz-sub").textContent = subText || "—";
  document.getElementById("viz-status").textContent = badgeText;
  document.getElementById("viz-status").className = "viz-badge " + (badgeClass || "");
}

function renderLinks(subject) {
  const url = subjectUrl(subject);
  const share = subjectShare(subject);
  document.getElementById("dep-url").textContent = url || "尚未生成";
  const shareRow = document.getElementById("dep-share-row");
  document.getElementById("dep-share-url").textContent = share || "未生成分享页";
  shareRow.classList.toggle("is-empty", !share);
  shareRow.querySelectorAll("button").forEach(b => { b.disabled = !share; });
  drawVizQr(subject);
}

function renderHistoryLinks(detail) {
  const links = document.getElementById("dep-links");
  if (detail === undefined) {
    links.innerHTML = '<div class="rail-empty">读取中…</div>';
    return;
  }
  if (!detail || !detail.links || !detail.links.length) {
    links.innerHTML = '<div class="rail-empty">还没有历史链接，重建后旧网址会记录在这里。</div>';
    return;
  }
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

function renderStatusFields(f) {
  document.getElementById("dep-pin").textContent = f.pinned ? "需要口令" : "无口令";
  document.getElementById("dep-exp").textContent = f.exp || "未知";
  document.getElementById("dep-pub").textContent = f.pub || "未知";
  document.getElementById("viz-pv").textContent = f.pv ? String(f.pv.total) : "未知";
  document.getElementById("viz-uv").textContent = f.pv ? String(f.pv.uv) : "未知";
  document.getElementById("viz-last").textContent = f.pv ? fmtVisitTime(f.pv.last) : "未知";
  document.getElementById("viz-rebuilds").textContent =
    f.count === null || f.count === undefined ? "未知" : String(f.count);
  document.getElementById("dep-last-rebuild").textContent = f.lastRebuild || "未知";
  const stoppedRow = document.getElementById("dep-stopped-row");
  stoppedRow.hidden = !f.stoppedAt;
  document.getElementById("dep-stopped-at").textContent = f.stoppedAt || "未知";
}

function renderDeployment(a) {
  const detail = DETAIL_CACHE[a.id];
  renderLinks({a: a, detail: detail});
  renderStatusFields({
    pinned: !!a.pinned,
    exp: fmtRemain(a.expires_at),
    pub: a.started || (detail && detail.published_at) || "未知",
    pv: a.proxy_port ? a.pv : null,
    count: detail ? detail.rebuild_count : rebuildCount(a.id),
    lastRebuild: detail
      ? (detail.last_rebuild_at ? fmtVisitTime(detail.last_rebuild_at) : "暂无")
      : "未知",
    stoppedAt: "",
  });
  renderHistoryLinks(detail);
  loadVizVisits(a.id);
}

function drawVizQr(subject) {
  const holder = document.getElementById("viz-qr");
  const share = subjectShare(subject);
  const target = share || subjectUrl(subject);
  document.getElementById("dep-qr-target").textContent =
    target ? (share ? "扫码打开分享页" : "扫码打开应用") : "未生成网址";
  if (!target || !window.qrcode) {
    holder.innerHTML = '<div class="rail-empty">—</div>';
    return;
  }
  if (VIZ_QR_URL === target && holder.innerHTML) return;
  VIZ_QR_URL = target;
  holder.innerHTML = qrSvg(target, 3, 2);
  holder.title = target;
}

function qrSvg(url, cell, margin) {
  const q = qrcode(0, "M");
  q.addData(url);
  q.make();
  return q.createSvgTag({cellSize: cell, margin: margin, scalable: true});
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
   "viz-uv", "viz-last", "viz-rebuilds", "dep-last-rebuild", "viz-name",
   "viz-url", "viz-sub"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = "—";
  });
  document.getElementById("dep-share-row").classList.add("is-empty");
  document.getElementById("dep-stopped-row").hidden = true;
  document.getElementById("dep-stopped-note").hidden = true;
  document.getElementById("dep-links").innerHTML =
    '<div class="rail-empty">还没有历史链接。</div>';
  const qr = document.getElementById("viz-qr");
  qr.innerHTML = "";
  qr.title = "";
  document.getElementById("dep-qr-target").textContent = "—";
  VIZ_QR_URL = "";
  document.getElementById("viz-visitors").innerHTML =
    '<div class="rail-empty">展开后读取最近访客。</div>';
  document.getElementById("dep-visitors-note").textContent = "近 24 小时";
  VIZ_VISITS_ID = "";
  document.getElementById("viz-status").textContent = "未知";
  document.getElementById("viz-status").className = "viz-badge";
}

function resetActions() {
  const rep = document.getElementById("dep-republish-btn");
  rep.hidden = true;
  ["dep-stop-btn", "dep-retry-btn", "dep-check-btn", "dep-pin-btn"].forEach(id => {
    const el = document.getElementById(id);
    el.disabled = false;
    el.removeAttribute("title");
  });
  document.getElementById("dep-check-btn").textContent = "重新自检";
  document.getElementById("dep-pin-btn").textContent = "改口令";
  document.getElementById("viz-pin-input").placeholder = "新口令；留空提交=移除";
  document.getElementById("dep-act-hint").textContent =
    "口令只作为一次请求参数；详情仅显示「需要 / 无」，不会回显明文。";
}

function setActionsDisabled(reason) {
  ["dep-stop-btn", "dep-retry-btn", "dep-check-btn"].forEach(id => {
    const el = document.getElementById(id);
    el.disabled = true;
    el.title = reason;
  });
}

function renderVizEmpty(html) {
  const empty = document.getElementById("viz-empty");
  empty.hidden = false;
  empty.innerHTML = html;
  document.getElementById("viz-panel").hidden = true;
  clearDeployment();
}

function renderViz() {
  resetActions();
  const found = findAsset(selectedAssetId);
  if (!found) {
    renderVizEmpty("<b>等待选择资产</b><p>从左侧选择一个应用或网页，这里会显示链接、二维码、历史网址、状态与操作。</p>" +
      '<button class="btn btn-sm" type="button" onclick="scanPorts(\'viz\')">扫描本机端口</button>');
    return;
  }
  if (found.hosted) {
    renderVizEmpty("<b>云端托管</b><p>这个资产不在这台电脑上运行，没有本机代理 / 隧道 / 源应用节点。</p>");
    return;
  }
  if (found.snapshot) {
    renderStopped(found.a);
    return;
  }
  const a = found.a;
  document.getElementById("viz-empty").hidden = true;
  document.getElementById("viz-panel").hidden = false;
  const expired = a.expires_at && a.expires_at < Date.now() / 1000;
  renderBase({a: a, detail: DETAIL_CACHE[a.id]},
    expired ? "已到期" : (a.alive ? "在线" : "已停止"),
    expired ? "expired" : (a.alive ? "online" : "offline"),
    (a.alive ? "当前发布 · 运行中" : "当前发布 · 进程失联，可重试通道") +
      " · " + (a.kind === "pages" ? "文件夹" : "端口"));
  renderDeployment(a);

  const nodes = a.nodes || {};
  setVizNode("proxy", nodes.proxy);
  setVizNode("tunnel", nodes.tunnel);
  setVizNode("source", nodes.source);
  setVizLink("viz-link-proxy", !!(nodes.proxy && nodes.proxy.state === "online" &&
    nodes.tunnel && nodes.tunnel.state === "online"));
  setVizLink("viz-link-source", !!(nodes.tunnel && nodes.tunnel.state === "online" &&
    nodes.source && nodes.source.state === "online"));
  if (VISITS_LOADED.has(a.id)) renderVizVisitors(a.id);
}

function currentAsset() {
  const found = findAsset(selectedAssetId);
  return found && !found.hosted && !found.snapshot ? found.a : null;
}

function vizStop() {
  const a = currentAsset();
  if (!a) return;
  askStop(a.id, a.title || a.name || a.id);
}

function vizCheck() {
  const snap = typeof currentSnapshot === "function" ? currentSnapshot() : null;
  if (snap) return vizCheckSource(snap);
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
  const snap = typeof currentSnapshot === "function" ? currentSnapshot() : null;
  if (snap) return vizRepublish();
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
  const subject = vizSubject();
  if (!subject) return;
  const target = subjectShare(subject) || subjectUrl(subject);
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
  const subject = vizSubject();
  if (!subject) return;
  const target = subjectShare(subject) || subjectUrl(subject);
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
    const id = (subject.a && subject.a.id) || (subject.snap && subject.snap.id) || "app";
    link.download = "panweb-qr-" + id + ".png";
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
