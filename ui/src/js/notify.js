// ---------- 通知面板：数据来自 /api/history?limit=20，展开时拉一次 ----------
const NOTIFY_LIMIT = 20;
let NOTIFY_ROWS = null;
let NOTIFY_PENDING_ID = 0;

function notifyPanel() { return document.getElementById("bell-panel"); }
function notifyList() { return document.getElementById("bell-list"); }

function notifyPanelClose() {
  const panel = notifyPanel();
  if (!panel || !panel.classList.contains("show")) return;
  panel.classList.remove("show");
  NOTIFY_ROWS = null;
  NOTIFY_PENDING_ID += 1;
}

function toggleBell(e) {
  if (e) e.stopPropagation();
  const panel = notifyPanel();
  const open = !panel.classList.contains("show");
  if (!open) { notifyPanelClose(); return; }
  panel.classList.add("show");
  checkNotifs();
  loadNotifyPanel();
}

async function loadNotifyPanel(force) {
  if (NOTIFY_ROWS && !force) { renderNotifyPanel(); return; }
  const token = ++NOTIFY_PENDING_ID;
  const list = notifyList();
  if (list) list.innerHTML = '<div class="feed-empty">正在读取最近事件…</div>';
  const d = await api("/api/history?limit=" + NOTIFY_LIMIT);
  if (token !== NOTIFY_PENDING_ID) return;
  if (!d.ok) {
    if (list) list.innerHTML = '<div class="feed-empty">通知读取失败：' +
      esc((d.error && d.error.message) || "未知错误") + "</div>";
    return;
  }
  NOTIFY_ROWS = (d.data && d.data.events) || [];
  renderNotifyPanel();
}

function notifyLabel(type) {
  const labels = typeof EVENT_LABELS !== "undefined" ? EVENT_LABELS : {};
  return labels[type] || type || "事件";
}

// /api/history 的 ts 是秒级数字；兼容字符串时间戳与毫秒值。
function notifyTs(ts) {
  const n = Number(ts);
  if (Number.isFinite(n) && n > 0) return n > 1e12 ? n : n * 1000;
  const parsed = new Date(String(ts || "").replace(" ", "T")).getTime();
  return Number.isFinite(parsed) ? parsed : 0;
}
function notifyTime(ts) {
  const ms = notifyTs(ts);
  if (!ms) return "";
  const d = new Date(ms);
  const p = n => String(n).padStart(2, "0");
  return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " +
    p(d.getHours()) + ":" + p(d.getMinutes());
}

function renderNotifyPanel() {
  const list = notifyList();
  if (!list) return;
  if (!NOTIFY_ROWS || !NOTIFY_ROWS.length) {
    list.innerHTML = '<div class="feed-empty">最近没有事件</div>';
    return;
  }
  list.innerHTML = NOTIFY_ROWS.map((ev, i) => {
    const unread = notifyTs(ev.ts) > readTs ? " bell-item-unread" : "";
    const canJump = ev.entry_id && typeof findAsset === "function" && findAsset(ev.entry_id);
    return '<button type="button" class="bell-item' + unread + '" data-i="' + i + '" ' +
      'onclick="notifyGo(' + i + ')" ' +
      (canJump ? 'aria-label="跳转到 ' + esc(ev.summary || "") + '"' : 'aria-disabled="true"') + ">" +
      '<span class="bell-text">' + esc(ev.summary || "") + "</span>" +
      '<span class="bell-kind">' + esc(notifyLabel(ev.type)) + (canJump ? "" : " · 已不存在") + "</span>" +
      '<span class="t">' + esc(notifyTime(ev.ts)) + "</span></button>";
  }).join("");
}

function notifyGo(i) {
  const ev = NOTIFY_ROWS && NOTIFY_ROWS[i];
  if (!ev) return;
  notifyPanelClose();
  if (!ev.entry_id || !findAsset(ev.entry_id)) {
    toast("该条目已不存在，无法跳转", false);
    return;
  }
  if (currentPage !== "apps") switchPage("apps");
  selectAsset(ev.entry_id);
  announce("已跳转到 " + (ev.summary || "对应条目"));
}

function notifyReload() { loadNotifyPanel(true); }
