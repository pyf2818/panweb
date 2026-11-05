// ---------- 中栏 stage：预览 / 新建 / 空态 + 快捷指令带 ----------
let stageMode = "preview"; // preview | create | empty

function stageSubject() {
  return typeof findAsset === "function" ? findAsset(selectedAssetId) : null;
}
function stageSetHead(kind, name, badge) {
  document.getElementById("stage-kind").textContent = kind;
  document.getElementById("stage-name").textContent = name;
  const b = document.getElementById("stage-badge");
  if (badge) { b.hidden = false; b.textContent = badge; }
  else b.hidden = true;
}
function stageTool(id, show) {
  const el = document.getElementById(id);
  if (el) el.hidden = !show;
}
function stageEmptyVisible(show) {
  const empty = document.getElementById("stage-empty");
  const preview = document.getElementById("stage-preview");
  const create = document.getElementById("stage-create");
  if (empty) empty.hidden = !show;
  if (preview) preview.hidden = show || stageMode === "create";
  if (create) create.hidden = stageMode !== "create";
}

function renderStage() {
  const stage = document.getElementById("stage");
  if (!stage) return;
  if (stageMode === "create") {
    stage.dataset.mode = "create";
    stageSetHead("新建", "新建应用", null);
    stageVisibleTools("create");
    stageEmptyVisible(false);
    return;
  }
  const found = stageSubject();
  if (!found) {
    stage.dataset.mode = "empty";
    stageSetHead("预览", "还没有可预览的应用", null);
    stageVisibleTools("empty");
    stageEmptyVisible(true);
    return;
  }
  stage.dataset.mode = "preview";
  const a = found.a;
  stageSetHead(found.snapshot ? "上次发布" : found.hosted ? "云端托管" : "预览",
    a.title || a.name || "未命名应用",
    found.hosted ? "云端托管" : found.snapshot ? assetStatusText(found) : statusText(assetStatus(a, false, false)));
  stageVisibleTools("preview", found);
  stageEmptyVisible(false);
  renderPreview();
}

function assetStatusText(found) {
  return found.snapshot ? statusText(assetStatus(found.a, false, true)) : "";
}

function stageVisibleTools(mode, found) {
  const tools = document.getElementById("stage-tools");
  if (!tools) return;
  tools.hidden = mode === "empty";
  const preview = mode === "preview";
  stageTool("stage-open", preview);
  stageTool("stage-copy", preview);
  stageTool("stage-refresh", preview);
  stageTool("stage-stop", preview && !!found && !found.snapshot && !found.hosted);
  stageTool("stage-republish", preview && !!found && !!found.snapshot);
  stageTool("stage-back", mode === "create");
  const copy = document.getElementById("stage-copy");
  const stop = document.getElementById("stage-stop");
  if (copy) copy.disabled = !preview || !found || !subjectOpenUrl(found);
  if (stop) stop.disabled = !found || found.snapshot || found.hosted;
}

function openStageCreate() {
  stageMode = "create";
  const stage = document.getElementById("stage");
  if (stage) {
    stage.dataset.mode = "create";
    const body = document.getElementById("stage-body");
    if (body) body.scrollTop = 0;
  }
  stageSetHead("新建", "新建应用", null);
  stageVisibleTools("create");
  stageEmptyVisible(false);
  announce("已进入新建应用表单");
}

function stageResetToPreview() {
  if (stageMode === "create") stageMode = "preview";
}

function stageBack() {
  if (pubPoll) { clearInterval(pubPoll); pubPoll = null; }
  stageMode = "preview";
  resetPubFeedback();
  renderStage();
}

async function stageAfterPublish(entryId, entry) {
  stageMode = "preview";
  if (entryId) selectedAssetId = entryId;
  await refresh(true);
  if (entryId && findAsset(entryId)) selectAsset(entryId);
  renderStage();
}

function stageOpen() {
  const found = stageSubject();
  const url = subjectOpenUrl(found);
  if (!url) { toast("当前条目还没有可用链接", false); return; }
  openUrl(url, found && !found.hosted && !found.snapshot ? found.a.id : null);
}
function stageCopy() {
  const found = stageSubject();
  const url = subjectOpenUrl(found);
  if (!url) { toast("当前条目还没有可用链接", false); return; }
  copyText(url);
}
async function stageStop() {
  const found = stageSubject();
  if (!found || found.snapshot) {
    toast("当前条目已停止，可在右栏重新发布", false);
    return;
  }
  if (found.hosted) { toast("云端托管条目请到右栏操作", false); return; }
  askStop(found.a.id, found.a.name || found.a.title);
}
function stageRepublish() {
  const found = stageSubject();
  if (found && found.snapshot) { if (typeof vizRepublish === "function") vizRepublish(); return; }
  toast("只有已停止条目才能用同样配置重新发布", false);
}

// ---------- 快捷指令带 ----------
function openPublishPort(port) {
  openPublish("port");
  const el = document.getElementById("in-port");
  if (el) {
    el.value = String(port || "");
    el.focus();
  }
}
function quickPublish(tab) {
  if (commandBusy) return;
  openPublish(tab || "port");
}
function quickStopCurrent() {
  if (commandBusy) return;
  const found = stageSubject();
  if (!found || found.snapshot) {
    addError("没有可停止的选中应用", "先从左侧选择运行中的条目，或右键栏「重新发布」恢复一个。");
    return;
  }
  stopCurrent();
}
function quickCheckCurrent() {
  if (commandBusy) return;
  doCheck({scope: "current"});
}
async function quickScan() {
  if (commandBusy) return;
  setCommandBusy(true);
  addStep("正在扫描本机监听端口…");
  const d = await api("/api/discover");
  setCommandBusy(false);
  if (!d.ok) {
    return addError((d.error && d.error.message) || "扫描失败", "稍后再试，或手动输入端口。");
  }
  const list = (d.data && d.data.candidates) || [];
  if (!list.length) {
    return addResult("<b>没有发现可发布的本机端口</b>",
      '<button class="btn btn-sm ghost" onclick="openPublish(\'pages\')">改为发布文件夹</button>');
  }
  const html = "<b>发现 " + list.length + " 个端口</b>";
  addResult(html, list.map(c => '<button class="btn btn-sm" type="button" onclick="openPublishPort(' +
    Number(c.port) + ')">:' + Number(c.port) + " " + esc((c.title || c.process || "").slice(0, 12)) +
    "</button>").join(" ") +
    '<button class="btn btn-sm ghost" type="button" onclick="quickScan()">重新扫描</button>');
}
