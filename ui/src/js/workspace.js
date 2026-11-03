// ---------- 三栏伸缩 ----------
function initDrag(handleId, cssVar, dir, min, max, def) {
  const handle = document.getElementById(handleId);
  handle.addEventListener("mousedown", e => {
    e.preventDefault();
    handle.classList.add("on");
    const startX = e.clientX, startW =
      parseFloat(getComputedStyle(document.documentElement).getPropertyValue(cssVar)) || def;
    const move = ev => {
      let w = startW + dir * (ev.clientX - startX);
      w = Math.max(min, Math.min(max, w));
      document.documentElement.style.setProperty(cssVar, w + "px");
    };
    const up = () => {
      handle.classList.remove("on");
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      localStorage.setItem("panweb-" + cssVar,
        document.documentElement.style.getPropertyValue(cssVar));
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });
  handle.addEventListener("dblclick", () => {
    localStorage.removeItem("panweb-" + cssVar);
    document.documentElement.style.removeProperty(cssVar);
  });
  const saved = localStorage.getItem("panweb-" + cssVar);
  if (saved) document.documentElement.style.setProperty(cssVar, saved);
}
initDrag("drag-side", "--side-w", 1, 176, 340, 212);

// ---------- 页面切换（左栏选模块，主区整幅展示） ----------
let currentPage = localStorage.getItem("panweb-page") || "apps";
const PAGE_META = {
  apps: ["我的发布台", null],
  feed: ["动态与提醒", "发布、停止与通道事件都会记录在这里"],
  agents: ["连接 Agent", "让 Agent 替你发布这台电脑上的应用 —— 装好技能，一句话就发布"],
  term: ["终端", "本机 Agent 的真终端（伪终端 PTY）搬进网页 —— 键盘直通，画面原样"],
  system: ["系统与数据", "版本、存储、运行状态与管理操作 —— 数据全部在本机"],
};
function updateSub() {
  const subEl = document.getElementById("page-sub");
  if (currentPage === "apps" && STATE) {
    const stats = STATE.stats;
    let sub = stats.total
      ? stats.online + " 个应用在线" + (stats.total > stats.online ? " · 共 " + stats.total + " 个" : "")
      : "还没有发布应用";
    if (stats.stopped_total) sub += " · 累计停止 " + stats.stopped_total;
    if (stats.attention) sub += ' · <span class="warn-text">⚠ ' + stats.attention + " 个需要检查</span>";
    subEl.innerHTML = sub;
  } else {
    subEl.textContent = PAGE_META[currentPage][1];
  }
}
function switchPage(page) {
  currentPage = page;
  localStorage.setItem("panweb-page", page);
  document.body.dataset.page = page;
  fx.page(page);
  document.querySelectorAll(".page").forEach(x =>
    x.classList.toggle("show", x.id === "page-" + page));
  document.querySelectorAll("[data-page]").forEach(x =>
    x.classList.toggle("active", x.dataset.page === page));
  document.getElementById("page-title").textContent = PAGE_META[page][0];
  updateSub();
  document.getElementById("topbar-pub").style.display = page === "agents" ? "none" : "";
  if (page === "agents") loadAgents();
  if (page === "term") tmEnterPage(); else tmLeavePage();
  if (page === "system") { loadSystem(); loadDomain(); }
}

// ---------- 系统与数据页 ----------
let SYSTEM = null;
function humanSize(n) {
  if (n > 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n > 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}
async function loadSystem() {
  const d = await api("/api/system");
  if (!d.ok) return;
  SYSTEM = d.data;
  document.getElementById("sy-apps").textContent = SYSTEM.apps_online + " / " + SYSTEM.apps_total;
  document.getElementById("sy-visits").textContent = SYSTEM.visits_total;
  document.getElementById("sy-agents").textContent = SYSTEM.agents_connected;
  document.getElementById("sy-size").textContent = humanSize(SYSTEM.data_size);
  const nb = document.getElementById("notify-visits-btn");
  if (nb) nb.textContent = "访客提醒：" + (SYSTEM.notify_visits === false ? "已关闭" : "已开启");
  document.getElementById("sy-about").innerHTML =
    "panweb v" + esc(SYSTEM.panweb_version) + " · " +
    esc(SYSTEM.cloudflared_version || "cloudflared 未安装") + " · " +
    "控制台运行 " + SYSTEM.uptime_min + " 分钟" +
    (SYSTEM.console_pid ? "（后台守护 pid " + SYSTEM.console_pid + "）" : "（前台）") +
    " · 预热通道 " + (SYSTEM.pool_ready ? "就绪 ⚡" : "—") +
    " · 数据目录 <span style='font-family:var(--mono)'>" + esc(SYSTEM.data_dir) + "</span>";
}
async function openDataDir() {
  if (!SYSTEM) return;
  const d = await api("/api/open-dir", {dir: SYSTEM.data_dir});
  if (!d.ok) toast(d.error ? d.error.message : "打开失败", false);
}
async function toggleVisitNotify() {
  const enabled = SYSTEM ? SYSTEM.notify_visits === false : false;
  const d = await api("/api/notify-visits", {enabled});
  if (!d.ok) return toast(d.error ? d.error.message : "设置失败", false);
  if (SYSTEM) SYSTEM.notify_visits = d.data.enabled;
  toast(d.data.enabled ? "访客提醒已开启" : "访客提醒已关闭");
  loadSystem();
}
async function recoverAll() {
  const d = await api("/api/recover", {});
  if (!d.ok) return toast(d.error ? d.error.message : "恢复失败", false);
  toast("已重启全部通道（" + (d.data.recovered || []).length + " 个），网址可能已更新");
  await refresh();
  if (currentPage === "system") loadSystem();
}
async function shutdownConsole() {
  if (!confirm("确定停止控制台？已发布的网址不受影响，隧道会继续工作。")) return;
  await api("/api/shutdown", {});
  if (refreshTimer) clearInterval(refreshTimer);
  toast("控制台已停止，页面将无法刷新");
}
async function exportReport() {
  const line = document.getElementById("report-line");
  if (line) line.textContent = "正在打包诊断信息…";
  const d = await api("/api/report", {});
  if (!d.ok) {
    if (line) line.textContent = "导出失败：" + (d.error ? d.error.message : "未知错误");
    return toast("诊断包导出失败", false);
  }
  if (line) line.textContent = "已导出：" + d.data.zip + "（" + humanSize(d.data.size) + "）";
  toast("诊断包已导出，可发给卖家排查");
}

// ---------- 版本与更新 ----------
let UPDATE = null;
function _upLine(text) {
  const el = document.getElementById("up-line");
  if (el) el.textContent = text;
}
function _upShowGet(show) {
  const btn = document.getElementById("up-get-btn");
  if (btn) btn.style.display = show ? "" : "none";
}
function _upBusy(busy) {
  ["up-check-btn", "up-get-btn"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  });
}
function _upRight(data) {
  if (data.license_mode === "development") return "开发版 · 不受更新窗口限制";
  return data.updates_active
    ? "更新权益有效至 " + (data.updates_until_text || "未知")
    : "更新权益已到期，取回升级包会被拒绝";
}
async function checkUpdate() {
  _upBusy(true);
  _upLine("正在查询发布仓库…");
  const d = await api("/api/update");
  _upBusy(false);
  if (!d.ok) {
    _upShowGet(false);
    _upLine("查询失败：" + (d.error ? d.error.message : "未知错误"));
    return toast("检查更新失败", false);
  }
  UPDATE = d.data;
  const notes = document.getElementById("up-notes");
  if (notes) {
    notes.style.display = UPDATE.latest_notes ? "" : "none";
    notes.textContent = UPDATE.latest_notes;
  }
  if (!UPDATE.newer) {
    _upShowGet(false);
    _upLine("已是最新（本机 " + UPDATE.current + "，发布 "
      + (UPDATE.latest || "无版本记录") + "）· " + _upRight(UPDATE));
      return toast("已经是最新版");
  }
  _upShowGet(!!UPDATE.asset);
  _upLine("发现新版本 " + (UPDATE.latest || "") + "（本机 " + UPDATE.current
    + "）· " + _upRight(UPDATE)
    + (UPDATE.asset ? "" : " · 这个 Release 里没有可用的安装包"));
}
async function applyUpdate() {
  if (!UPDATE || !UPDATE.asset) return toast("这个发布里没有可用的安装包", false);
  if (!confirm("要为本机 " + UPDATE.current + " 取回升级包 " + UPDATE.asset.name
    + "（约 " + Math.max(1, Math.round((UPDATE.asset.size || 0) / 1048576))
    + " MB）吗？下载不会替换正在运行的版本。")) return;
  _upBusy(true);
  _upLine("正在下载 " + UPDATE.asset.name + "…");
  const d = await api("/api/update/apply", {});
  _upBusy(false);
  if (!d.ok) {
    _upLine("取回失败：" + (d.error ? d.error.message : "未知错误"));
    return toast(d.error ? d.error.message : "取回失败", false);
  }
  UPDATE = d.data;
  _upShowGet(false);
  _upLine(d.data.message + " · SHA-256 " + (d.data.sha256 || "").slice(0, 16)
    + "… · 挂载后把 panweb.app 拖进「应用程序」覆盖，再重启控制台");
  toast("升级包已取回");
}

async function doPack() {
  const folder = document.getElementById("in-pack").value.trim();
  if (!folder) return toast("请输入文件夹路径", false);
  const d = await api("/api/pack", {folder});
  if (!d.ok) return toast(d.error ? d.error.message : "导出失败", false);
  toast("已导出：" + d.data.zip);
}
document.querySelectorAll("[data-page]").forEach(a =>
  a.addEventListener("click", () => switchPage(a.dataset.page)));

// ---------- 连接器 ----------
async function loadAgents() {
  const list = document.getElementById("ag-list");
  const d = await api("/api/agents");
  if (!d.ok) { list.innerHTML = '<div class="feed-empty">检测失败</div>'; return; }
  list.innerHTML = d.data.agents.map(a => {
    const st = a.connected
      ? '<span class="ag-state st-on">● 已连接' + (a.version ? " " + esc(a.version) : "") + '</span>'
      : (a.detected ? '<span class="ag-state st-yes">● 可以连接</span>'
                     : '<span class="ag-state st-no">未检测到</span>');
    const btn = a.connected
      ? '<button class="ag-btn rm" onclick="agentAction(&quot;disconnect&quot;,' + jsq(a.id) + ')">移除</button>'
      : '<button class="ag-btn go" onclick="agentAction(&quot;connect&quot;,' + jsq(a.id) + ')" ' +
        (a.detected ? "" : "disabled") + '>🔌 连接</button>';
    return '<div class="card agent-card">' +
      '<div class="agent-top">' +
        '<div class="agent-ic" style="background:' + esc(a.color) + '">' + esc(a.letter) + '</div>' +
        '<div class="agent-name">' + esc(a.name) + '</div>' + st +
      '</div>' +
      '<div class="agent-foot"><span class="dir" title="' + esc(a.skills_dir) + '">' + esc(a.skills_dir) + '</span>' + btn + '</div>' +
    '</div>';
  }).join("");
}
async function agentAction(action, id) {
  const d = await api("/api/agents/" + action, {id});
  if (!d.ok) return toast(d.error ? d.error.message : "操作失败", false);
  toast(action === "connect" ? "技能已安装，重新打开 Agent 即可用" : "已移除技能");
  await loadAgents();
}
async function copyGuide() {
  const d = await api("/api/agents/guide", {});
  if (!d.ok) return toast("获取说明失败", false);
  copyText(d.data.guide);
}

// ---------- ⌘K 命令面板 ----------
let kzSel = 0, kzItems = [];
function paletteCommands() {
  const cmds = [
    {t: "发布端口…", k: "发布", f: () => openPublish("port")},
    {t: "发布文件夹…", k: "发布", f: () => openPublish("pages")},
    {t: "启动项目并发布…", k: "发布", f: () => openPublish("project")},
    {t: "查看动态与提醒", k: "页面", f: () => switchPage("feed")},
    {t: "连接 Agent", k: "页面", f: () => switchPage("agents")},
    {t: "终端 · 让 Agent 替你部署", k: "页面", f: () => switchPage("term")},
    {t: "系统与数据", k: "页面", f: () => switchPage("system")},
    {t: "切换主题", k: "界面", f: cycleTheme},
    {t: "刷新", k: "界面", f: () => refresh(true)},
    {t: "停止全部发布", k: "停止", f: async () => { await api("/api/stop", {target: "all"}); toast("已全部停止"); await refresh(); }},
  ];
  (STATE && STATE.apps ? STATE.apps : []).forEach(a => {
    cmds.push({t: "打开 " + a.name, k: "应用", f: () => openUrl(a.url, a.id)});
    cmds.push({t: "复制 " + a.name + (a.share_url ? " 分享链接" : " 网址"), k: "应用",
               f: () => copyText(a.share_url || a.url)});
    if (a.share_url) cmds.push({t: "预览 " + a.name + " 分享页", k: "应用", f: () => openUrl(a.share_url, a.id)});
    cmds.push({t: "停止 " + a.name, k: "停止", f: async () => { await api("/api/stop", {target: a.id}); toast("已停止 " + a.name); await refresh(); }});
  });
  return cmds;
}
function toggleKz() {
  const ov = document.getElementById("kz-overlay");
  const show = !ov.classList.contains("show");
  ov.classList.toggle("show", show);
  if (show) {
    document.getElementById("kz-input").value = "";
    renderKz("");
    setTimeout(() => document.getElementById("kz-input").focus(), 80);
  }
}
function renderKz(q) {
  kzItems = paletteCommands().filter(c => !q || (c.t + c.k).toLowerCase().includes(q.toLowerCase()));
  kzSel = 0;
  document.getElementById("kz-list").innerHTML = kzItems.map((c, i) =>
    '<div class="kz-item' + (i === 0 ? " sel" : "") + '" data-i="' + i + '">' +
    esc(c.t) + '<span class="k">' + esc(c.k) + '</span></div>').join("")
    || '<div class="feed-empty">没有匹配的命令</div>';
}
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    toggleKz();
    return;
  }
  const ov = document.getElementById("kz-overlay");
  if (!ov.classList.contains("show")) return;
  if (e.key === "Escape") { ov.classList.remove("show"); return; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    kzSel = Math.max(0, Math.min(kzItems.length - 1, kzSel + (e.key === "ArrowDown" ? 1 : -1)));
    document.querySelectorAll(".kz-item").forEach((el, i) => el.classList.toggle("sel", i === kzSel));
  }
  if (e.key === "Enter" && kzItems[kzSel]) {
    ov.classList.remove("show");
    kzItems[kzSel].f();
  }
});
document.getElementById("kz-input").addEventListener("input", e => renderKz(e.target.value));
document.getElementById("kz-list").addEventListener("click", e => {
  const item = e.target.closest(".kz-item");
  if (item) { document.getElementById("kz-overlay").classList.remove("show"); kzItems[+item.dataset.i].f(); }
});

