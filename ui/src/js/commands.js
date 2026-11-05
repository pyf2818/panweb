// ---------- 操作结果区：停止 / 自检 / 发布 job 的状态条（不是消息流） ----------
let commandBusy = false;

function stageNote(html, tone) {
  const box = document.getElementById("stage-note");
  if (!box) return;
  box.className = "stage-note" + (tone ? " " + tone : "");
  box.hidden = !html;
  if (html) box.innerHTML = html;
}
function noteText(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html || "";
  return (tmp.textContent || "").replace(/\s+/g, " ").trim().slice(0, 300);
}
function addStep(text) {
  stageNote('<span class="sn-step">◌ ' + esc(text) + "</span>");
  announce(text);
}
function addError(message, hint, examples, extraButton) {
  const html = '<b class="sn-err">' + esc(message || "执行失败") + "</b>" +
    (hint ? '<span class="sn-hint">' + esc(hint) + "</span>" : "") +
    '<span class="sn-acts">' + (extraButton || "") + "</span>";
  stageNote(html, "bad");
  announce((message || "执行失败") + (hint ? "。" + hint : ""));
}
function addResult(html, actions) {
  stageNote(html + '<span class="sn-acts">' + (actions || "") + "</span>", "good");
  announce(noteText(html));
}
function setCommandBusy(busy) {
  commandBusy = busy;
  document.querySelectorAll("#stage-quickbar .quick-btn").forEach(b => { b.disabled = busy; });
  const pub = document.getElementById("pub-btn");
  if (pub) pub.disabled = busy;
  const stage = document.getElementById("stage");
  if (stage) stage.setAttribute("aria-busy", busy ? "true" : "false");
}

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
function stepText(step) {
  if (!step) return "";
  if (typeof step === "string") return step;
  return step.text || step.label || step.message || JSON.stringify(step);
}

async function pollJob(jobId, parsed) {
  let seen = 0;
  let lastText = "";
  for (let i = 0; i < 1800; i++) {
    await sleep(700);
    const d = await api("/api/job?id=" + encodeURIComponent(jobId));
    if (!d.ok) {
      const err = d.error || {};
      return addError(err.message || "任务读取失败", err.hint || "控制台可能已重启", null,
        '<button class="btn btn-sm ghost" onclick="refresh(true)">刷新</button>');
    }
    const job = d.data || {};
    const steps = Array.isArray(job.steps) ? job.steps : [];
    while (seen < steps.length) {
      const text = stepText(steps[seen]);
      if (text) addStep(text);
      seen += 1;
    }
    if (!steps.length && job.step && job.step !== lastText) {
      lastText = job.step;
      addStep(lastText);
    }
    if (job.done) {
      if (job.ok) return onJobSuccess(job.result, parsed);
      return addError((job.error && (job.error.message || job.error)) || "发布失败",
        job.error && job.error.hint, null,
        '<button class="btn btn-sm ghost" onclick="openPublish(\'port\')">重新填写</button>');
    }
  }
  addError("等待超时", "任务仍在后台运行，可刷新状态或重新发布。", null,
    '<button class="btn btn-sm ghost" onclick="refresh(true)">刷新</button>');
}

async function onJobSuccess(entry, parsed) {
  entry = entry || {};
  addStep("发布完成，正在同步状态…");
  if (entry.id) selectedAssetId = entry.id;
  await refresh(true);
  if (entry.id) {
    selectAsset(entry.id);
    loadAssetTimeline(entry.id, true);
    renderViz();
  }
  const url = entry.url || "";
  const share = entry.share_url || "";
  const pinNote = entry.pinned || (parsed && parsed.options && parsed.options.pin)
    ? '<span class="sn-hint">已设置访问口令；口令只在你的记忆里，页面不会保存。</span>' : "";
  addResult("<b>" + esc(entry.name || "发布成功") + " 已上线</b>" +
    '<span class="sn-url">' + esc(url || "网址待生成") + "</span>" +
    pinNote,
    (url ? '<button class="btn btn-sm" onclick="copyText(' + jsq(url) +
      ')">复制网址</button><button class="btn btn-sm ghost" onclick="stageOpen()">在预览中打开</button>' : "") +
    (entry.id ? '<button class="btn btn-sm ghost" onclick="openDrawer(' + jsq(entry.id) +
      ')">详情</button>' : ""));
  stageAfterPublish(entry.id || null, entry);
}

function resolveStopTarget(parsed) {
  if (parsed.scope === "all") return "all";
  if (parsed.scope === "current") {
    const found = findAsset(selectedAssetId);
    if (!found || found.hosted || found.snapshot) return null;
    return found.a.id;
  }
  if (parsed.port) {
    const found = findAssetByPort(parsed.port);
    return found ? found.id : null;
  }
  return parsed.id || null;
}

async function stopFromCommand(parsed) {
  const target = resolveStopTarget(parsed);
  if (!target) {
    const snap = typeof currentSnapshot === "function" ? currentSnapshot() : null;
    return addError(snap ? "当前选中条目已停止" : (parsed.port
      ? "没有发布在端口 " + parsed.port + " 的应用" : "没有选中的应用"),
      snap ? "在右栏点「用同样配置重新发布」，或先选择运行中的条目"
        : "先从左侧选择资产，或到「扫描端口」找可发布的应用");
  }
  const d = await api("/api/stop", {target});
  if (!d.ok) {
    const err = d.error || {};
    return addError(err.message || "停止失败", err.hint || "稍后重试");
  }
  const stopped = (d.data && d.data.stopped) || [];
  if (!stopped.length) return addError("没有可停止的应用", "当前选中的条目可能已经停止");
  addResult("<b>已停止 " + stopped.length + " 个应用</b>" +
    stopped.map(s => '<span class="sn-hint">' + esc(s.name || s.id || "") + "</span>").join(""),
    '<button class="btn btn-sm ghost" onclick="refresh(true)">刷新状态</button>');
  if (stopped.some(s => s.id === selectedAssetId)) {
    // 停止后会生成只读快照，保留选中，右栏直接切到「上次发布」状态。
    loadAssetTimeline(selectedAssetId, true);
  }
  await refresh(true);
  reloadTimeline();
}

function stopCurrent() {
  if (commandBusy) return;
  setCommandBusy(true);
  stopFromCommand({scope: "current"}).finally(() => setCommandBusy(false));
}

function resolveCheckTarget(parsed) {
  if (parsed.scope === "current") {
    const found = findAsset(selectedAssetId);
    if (!found || found.hosted || found.snapshot) return null;
    return found.a.id;
  }
  if (parsed.port) {
    const found = findAssetByPort(parsed.port);
    return found ? found.id : null;
  }
  return parsed.id || null;
}

async function doCheck(parsed) {
  const id = resolveCheckTarget(parsed);
  if (!id) {
    const snap = typeof currentSnapshot === "function" ? currentSnapshot() : null;
    return addError(snap ? "当前选中条目已停止" : (parsed.port
      ? "没有发布在端口 " + parsed.port + " 的应用" : "没有可检查的应用"),
      snap ? "在右栏点「用同样配置重新发布」，或先选择运行中的条目"
        : "先从左侧选择资产，或到「扫描端口」找可发布的应用");
  }
  addStep("正在从访客视角自检…");
  const d = await api("/api/check", {id});
  if (!d.ok) {
    const err = d.error || {};
    return addError(err.message || "自检失败", err.hint || "稍后重试");
  }
  const check = d.data || {};
  const good = check.verdict === "ok" || check.verdict === "healthy";
  const signals = (check.signals || []).map(s => s.detail || s.code || "").filter(Boolean);
  const html = "<b>自检：" + esc(check.summary || check.verdict || "完成") + "</b>" +
    '<span class="sn-url">' + esc(check.url || "") + "</span>" +
    (signals.length ? '<span class="sn-hint">' + esc(signals.slice(0, 4).join(" · ")) + "</span>" : "") +
    ((check.fixes || []).length ? '<span class="sn-hint">已自动修复：' +
      esc(check.fixes.join("；")) + "</span>" : "");
  if (good) addResult(html, '<button class="btn btn-sm ghost" onclick="openDrawer(' +
    jsq(id) + ')">详情</button>');
  else addError(check.summary || "自检未通过", "打开详情查看信号与修复建议", null,
    '<button class="btn btn-sm ghost" onclick="openDrawer(' + jsq(id) + ')">详情</button>');
  loadAssetTimeline(id, true);
}
