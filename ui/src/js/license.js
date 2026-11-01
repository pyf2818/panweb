// ---------- 买断许可 ----------
function licenseModeText(st) {
  if (!st) return "读取中…";
  if (st.mode === "development") return "开发版";
  if (st.mode === "active") return "已激活";
  if (st.mode === "trial") {
    return st.trial_days_left != null ? "试用剩余 " + st.trial_days_left + " 天" : "试用中";
  }
  if (st.mode === "expired") return "试用已结束";
  if (st.mode === "invalid") return "许可无效";
  return st.message || "未激活";
}

function renderLicense() {
  const st = STATE && STATE.license;
  if (!st) return;
  const label = licenseModeText(st);
  const btn = document.getElementById("license-btn");
  if (btn) {
    btn.textContent = "许可：" + label;
    btn.classList.toggle("warn", !st.can_publish);
    btn.title = st.message + (st.hint ? " · " + st.hint : "");
  }
  const mode = document.getElementById("lic-mode");
  if (mode) {
    mode.textContent = label;
    mode.classList.toggle("warn-text", !st.can_publish);
  }
  const detail = document.getElementById("lic-detail");
  if (detail) {
    detail.textContent = st.message + (st.hint ? " · " + st.hint : "");
  }
  const banner = document.getElementById("license-banner");
  if (banner) {
    const need = !!st.activation_required;
    banner.style.display = need ? "flex" : "none";
    if (need) {
      document.getElementById("license-banner-title").textContent = label;
      document.getElementById("license-banner-text").textContent =
        " · " + (st.hint || st.message || "请激活后继续发布");
    }
  }
  const summary = document.getElementById("license-summary");
  if (summary) {
    summary.textContent = st.message + (st.hint ? " · " + st.hint : "");
  }
  const current = document.getElementById("license-current");
  if (current) {
    const lines = [];
    if (st.mode !== "development") {
      lines.push("状态：" + st.message);
      if (st.license_id) lines.push("许可编号：" + st.license_id);
      if (st.updates_until_text) lines.push("更新权益：" + st.updates_until_text);
      if (st.trial_ends_text && st.mode === "trial") lines.push("试用到期：" + st.trial_ends_text);
    }
    if (st.machine) lines.push("本机指纹：" + st.machine);
    if (st.mode === "development") {
      lines.push("此构建未启用许可校验，所有功能可用。");
    }
    current.textContent = lines.join("\n");
  }
  const deact = document.getElementById("license-deactivate");
  if (deact) deact.style.display = st.mode === "active" ? "" : "none";
}

function openLicense() {
  renderLicense();
  const key = document.getElementById("license-key");
  if (key) key.value = "";
  document.getElementById("license-overlay").classList.add("show");
  setTimeout(() => { if (key) key.focus(); }, 120);
}

function closeLicense() {
  document.getElementById("license-overlay").classList.remove("show");
}

async function activateLicenseKey() {
  const keyEl = document.getElementById("license-key");
  const btn = document.getElementById("license-activate");
  const key = (keyEl.value || "").trim();
  if (!key) { toast("请粘贴许可密钥", false); keyEl.focus(); return; }
  if (btn) { btn.disabled = true; btn.textContent = "激活中…"; }
  const d = await api("/api/license/activate", {key});
  if (btn) { btn.disabled = false; btn.textContent = "激活"; }
  if (!d.ok) { toast(d.error ? d.error.message : "激活失败", false); return; }
  STATE.license = d.data;
  renderLicense();
  closeLicense();
  await refresh();
  toast("许可已激活 🎉");
}

async function deactivateLicenseKey() {
  if (!confirm("解除本机绑定？许可密钥仍可在本机或其他设备重新激活。")) return;
  const d = await api("/api/license/deactivate", {});
  if (!d.ok) { toast(d.error ? d.error.message : "解除失败", false); return; }
  closeLicense();
  await refresh();
  toast("已解除本机绑定");
}
