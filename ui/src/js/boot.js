// ---------- 启动 ----------
const PAGES = ["apps", "feed", "agents", "term", "system"];
initTheme();
switchPage(PAGES.includes(currentPage) ? currentPage : "apps");
initChat();
refresh();
const refreshTimer = setInterval(() => { if (!document.hidden) refresh(); }, 4000);

// 页面隐藏时暂停轮询与装饰动效；回到前台立即补一次状态
document.body.classList.toggle("page-hidden", document.hidden);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
