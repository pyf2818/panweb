// ---------- 中栏：对话式发布（解析 → 异步 job → 回执/重试） ----------
let chatInited = false;
let commandBusy = false;
let LAST_PARSED = null;

const HELP_EXAMPLES = [
  "发布 3000",
  "发布 /path/to/dist",
  "发布 3000 pin=1234 有效期=1d 分享=开 名称=演示站",
  "启动 /path/to/project",
  "停止 8080", "停止 当前", "停止 全部",
  "检查 当前", "帮助",
];

function maskPin(text) {
  return String(text || "").replace(
    /(pin)(\s*=\s*|\s+)(?:"[^"]*"|'[^']*'|\S+)/gi, "$1$2****");
}
function chatScroll() {
  const log = document.getElementById("chat-log");
  log.scrollTop = log.scrollHeight;
}
function chatMsg(kind, role, html) {
  const log = document.getElementById("chat-log");
  const el = document.createElement("div");
  el.className = "msg " + kind;
  el.innerHTML = '<div class="msg-role">' + esc(role) + '</div>' +
    '<div class="bubble">' + html + '</div>';
  log.appendChild(el);
  while (log.children.length > 120) log.removeChild(log.firstElementChild);
  chatScroll();
  return el;
}
function addUser(text) {
  chatMsg("user", "你", esc(maskPin(text)));
}
function addStep(text) {
  chatMsg("step", "进程", esc(text));
}
function addSystem(html) {
  chatMsg("system", "系统", html);
}
function addHelp(parsed) {
  const examples = (parsed && parsed.examples) || HELP_EXAMPLES;
  addSystem("<b>可用指令</b><br>发布 / 启动 / 停止 / 检查 / 帮助，支持 " +
    "<code>pin=</code>、<code>有效期=1h|1d|7d|永久</code>、<code>分享=开|关</code>、" +
    "<code>名称=</code>。端口或文件夹省略时沿用上次默认值。" +
    examplesHtml(examples));
}
function examplesHtml(examples) {
  return '<div class="example-list">' + examples.map(ex =>
    '<div class="example-row"><button type="button" class="ex" onclick="fillCommand(' +
    jsq(ex) + ')" title="填入输入框">' + esc(ex) + '</button>' +
    '<button type="button" class="btn btn-sm ghost" onclick="copyText(' + jsq(ex) +
    ')">复制</button></div>').join("") + "</div>";
}
function addError(message, hint, examples, extraButton, allowRetry) {
  const retry = allowRetry === false ? "" :
    '<button class="btn btn-sm ghost" onclick="retryLast()">重试</button>';
  const msg = chatMsg("error", "失败", "<b>" + esc(message || "执行失败") + "</b>" +
    (hint ? '<div class="err-hint">' + esc(hint) + "</div>" : "") +
    (examples && examples.length ? examplesHtml(examples) : "") +
    '<div class="msg-actions">' + retry + (extraButton || "") + "</div>");
  return msg;
}
function addResult(html, actions) {
  chatMsg("success", "完成", html + '<div class="msg-actions">' + (actions || "") + "</div>");
}
function setCommandBusy(busy) {
  commandBusy = busy;
  const input = document.getElementById("cmd-input");
  const run = document.getElementById("cmd-run");
  input.disabled = busy;
  run.disabled = busy;
  run.textContent = busy ? "执行中…" : "执行";
}
function fillCommand(text) {
  const input = document.getElementById("cmd-input");
  input.value = text;
  input.focus();
  autoGrowCommand();
}
function autoGrowCommand() {
  const input = document.getElementById("cmd-input");
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 128) + "px";
}
function initChat() {
  if (chatInited) return;
  chatInited = true;
  addSystem("这里是发布控制台。输入 <b>发布 3000</b> 回车即可；" +
    "口令只用于当次请求，消息里只显示 <code>pin=****</code>。" + examplesHtml(HELP_EXAMPLES.slice(0, 4)));
  document.getElementById("cmd-input").addEventListener("input", autoGrowCommand);
  document.getElementById("cmd-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("cmd-form").requestSubmit();
    }
  });
}

async function submitCommand(event) {
  if (event) event.preventDefault();
  if (commandBusy) return;
  const input = document.getElementById("cmd-input");
  const text = (input.value || "").trim();
  if (!text) return;
  addUser(text);
  input.value = "";
  autoGrowCommand();
  setCommandBusy(true);
  try {
    const d = await api("/api/command", {text});
    if (!d.ok) {
      const err = d.error || {};
      addError(err.message || "指令无法解析", err.hint || "换一种写法再试",
        d.examples || HELP_EXAMPLES.slice(0, 4), null, false);
      return;
    }
    const parsed = d.data;
    LAST_PARSED = parsed;
    if (parsed.action === "help") return addHelp(parsed);
    await executeParsed(parsed);
  } catch (e) {
    addError("执行失败", String(e && e.message || e), null);
  } finally {
    setCommandBusy(false);
  }
}

async function retryLast() {
  if (commandBusy || !LAST_PARSED) return;
  addSystem("按上一次的解析结果重试（口令只保留在本次页面内存中）。");
  setCommandBusy(true);
  try {
    await executeParsed(LAST_PARSED);
  } finally {
    setCommandBusy(false);
  }
}

async function executeParsed(parsed) {
  if (!parsed || !parsed.ok) return;
  const options = parsed.options || {};
  if (parsed.action === "stop") return stopFromCommand(parsed);
  if (parsed.action === "check") return doCheck(parsed);
  if (parsed.action === "help") return addHelp(parsed);
  const endpoint = {publish: "/api/publish", pages: "/api/pages", run: "/api/run"}[parsed.action];
  if (!endpoint) return addError("暂不支持这个动作", "试试：发布 3000");
  const body = {
    async: true, pin: options.pin || null, expires: options.expires || "",
    name: options.name || null, share: !!options.share,
  };
  if (parsed.action === "publish") body.port = parsed.port;
  if (parsed.folder) body.folder = parsed.folder;

  const d = await api(endpoint, body);
  if (!d.ok) {
    const err = d.error || {};
    return addError(err.message || "发布失败", err.hint || "检查目标后重试",
      null, '<button class="btn btn-sm ghost" onclick="openPublish(\'port\')">高级发布</button>');
  }
  if (d.data && d.data.job) return pollJob(d.data.job, parsed);
  return onJobSuccess(d.data, parsed);
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
      return addError(err.message || "任务读取失败", err.hint || "控制台可能已重启",
        null, '<button class="btn btn-sm ghost" onclick="refresh(true)">刷新</button>');
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
        '<button class="btn btn-sm ghost" onclick="openPublish(\'port\')">高级发布</button>');
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
  const qrId = "qr-" + Math.random().toString(36).slice(2);
  const pinNote = entry.pinned || (parsed.options && parsed.options.pin)
    ? '<div class="err-hint">已设置访问口令；口令只在你的记忆里，页面不会保存。</div>' : "";
  const html = '<b>' + esc(entry.name || "发布成功") + " 已上线</b>" +
    '<div class="receipt"><div class="receipt-url">' + esc(url || "网址待生成") + "</div>" +
    (share ? '<div class="receipt-url">分享：' + esc(share) + "</div>" : "") +
    pinNote +
    '<div class="receipt-qr"><div id="' + qrId + '"></div><div class="qr-note">' +
    (share ? "扫码打开分享页" : "扫码直接打开应用") + "<br>二维码在本地生成，不走外链。</div></div></div>";
  const actions = (url ? '<button class="btn btn-sm" onclick="copyText(' + jsq(url) +
    ')">复制网址</button><button class="btn btn-sm ghost" onclick="window.open(' + jsq(url) +
    ',\'_blank\')">打开</button>' : "") +
    (entry.id ? '<button class="btn btn-sm ghost" onclick="openDrawer(' + jsq(entry.id) +
      ')">详情</button><button class="btn btn-sm ghost" onclick="stopCurrent()">停止</button>' : "");
  addResult(html, actions);
  drawQr(qrId, share || url);
}

function drawQr(holderId, url) {
  const holder = document.getElementById(holderId);
  if (!holder || !url) return;
  if (!window.qrcode) {
    holder.textContent = "二维码不可用";
    return;
  }
  try {
    const q = qrcode(0, "M");
    q.addData(url);
    q.make();
    holder.innerHTML = q.createSvgTag({cellSize: 2, margin: 0, scalable: true});
    holder.firstElementChild.style.width = "92px";
    holder.firstElementChild.style.height = "92px";
  } catch (e) {
    holder.textContent = "二维码生成失败";
  }
}

function resolveStopTarget(parsed) {
  if (parsed.scope === "all") return "all";
  if (parsed.scope === "current") {
    const found = findAsset(selectedAssetId);
    if (!found || found.hosted) return null;
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
    return addError(parsed.port ? "没有发布在端口 " + parsed.port + " 的应用" :
      "没有选中的应用", "先从左侧选择资产，或写：停止 8080", null);
  }
  const d = await api("/api/stop", {target});
  if (!d.ok) {
    const err = d.error || {};
    return addError(err.message || "停止失败", err.hint || "稍后重试", null);
  }
  const stopped = (d.data && d.data.stopped) || [];
  if (!stopped.length) return addError("没有可停止的应用", "用「停止 全部」清理全部发布");
  addResult("<b>已停止 " + stopped.length + " 个应用</b>" +
    stopped.map(s => '<div class="err-hint">' + esc(s.name || s.id || "") + "</div>").join(""),
    '<button class="btn btn-sm ghost" onclick="refresh(true)">刷新状态</button>');
  if (stopped.some(s => s.id === selectedAssetId)) selectedAssetId = null;
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
    if (!found || found.hosted) return null;
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
    return addError(parsed.port ? "没有发布在端口 " + parsed.port + " 的应用" :
      "没有可检查的应用", "先从左侧选择资产，或写：检查 8080", null);
  }
  addStep("正在从访客视角自检…");
  const d = await api("/api/check", {id});
  if (!d.ok) {
    const err = d.error || {};
    return addError(err.message || "自检失败", err.hint || "稍后重试", null);
  }
  const check = d.data || {};
  const good = check.verdict === "ok" || check.verdict === "healthy";
  const signals = (check.signals || []).map(s => s.detail || s.code || "").filter(Boolean);
  const html = "<b>自检：" + esc(check.summary || check.verdict || "完成") + "</b>" +
    '<div class="err-hint">' + esc(check.url || "") + "</div>" +
    (signals.length ? '<div class="err-hint">' + esc(signals.slice(0, 4).join(" · ")) + "</div>" : "") +
    ((check.fixes || []).length ? '<div class="err-hint">已自动修复：' +
      esc(check.fixes.join("；")) + "</div>" : "");
  if (good) addResult(html, '<button class="btn btn-sm ghost" onclick="openDrawer(' +
    jsq(id) + ')">详情</button>');
  else addError(check.summary || "自检未通过", "打开详情查看信号与修复建议", null,
    '<button class="btn btn-sm ghost" onclick="openDrawer(' + jsq(id) + ')">详情</button>');
  loadAssetTimeline(id, true);
}
