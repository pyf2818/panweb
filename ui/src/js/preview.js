// ---------- 中栏：本机预览（只消费 /api/preview，不拼任意 URL） ----------
let PREVIEW_SEQ = 0;
let PREVIEW_TIMER = null;
let PREVIEW_TARGET = "";
let PREVIEW_SIG = "";

function previewSubject() {
  const found = findAsset(selectedAssetId);
  if (!found) return null;
  return found;
}
function subjectOpenUrl(found) {
  const a = (found && found.a) || {};
  return a.share_url || a.url || "";
}
function clearPreviewWatch() {
  if (PREVIEW_TIMER) { clearTimeout(PREVIEW_TIMER); PREVIEW_TIMER = null; }
}
function previewLoading(text) {
  return '<div class="pv-loading"><span class="spin" aria-hidden="true"></span>' +
    esc(text || "正在检查本机预览…") + "</div>";
}
function previewDegrade(title, detail, url) {
  return '<div class="pv-degrade" role="note">' +
    '<span class="pv-ico" aria-hidden="true">!</span>' +
    "<b>" + esc(title) + "</b><p>" + esc(detail) + "</p>" +
    '<div class="pv-actions">' +
    (url ? '<button class="btn btn-primary" type="button" onclick="openUrl(' + jsq(url) +
      ')">打开链接</button>' : "") +
    '<button class="btn btn-sm ghost" type="button" onclick="stageRefresh()">重新检查</button>' +
    "</div></div>";
}

function showPreviewHtml(html) {
  const box = document.getElementById("stage-preview");
  if (box) box.innerHTML = html;
}

function renderFrame(url, seq) {
  const box = document.getElementById("stage-preview");
  if (!box) return;
  PREVIEW_TARGET = url;
  box.innerHTML = '<div class="pv-frame"><iframe id="stage-frame" title="本机应用预览" ' +
    'src="' + esc(url) + '" sandbox="allow-scripts allow-same-origin allow-forms allow-popups" ' +
    'referrerpolicy="no-referrer" onload="onPreviewFrameLoad()"></iframe></div>';
  PREVIEW_TIMER = setTimeout(() => {
    if (seq !== PREVIEW_SEQ) return;
    showPreviewHtml(previewDegrade("本机预览加载超时",
      "页面在 8 秒内没有响应；可能是应用拒绝内嵌或服务已退出。", ""));
  }, 8000);
}

function onPreviewFrameLoad() {
  clearPreviewWatch();
}

async function renderPreview(force) {
  const found = previewSubject();
  const box = document.getElementById("stage-preview");
  if (!box) return;
  const sig = found ? [found.id, found.hosted, found.snapshot,
    found.a && found.a.alive, found.a && found.a.url, found.a && found.a.share_url].join("|") : "";
  // 4 秒状态刷新不应重载正在看的 iframe；只有选中/状态/地址变化或手动刷新才重建。
  if (!force && sig === PREVIEW_SIG && box.childElementCount) return;
  PREVIEW_SIG = sig;
  clearPreviewWatch();
  PREVIEW_SEQ += 1;
  const seq = PREVIEW_SEQ;
  if (!found) { box.innerHTML = ""; PREVIEW_TARGET = ""; return; }
  if (found.hosted) {
    showPreviewHtml(previewDegrade("云端托管不提供本地预览",
      "这个资产在 GitHub Pages 上，请用「打开」查看。", subjectOpenUrl(found)));
    return;
  }
  if (found.snapshot) {
    showPreviewHtml(previewDegrade("已停止 · 右栏可重新发布",
      "上次链接已经失效。右栏保留上次配置，点击「用同样配置重新发布」即可恢复。",
      subjectOpenUrl(found)));
    return;
  }
  const a = found.a;
  if (!a.alive) {
    showPreviewHtml(previewDegrade("应用已停止",
      "进程不在运行，无法内嵌预览。可先启动源应用，再重新发布。", subjectOpenUrl(found)));
    return;
  }
  showPreviewHtml(previewLoading());
  const d = await api("/api/preview?id=" + encodeURIComponent(a.id));
  if (seq !== PREVIEW_SEQ) return;
  if (!d.ok) {
    const err = d.error || {};
    showPreviewHtml(previewDegrade("无法预览", err.message || "本机预览不可用",
      subjectOpenUrl(found)));
    return;
  }
  const data = d.data || {};
  if (!data.embeddable) {
    showPreviewHtml(previewDegrade(data.reason || "该应用禁止内嵌，请用打开",
      "上游返回了不允许内嵌的响应，预览被拦下。用「打开链接」在新标签页查看。",
      subjectOpenUrl(found)));
    return;
  }
  if (!data.url) {
    showPreviewHtml(previewDegrade("无法预览", "没有解析到本机地址。", subjectOpenUrl(found)));
    return;
  }
  renderFrame(data.url, seq);
}

function stageRefresh() {
  renderPreview(true);
  announce("正在刷新预览");
}
