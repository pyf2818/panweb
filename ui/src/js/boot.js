// ---------- 启动 ----------
switchPage(["apps", "feed", "agents", "system"].includes(currentPage) ? currentPage : "apps");
refresh();
const refreshTimer = setInterval(() => { if (!document.hidden) refresh(); }, 4000);
