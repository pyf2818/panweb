// ---------- 自检结论与上游兼容（访客视角能不能打开） ----------
const CHECK_UI = {
  ok: {chip: "✓ 可访问", text: "访客现在能正常打开"},
  warn: {chip: "△ 需留意", text: "大概率能用，但有坑"},
  blocked: {chip: "✕ 打不开", text: "访客现在打不开"},
};
const AUTH_FIELDS = {
  bearer: [["令牌", "Bearer 令牌（不含 “Bearer ” 前缀）", "password"]],
  basic: [["用户名", "上游用户名", "text"], ["密码", "上游密码", "password"]],
  header: [["头名称", "例如 X-Api-Key", "text"], ["头值", "这个头的值", "password"]],
};
let compatCache = null;

function checkBadge(a) {
  const c = a.check;
  if (!c || !CHECK_UI[c.verdict]) return "";
  const info = CHECK_UI[c.verdict];
  return '<span class="check-badge ' + c.verdict + '" title="' + esc(c.summary) + '">' +
    info.chip + '</span>';
}

function fmtCheckTs(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
    String(d.getDate()).padStart(2, "0") + " " + d.toTimeString().slice(0, 5);
}

function renderCheckSection(a) {
  const box = document.getElementById("dw-check");
  const stamp = document.getElementById("dw-check-ts");
  if (!box) return;
  const c = a.check;
  if (!c) {
    stamp.textContent = "";
    box.innerHTML = '<div class="feed-empty">还没有自检记录 · 点下面按钮按访客视角打开一次</div>';
    return;
  }
  stamp.textContent = "上次自检：" + fmtCheckTs(c.ts);
  const info = CHECK_UI[c.verdict] || {chip: "·", text: c.summary || ""};
  let html = '<div class="check-verdict ' + esc(c.verdict) + '">' +
    '<b>' + info.chip + '</b><span>' + esc(c.summary || info.text) + '</span></div>';
  (c.fixes || []).forEach(f => {
    html += '<div class="check-fix">🔧 ' + esc(f) + '</div>';
  });
  (c.signals || []).forEach(s => {
    if (s.severity === "info" || s.label === c.summary) return;
    html += '<div class="check-sig ' + esc(s.severity) + '">' + esc(s.label || s.code) +
      (s.advice ? '<div class="t">' + esc(s.advice) + '</div>' : '') + '</div>';
  });
  const infos = (c.signals || []).filter(s => s.severity === "info");
  if (infos.length) {
    html += '<div class="d-hint">' + infos.map(s => esc(s.label)).join(" · ") + '</div>';
  }
  box.innerHTML = html;
}

async function runCheck() {
  if (!currentDrawerId) return;
  const btn = document.getElementById("dw-check-btn");
  const label = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><path d="M21 12a9 9 0 11-6.2-8.56"/></svg> 自检中…（打开首页与引用资源）';
  const d = await api("/api/check", {id: currentDrawerId});
  btn.disabled = false;
  btn.textContent = label;
  if (!d.ok) return toast(d.error ? d.error.message : "自检失败", false);
  toast("自检：" + d.data.summary, d.data.verdict === "ok");
  await refresh();
  loadDetail();
}

// ---------- 上游兼容 ----------
async function loadCompat(id) {
  const d = await api("/api/compat?id=" + encodeURIComponent(id));
  if (!d.ok) return;
  compatCache = d.data;
  renderCompat(d.data);
}

function renderCompat(c) {
  const sel = document.getElementById("dw-hostmode");
  if (!sel) return;
  sel.innerHTML = (c.host_modes || []).map(m =>
    '<option value="' + esc(m.value) + '"' + (m.value === c.host_mode ? " selected" : "") + '>' +
    esc(m.label) + '</option>').join("");
  const kind = document.getElementById("dw-auth-kind");
  const save = document.getElementById("dw-auth-save");
  const proxied = c.proxied !== false;
  kind.value = (c.auth && c.auth.kind) || "";
  [sel, kind, save].forEach(el => { el.disabled = !proxied; });
  document.getElementById("dw-hostmode-hint").textContent = !proxied
    ? "这是直连发布：隧道直接指向应用端口，panweb 不在请求链路上，所以这里改不动。要治 Host 校验或代填凭据，重新发布时勾选「分享页 + 访问统计」（或设置访问口令），让流量经过内置代理。"
    : (c.host_mode === "tunnel"
      ? "上游会看到访客正在用的公网域名（Host 与 X-Forwarded-Host 一起补上）。Jupyter、Grafana、n8n、Open WebUI、Vite 开发服务器这类会校验 Host 防重绑定的应用需要这个。"
      : "上游只看到本机地址（127.0.0.1:端口），只肯服务 localhost 的开发服务器用这个。");
  renderAuthFields();
}

function renderAuthFields() {
  const kind = document.getElementById("dw-auth-kind").value;
  const box = document.getElementById("dw-auth-fields");
  const auth = compatCache && compatCache.auth;
  const same = auth && auth.kind === kind;
  if (!kind) {
    box.innerHTML = '<div class="d-hint">' +
      (auth ? "已注入：" + esc(auth.label) + "；把种类选成「不注入」并保存即可清除。"
            : "没有替访客带上应用自己的凭据。") + '</div>';
    return;
  }
  box.innerHTML = (AUTH_FIELDS[kind] || []).map((f, i) => {
    const secret = f[2] === "password";
    const val = secret ? "" : (same ? (auth.user || auth.name || "") : "");
    const ph = secret && same ? "已保存 · 要改就填新值" : (val || f[1]);
    return '<div class="d-field" style="margin-top:7px"><input type="' + f[2] +
      '" id="dw-auth-' + i + '" value="' + esc(val) + '" placeholder="' + esc(ph) +
      '" autocomplete="off" spellcheck="false"></div>';
  }).join("") +
    '<div class="d-hint">已保存的密钥不会回显；要修改就把每一项重新填全。' +
    '密钥只写进本机 ~/.panweb/secrets（0600），控制台、命令行和分享页都只显示种类。</div>';
}

async function saveHostMode() {
  if (!currentDrawerId) return;
  const mode = document.getElementById("dw-hostmode").value;
  const d = await api("/api/compat", {id: currentDrawerId, host_mode: mode});
  if (!d.ok) return toast(d.error ? d.error.message : "设置失败", false);
  compatCache = d.data;
  renderCompat(d.data);
  toast("Host 模式已切换，正在按访客视角复验…");
  await runCheck();
}

async function saveAuth() {
  if (!currentDrawerId) return;
  const kind = document.getElementById("dw-auth-kind").value;
  const body = {id: currentDrawerId};
  if (!kind) {
    body.clear_auth = true;
  } else {
    const vals = (AUTH_FIELDS[kind] || []).map((f, i) =>
      (document.getElementById("dw-auth-" + i).value || "").trim());
    // 已保存的密钥不回显，所以改任何一项都要填全——少了这一条就没法判断是改还是留。
    if (vals.some(v => !v)) {
      return toast("请把每一项都填全（已保存的密钥不会回显）", false);
    }
    body.auth_kind = kind;
    if (kind === "bearer") body.token = vals[0];
    else if (kind === "basic") { body.user = vals[0]; body.password = vals[1]; }
    else { body.header_name = vals[0]; body.header_value = vals[1]; }
  }
  const d = await api("/api/compat", body);
  if (!d.ok) return toast(d.error ? d.error.message : "保存失败", false);
  compatCache = d.data;
  renderCompat(d.data);
  toast(body.clear_auth ? "已清除上游凭据" : "已保存，只存在本机");
  await refresh();
}
