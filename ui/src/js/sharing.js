// ---------- 分享卡片 ----------
function roundRectPath(x, y, w, h, r) {
  const ctx = this;
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
async function genShareCard() {
  const a = (STATE.apps || []).find(x => x.id === currentDrawerId);
  if (!a) return;
  const url = a.share_url || a.url;
  const c = document.createElement("canvas");
  c.width = 900; c.height = 520;
  const x = c.getContext("2d");
  const g = x.createLinearGradient(0, 0, 900, 520);
  g.addColorStop(0, "#f7f6f2"); g.addColorStop(1, "#e9f2ee");
  x.fillStyle = g; x.fillRect(0, 0, 900, 520);
  x.fillStyle = "#ffffff";
  roundRectPath.call(x, 40, 40, 820, 440, 28); x.fill();
  x.strokeStyle = "#e9e6de"; roundRectPath.call(x, 40, 40, 820, 440, 28); x.stroke();
  x.fillStyle = "#22312e"; x.font = "600 46px 'PingFang SC', 'Noto Serif SC', sans-serif";
  x.fillText(a.name.slice(0, 14), 80, 132);
  x.fillStyle = "#8a968f"; x.font = "22px sans-serif";
  x.fillText("已在 panweb 上线，扫码或点链接访问", 80, 174);
  x.fillStyle = "#2a6558"; x.font = "600 22px 'SF Mono', monospace";
  x.fillText(url.slice(0, 44), 80, 228);
  x.fillStyle = "#b9975b"; x.font = "20px sans-serif";
  let y = 268;
  if (a.pinned) { x.fillText("已设置访问口令，口令向主人索取", 80, y); y += 34; }
  if (a.expires_at) { x.fillText("有效期至 " + new Date(a.expires_at * 1000).toLocaleString(), 80, y); y += 34; }
  if (a.desc) { x.fillStyle = "#6d7a73"; x.font = "19px sans-serif"; x.fillText(a.desc.slice(0, 34), 80, y); }
  const q = qrcode(0, "M"); q.addData(url); q.make();
  const img = new Image();
  await new Promise(res => { img.onload = res; img.src = q.createDataURL(7, 2); });
  x.drawImage(img, 624, 88, 196, 196);
  x.fillStyle = "#8a968f"; x.font = "16px sans-serif";
  x.fillText(a.share_url ? "扫码打开分享页" : "扫码直接打开", 668, 312);
  x.fillStyle = "#33796b"; x.font = "600 24px sans-serif";
  x.fillText("◈ panweb", 80, 432);
  x.fillStyle = "#b3bdb7"; x.font = "17px sans-serif";
  x.fillText("免费 · 零服务器 · 一句话发布", 80, 460);
  const dataUrl = c.toDataURL("image/png");
  document.getElementById("share-img").src = dataUrl;
  document.getElementById("share-dl").href = dataUrl;
  document.getElementById("share-preview").style.display = "block";
}
function shareText(a) {
  const url = a.share_url || a.url;
  const exp = a.expires_at ? "（" + fmtRemain(a.expires_at) + "后失效）" : "";
  const pin = a.pinned ? "（口令向主人索取）" : "";
  return "【" + a.name + "】已上线：" + url + pin + exp + " —— 点链接或扫码即可访问";
}
function openSharePage() {
  const a = (STATE.apps || []).find(x => x.id === currentDrawerId);
  if (a) openUrl(a.share_url || a.url, a.id);
}
async function saveShareDesc() {
  const a = (STATE.apps || []).find(x => x.id === currentDrawerId);
  if (!a) return;
  const desc = document.getElementById("dw-share-desc").value.trim();
  const d = await api("/api/share", {id: currentDrawerId, desc});
  if (!d.ok) return toast(d.error ? d.error.message : "保存失败", false);
  toast(desc ? "分享页说明已更新" : "分享页说明已移除");
  await refresh();
  loadDetail();
}
async function enableShare() {
  const a = (STATE.apps || []).find(x => x.id === currentDrawerId);
  if (!a) return;
  const d = await api("/api/share", {id: currentDrawerId, desc: ""});
  if (!d.ok) return toast(d.error ? d.error.message : "启用失败", false);
  toast("分享页已启用");
  await refresh();
  loadDetail();
}
function copyShareText() {
  const a = (STATE.apps || []).find(x => x.id === currentDrawerId);
  if (a) copyText(shareText(a));
}
async function copyShareImg() {
  const src = document.getElementById("share-img").src;
  if (!src) return toast("先点「生成分享图」", false);
  try {
    const blob = await (await fetch(src)).blob();
    await navigator.clipboard.write([new ClipboardItem({"image/png": blob})]);
    toast("图片已复制，可直接粘贴到微信");
  } catch (e) {
    toast("此浏览器不支持复制图片，请用「下载 PNG」", false);
  }
}

// ---------- 固定域名 ----------
async function loadDomain() {
  const d = await api("/api/domain");
  const body = document.getElementById("dm-body");
  if (!d.ok) { body.innerHTML = '<div class="feed-empty">读取失败</div>'; return; }
  STATE.domain = d.data;
  if (!d.data.cert) {
    body.innerHTML = '<div class="dm-step"><span style="font-size:12.5px;color:var(--muted)">第一步：授权 Cloudflare（浏览器登录一次）</span>' +
      '<button class="btn btn-sm btn-primary" onclick="domainLogin()">授权 Cloudflare</button></div>' +
      '<div class="d-hint">授权完成后本页会自动识别，再填域名启用。</div>';
    return;
  }
  if (!d.data.configured) {
    body.innerHTML = '<div class="dm-step">✅ 已授权 <input class="dm-input" id="dm-domain" placeholder="例如 demo.你的域名.com">' +
      '<button class="btn btn-sm btn-primary" id="dm-go" onclick="domainSetup()">启用固定域名</button></div>' +
      '<div class="d-hint">将自动创建命名隧道并写入 DNS 路由（约 10-30 秒）。启用后在应用详情里「绑定」。</div>';
    return;
  }
  body.innerHTML = '<div class="dm-step">🟢 <span style="font-family:var(--mono)">' + esc(d.data.domain) + '</span>' +
    (d.data.running ? "" : ' <span class="ag-state st-no">进程已停止</span>') +
    '<span style="flex:1"></span>' +
    '<button class="btn btn-sm btn-danger" onclick="domainTeardown()">停用</button></div>' +
    '<div class="d-hint">在应用详情的「设置」里点「设为固定域名应用」即可绑定（同一时间绑定一个应用）。</div>';
}
async function domainLogin() {
  const d = await api("/api/domain/login", {});
  if (!d.ok) return toast(d.error ? d.error.message : "失败", false);
  toast("浏览器已打开 Cloudflare 授权页，完成后回到这里");
}
async function domainSetup() {
  const btn = document.getElementById("dm-go");
  const domain = document.getElementById("dm-domain").value.trim();
  if (!domain) return toast("请输入域名", false);
  btn.disabled = true; btn.textContent = "配置中…（10-30 秒）";
  const d = await api("/api/domain/setup", {domain});
  btn.disabled = false; btn.textContent = "启用固定域名";
  if (!d.ok) return toast(d.error ? d.error.message : "配置失败", false);
  toast("固定域名已启用：" + d.data.domain);
  await loadDomain();
}
async function bindDomain(id) {
  const d = await api("/api/domain/bind", {id});
  if (!d.ok) return toast(d.error ? d.error.message : "绑定失败", false);
  toast(id ? "已绑定到固定域名" : "已解绑");
  await refresh();
  if (currentDrawerId) loadDetail();
}
async function domainTeardown() {
  if (!confirm("停用固定域名？绑定它的应用会回到随机网址。")) return;
  const d = await api("/api/domain/teardown", {});
  if (!d.ok) return toast("停用失败", false);
  toast("固定域名已停用");
  await loadDomain();
}

// ---------- 一键安装 / 菜单栏 ----------
async function installCF() {
  toast("开始安装 cloudflared（约 1-2 分钟）…");
  const d = await api("/api/install-cf", {});
  if (!d.ok) return toast(d.error ? d.error.message : "安装失败", false);
  if (d.data.already) { await refresh(); return toast("cloudflared 已安装"); }
  const timer = setInterval(async () => {
    const s = await api("/api/install-cf/status");
    if (s.ok && s.data.ready) {
      clearInterval(timer);
      toast("cloudflared 安装完成 🎉");
      await refresh();
    }
  }, 3000);
}
async function installMenubar() {
  const d = await api("/api/install-menubar", {});
  if (!d.ok) return toast(d.error ? d.error.message : "安装失败", false);
  toast("菜单栏已安装并启动（屏幕右上角 ◈），可从系统退出");
}
async function saveRename() {
  const name = document.getElementById("dw-rename").value.trim();
  if (!name) return toast("名称不能为空", false);
  const d = await api("/api/rename", {id: currentDrawerId, name});
  if (!d.ok) return toast(d.error ? d.error.message : "改名失败", false);
  toast("已改名：" + name);
  await refresh();
}
async function savePin() {
  const pin = document.getElementById("dw-pin").value.trim();
  const d = await api("/api/pin", {id: currentDrawerId, pin});
  if (!d.ok) return toast(d.error ? d.error.message : "设置失败", false);
  if (d.data.updated && d.data.entry) {
    toast("口令已更新（网址已更换）");
    await refresh();
    const nid = d.data.entry.id;
    currentDrawerId = nid;
    loadDetail();
  } else {
    toast(pin ? "口令已生效，立即热更新" : "口令已移除");
    document.getElementById("dw-pin").value = "";
    await refresh();
    loadDetail();
  }
}

// ---------- 停止 ----------
function askStop(id, name) {
  stopTarget = id;
  document.getElementById("stop-sub").textContent = "停止「" + name + "」后网址立即失效；若该应用由 panweb 启动，应用进程也会一并停止。";
  document.getElementById("stop-overlay").classList.add("show");
}
async function doStop() {
  if (!stopTarget) return;
  const d = await api("/api/stop", {target: stopTarget});
  document.getElementById("stop-overlay").classList.remove("show");
  if (!d.ok) {
    const err = d.error || {};
    toast(err.message || "停止失败", false);
    if (typeof addError === "function") addError(err.message || "停止失败", err.hint || "稍后重试", null);
    return;
  }
  toast("已停止发布");
  if (typeof addResult === "function") addResult("<b>已停止发布</b>");
  if (stopTarget === selectedAssetId) selectedAssetId = null;
  stopTarget = null;
  await refresh();
}
document.getElementById("stop-btn").addEventListener("click", doStop);
document.querySelectorAll(".overlay").forEach(ov =>
  ov.addEventListener("click", e => { if (e.target === ov) ov.classList.remove("show"); }));
document.addEventListener("keydown", e => {
  if (e.key === "Escape") document.querySelectorAll(".overlay").forEach(ov => ov.classList.remove("show"));
});

