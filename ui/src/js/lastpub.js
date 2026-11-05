// ---------- 右栏：已停止/已到期条目的上次发布快照与重发 ----------
function currentSnapshot() {
  if (!selectedAssetId || !Array.isArray(STATE.last_deployments)) return null;
  return STATE.last_deployments.find(s => s.id === selectedAssetId) || null;
}

function snapStopLabel(reason) {
  if (reason === "expired") return "有效期到期，自动收回";
  if (reason === "invalid_expires_at") return "有效期字段损坏，按到期收回";
  if (reason === "cleanup") return "长时间离线，自动清理";
  return "手动停止";
}

function renderStopped(snap) {
  const detail = DETAIL_CACHE[snap.id];
  const expired = snap.stop_reason === "expired" ||
    snap.stop_reason === "invalid_expires_at";
  document.getElementById("viz-empty").hidden = true;
  document.getElementById("viz-panel").hidden = false;
  renderBase({snap: snap, detail: detail},
    expired ? "已到期" : "已停止", expired ? "expired" : "offline",
    "上次发布 · " + (snap.kind === "pages"
      ? "文件夹 " + (snap.folder || "未知")
      : "端口 " + (snap.port || "未知")));
  renderLinks({snap: snap, detail: detail});
  renderStatusFields({
    pinned: !!snap.pinned,
    exp: snap.expires_text || fmtRemain(snap.expires_at),
    pub: snap.started || "未知",
    pv: snap.pv,
    count: detail ? detail.rebuild_count : null,
    lastRebuild: detail && detail.last_rebuild_at
      ? fmtVisitTime(detail.last_rebuild_at) : "未知",
    stoppedAt: snap.stopped_at ? fmtVisitTime(snap.stopped_at) : "未知",
  });
  renderHistoryLinks(detail);

  const note = document.getElementById("dep-stopped-note");
  note.hidden = false;
  note.innerHTML = "<b>上次发布已停止</b><div>停止于 " +
    esc(fmtVisitTime(snap.stopped_at)) + " · " + esc(snapStopLabel(snap.stop_reason)) +
    "。链接已不可访问，可以用同样配置重新发布。</div>";

  const rep = document.getElementById("dep-republish-btn");
  rep.hidden = false;
  rep.disabled = false;
  const stopBtn = document.getElementById("dep-stop-btn");
  stopBtn.disabled = true;
  stopBtn.title = "条目已停止，重新发布后才能停止";
  const retryBtn = document.getElementById("dep-retry-btn");
  retryBtn.disabled = true;
  retryBtn.title = "条目已停止，重新发布后才能重试通道";
  const checkBtn = document.getElementById("dep-check-btn");
  checkBtn.textContent = "检查源状态";
  checkBtn.title = "检查源端口或文件夹是否仍在（不代表旧链接可访问）";
  document.getElementById("dep-pin-btn").textContent = "重发并设口令";
  document.getElementById("viz-pin-input").placeholder = "重发时的新口令（可选）";
  document.getElementById("dep-act-hint").textContent =
    "重发复用上次端口/文件夹与名称；有效期与分享取后端记忆；旧口令不会恢复。";

  setVizNode("proxy", {state: "offline", detail: "条目已停止"});
  setVizNode("tunnel", {state: "offline", detail: "隧道已关闭"});
  setVizNode("source", {state: "offline", detail: "上次的源目标"});
  setVizLink("viz-link-proxy", false);
  setVizLink("viz-link-source", false);
  loadVizVisits(snap.id);
}

async function vizRepublish() {
  const snap = currentSnapshot();
  if (!snap) return;
  if (commandBusy) return toast("有指令正在执行，稍后再试", false);
  const input = document.getElementById("viz-pin-input");
  const pin = (input.value || "").trim();
  if (pin && pin.length < 4) {
    return addError("口令太短", "至少 4 位；留空表示不带口令重发", null);
  }
  const body = {async: true, pin: pin || null};
  if (snap.name) body.name = snap.name;
  if (snap.title) body.title = snap.title;
  let endpoint = "";
  if (snap.kind === "pages" && snap.folder) {
    endpoint = "/api/pages";
    body.folder = snap.folder;
  } else if (snap.kind === "port" && snap.port) {
    endpoint = "/api/publish";
    body.port = snap.port;
  } else {
    return addError("上次目标缺失", "快照里没有端口或文件夹；请用「新建应用」重新填写。", null);
  }
  setCommandBusy(true);
  addStep("正在用上次配置重新发布" + (pin ? "（带新口令）" : "") + "…");
  input.value = "";
  try {
    const d = await api(endpoint, body);
    if (!d.ok) {
      const err = d.error || {};
      return addError(err.message || "重新发布失败", err.hint || "检查目标后重试",
        null, '<button class="btn btn-sm ghost" onclick="openPublish(\'port\')">新建应用</button>');
    }
    if (d.data && d.data.job) return await pollJob(d.data.job, {options: {pin: pin || ""}});
    return await onJobSuccess(d.data, {options: {pin: pin || ""}});
  } finally {
    setCommandBusy(false);
  }
}

async function vizCheckSource(snap) {
  if (!snap || commandBusy) return;
  addStep(snap.kind === "pages" ? "正在检查上次的文件夹是否还在…" :
    "正在检查上次的端口是否还在监听…");
  try {
    if (snap.kind === "pages") {
      if (!snap.folder) return addError("上次目标缺失", "快照里没有文件夹路径。", null);
      const d = await api("/api/detect?folder=" + encodeURIComponent(snap.folder));
      if (!d.ok) {
        const err = d.error || {};
        return addError("文件夹不可用", err.message || err.hint || "路径可能已被移动或删除", null);
      }
      const info = d.data || {};
      return addResult("<b>文件夹仍在</b><div class=\"err-hint\">" +
        esc(snap.folder) + " · " + esc(info.detail || info.type || "可识别") +
        "</div><div class=\"err-hint\">这里只检查源，不代表旧链接仍可访问。</div>");
    }
    if (!snap.port) return addError("上次目标缺失", "快照里没有端口号。", null);
    const d = await api("/api/discover");
    if (!d.ok) return addError("端口扫描失败", "稍后重试", null);
    const hit = ((d.data && d.data.candidates) || [])
      .find(c => Number(c.port) === Number(snap.port));
    if (!hit) {
      return addError("端口 " + snap.port + " 未在监听",
        "源应用可能已退出；先启动它，再重新发布。", null);
    }
    addResult("<b>源端口仍在监听</b><div class=\"err-hint\">端口 " +
      esc(String(snap.port)) + (hit.title ? " · " + esc(hit.title) : "") +
      (hit.process ? " · " + esc(hit.process) : "") +
      "</div><div class=\"err-hint\">这里只检查源端口，不代表旧链接仍可访问。</div>");
  } catch (e) {
    addError("检查失败", String(e && e.message || e), null);
  }
}
