// ---------- 右栏：分组折叠（只持久化布尔）与最近访客 ----------
const DEP_GROUP_KEYS = ["links", "status", "visitors", "history", "process"];
const DEP_GROUP_DEFAULTS = {
  links: true, status: true, visitors: false, history: false, process: false,
};
const DEP_GROUP_STORE = "panweb-dep-groups";
const VISIT_CACHE = {};
const VISITS_LOADED = new Set();

function depGroupState() {
  const out = Object.assign({}, DEP_GROUP_DEFAULTS);
  try {
    const raw = JSON.parse(localStorage.getItem(DEP_GROUP_STORE) || "{}");
    DEP_GROUP_KEYS.forEach(k => {
      if (typeof raw[k] === "boolean") out[k] = raw[k];
    });
  } catch (e) { /* 坏数据回退默认 */ }
  return out;
}

function saveDepGroupState(state) {
  try {
    const out = {};
    DEP_GROUP_KEYS.forEach(k => { out[k] = !!state[k]; });
    localStorage.setItem(DEP_GROUP_STORE, JSON.stringify(out));
  } catch (e) { /* 隐私模式忽略 */ }
}

function applyDepGroup(id, open) {
  const group = document.getElementById("dep-group-" + id);
  const body = document.getElementById("dep-body-" + id);
  if (!group || !body) return;
  const btn = group.querySelector(".dep-group-btn");
  if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
  body.hidden = !open;
  group.classList.toggle("is-collapsed", !open);
}

function toggleDepGroup(id) {
  const btn = document.getElementById("dep-group-" + id)
    .querySelector(".dep-group-btn");
  const open = btn.getAttribute("aria-expanded") !== "true";
  applyDepGroup(id, open);
  const state = depGroupState();
  state[id] = open;
  saveDepGroupState(state);
  if (id === "visitors" && open) loadVizVisits(selectedAssetId, true);
}

function initDepGroups() {
  const state = depGroupState();
  DEP_GROUP_KEYS.forEach(k => applyDepGroup(k, state[k]));
}

function renderVizVisitors(id) {
  const box = document.getElementById("viz-visitors");
  const rows = VISIT_CACHE[id] || [];
  if (!rows.length) {
    box.innerHTML = '<div class="rail-empty">近 24 小时还没有访问记录。</div>';
    return;
  }
  box.innerHTML = rows.map(v => {
    const meta = [v.device, v.country, v.browser].filter(Boolean).join(" · ") || "未知设备";
    const path = v.path || "/";
    return '<div class="viz-visitor"><span class="v-name">' + esc(path) +
      '</span><span class="v-meta">' + esc(meta) + " · " +
      esc(fmtVisitTime(v.ts)) + "</span></div>";
  }).join("");
}

async function loadVizVisits(id, force) {
  if (!id) return;
  const snap = typeof currentSnapshot === "function" ? currentSnapshot() : null;
  if (snap) {
    document.getElementById("dep-visitors-note").textContent = "停止时已清理";
    document.getElementById("viz-visitors").innerHTML =
      '<div class="rail-empty">访问明细随停止清理；上方 PV/UV 为停止前统计。</div>';
    return;
  }
  const a = currentAsset();
  if (!a) return;
  if (!a.proxy_port) {
    document.getElementById("dep-visitors-note").textContent = "无代理";
    document.getElementById("viz-visitors").innerHTML =
      '<div class="rail-empty">该条目没有经过内置代理，没有访客明细。</div>';
    return;
  }
  if (!force && VISITS_LOADED.has(id)) {
    renderVizVisitors(id);
    return;
  }
  VISITS_LOADED.add(id);
  const d = await api("/api/visits?id=" + encodeURIComponent(id));
  if (!d.ok || selectedAssetId !== id) return;
  VISIT_CACHE[id] = (d.data && d.data.recent) || [];
  renderVizVisitors(id);
}
