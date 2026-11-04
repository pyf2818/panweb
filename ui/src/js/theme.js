// ---------- 主题：跟随系统 / 浅色 / 深色 ----------
// 偏好只写 localStorage 的 panweb-theme，不碰口令与业务数据。
const THEME_KEY = "panweb-theme";
const THEME_CHOICES = ["auto", "light", "dark"];
const THEME_MQ = window.matchMedia
  ? window.matchMedia("(prefers-color-scheme: dark)") : null;
const THEME_ICONS = {
  auto: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 000 16z" fill="currentColor" stroke="none"/></svg>',
  light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6"/></svg>',
  dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M20 13.2A8.2 8.2 0 0110.8 4a8.2 8.2 0 109.2 9.2z"/></svg>',
};
const THEME_NAMES = {auto: "跟随系统", light: "浅色", dark: "深色"};

function themePreference() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    return THEME_CHOICES.includes(stored) ? stored : "auto";
  } catch (e) {
    return "auto";
  }
}

function themeResolved(pref) {
  if (pref === "light" || pref === "dark") return pref;
  return THEME_MQ && THEME_MQ.matches ? "dark" : "light";
}

function paintThemeControl(pref, theme) {
  const btn = document.getElementById("theme-btn");
  const label = document.getElementById("theme-label");
  const icon = document.getElementById("theme-icon");
  const name = THEME_NAMES[pref] || THEME_NAMES.auto;
  if (icon) icon.innerHTML = THEME_ICONS[pref] || THEME_ICONS.auto;
  if (label) label.textContent = name;
  if (btn) {
    btn.dataset.pref = pref;
    btn.setAttribute("aria-label", "主题：" + name + "（当前" + (theme === "dark" ? "深色" : "浅色") + "）");
    btn.title = "主题：" + name + "（点击切换）";
  }
}

function applyThemePreference(pref, persist) {
  if (!THEME_CHOICES.includes(pref)) pref = "auto";
  const theme = themeResolved(pref);
  const root = document.documentElement;
  root.setAttribute("data-theme", theme);
  root.setAttribute("data-theme-pref", pref);
  root.style.colorScheme = theme;
  if (persist) {
    try { localStorage.setItem(THEME_KEY, pref); } catch (e) { /* 隐私模式忽略 */ }
  }
  paintThemeControl(pref, theme);
}

function cycleTheme() {
  const next = {auto: "light", light: "dark", dark: "auto"}[themePreference()] || "auto";
  applyThemePreference(next, true);
}

function initTheme() {
  applyThemePreference(themePreference(), false);
  const follow = () => {
    if (themePreference() === "auto") applyThemePreference("auto", false);
  };
  if (THEME_MQ) {
    if (THEME_MQ.addEventListener) THEME_MQ.addEventListener("change", follow);
    else if (THEME_MQ.addListener) THEME_MQ.addListener(follow);
  }
}
