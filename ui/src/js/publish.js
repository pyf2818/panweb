// ---------- 发布弹窗 ----------
let pubTab = "port";
let pubDefaults = null;
let pubPoll = null;
const PUB_PIN_KEY = "panweb.pin";

function storedPin() {
  try { return sessionStorage.getItem(PUB_PIN_KEY) || ""; } catch (e) { return ""; }
}
function rememberPin(pin) {
  try {
    if (pin) sessionStorage.setItem(PUB_PIN_KEY, pin);
    else sessionStorage.removeItem(PUB_PIN_KEY);
  } catch (e) { /* 隐私模式禁用存储也不影响发布 */ }
}

function openPublish(tab) {
  if (STATE && STATE.license && STATE.license.activation_required) {
    toast("试用已结束，请先激活买断版", false);
    openLicense();
    return;
  }
  pubTab = tab || "port";
  switchTab(pubTab);
  document.getElementById("in-name").value = "";
  document.getElementById("in-title").value = "";
  document.getElementById("in-desc").value = "";
  document.getElementById("in-port").value = "";
  document.getElementById("in-folder").value = "";
  document.getElementById("in-project").value = "";
  document.getElementById("in-pin").value = storedPin();
  document.getElementById("in-share").checked = true;
  document.getElementById("in-exp").value = "";
  document.getElementById("in-files").value = "";
  document.getElementById("in-cloudfolder").value = "";
  document.getElementById("detect-line").className = "detect-line";
  selPort = null; selPortRisky = null; detected = null;
  resetPubFeedback();
  updateRisk();
  document.getElementById("pub-overlay").classList.add("show");
  loadPublishOptions();
  setTimeout(() => {
    const el = pubTab === "port" ? "in-port" : pubTab === "pages" ? "in-folder"
      : pubTab === "cloud" ? "in-cloudfolder" : "in-project";
    document.getElementById(el).focus();
  }, 120);
}
function closePublish() {
  document.getElementById("pub-overlay").classList.remove("show");
  if (pubPoll) { clearInterval(pubPoll); pubPoll = null; }
}
function resetPubFeedback() {
  const btn = document.getElementById("pub-btn");
  if (btn) {
    btn.disabled = false;
    btn.textContent = pubTab === "project" ? "启动并发布"
      : pubTab === "cloud" ? "上传并托管" : "发布";
  }
  hidePubError();
  const box = document.getElementById("pub-progress");
  if (box) { box.hidden = true; document.getElementById("pub-steps").innerHTML = ""; }
}
function hidePubError() {
  const box = document.getElementById("pub-error");
  if (box) { box.hidden = true; box.innerHTML = ""; }
}
function switchTab(tab) {
  pubTab = tab;
  ["port", "pages", "project", "cloud"].forEach(t =>
    document.getElementById("tab-" + t).classList.toggle("active", t === tab));
  document.getElementById("pane-port").style.display = tab === "port" ? "" : "none";
  document.getElementById("pane-pages").style.display = tab === "pages" ? "" : "none";
  document.getElementById("pane-project").style.display = tab === "project" ? "" : "none";
  document.getElementById("pane-cloud").style.display = tab === "cloud" ? "" : "none";
  document.getElementById("pin-field").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("title-field").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("desc-field").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("share-line").style.display = tab === "cloud" ? "none" : "flex";
  document.getElementById("share-hint").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("in-share").disabled = tab === "pages";
  if (tab === "pages") document.getElementById("in-share").checked = true;
  document.getElementById("share-hint").textContent = tab === "pages"
    ? "文件夹发布默认经由内置代理，分享页与访问统计自动开启。"
    : "分享链接会先展示应用名、说明、有效期和口令入口；取消勾选则直连发布（更快，但无统计）。";
  document.getElementById("in-exp").closest(".field").style.display = tab === "cloud" ? "none" : "";
  document.getElementById("pub-btn").textContent =
    tab === "project" ? "启动并发布" : tab === "cloud" ? "上传并托管" : "发布";
  updateRisk();
}
async function loadPublishOptions() {
  const list = document.getElementById("cand-list");
  if (pubTab === "port") list.innerHTML = '<div class="feed-empty">扫描中…</div>';
  const d = await api("/api/publish-defaults");
  if (!d.ok) {
    if (pubTab === "port")
      list.innerHTML = '<div class="feed-empty">扫描失败，可直接输入端口</div>';
    applyStoredDefaults({});
    return;
  }
  const defaults = d.data.defaults || {};
  applyStoredDefaults(defaults);
  if (pubTab === "port") renderCandidates(d.data.candidates || [], defaults);
}
function applyStoredDefaults(d) {
  pubDefaults = d || {};
  const exp = document.getElementById("in-exp");
  if (exp && !exp.value) exp.value = pubDefaults.expires || "";
  if (pubTab !== "pages")
    document.getElementById("in-share").checked = pubDefaults.share !== false;
  const folder = document.getElementById("in-folder");
  const project = document.getElementById("in-project");
  if (folder && !folder.value && pubDefaults.last_folder) folder.value = pubDefaults.last_folder;
  if (project && !project.value && pubDefaults.last_project) project.value = pubDefaults.last_project;
  const bits = [];
  if (pubDefaults.last_port) bits.push("上次端口 " + pubDefaults.last_port);
  if (pubDefaults.expires) bits.push("上次有效期 " + pubDefaults.expires);
  if (storedPin()) bits.push("口令沿用本标签页");
  const note = document.getElementById("pub-smart");
  if (bits.length) {
    note.textContent = "已按上次设置预填：" + bits.join(" · ") + "（可随时改）";
    note.hidden = false;
  } else {
    note.hidden = true;
  }
}
function renderCandidates(cands, defaults) {
  const list = document.getElementById("cand-list");
  if (!cands.length) {
    list.innerHTML = '<div class="feed-empty">没有发现正在运行的应用<br>可先在本地启动项目，或到「启动项目」让 panweb 替你启动</div>';
    return;
  }
  list.innerHTML = cands.map(c =>
    '<div class="cand" data-port="' + c.port + '" data-risky="' + esc(c.risky || "") + '" onclick="selCand(this)">' +
    '<span class="c-port">' + c.port + '</span><span class="c-title">' + esc(c.title) + '</span>' +
    '<span class="c-proc">' + esc(c.process || "") + '</span>' +
    (c.published ? '<span class="c-risk" style="color:var(--accent);background:var(--accent-soft)">已发布</span>' : '') +
    (c.risky ? '<span class="c-risk">⚠ 高危</span>' : '') + '</div>').join("");
  // 少一步：上次用过的端口还在，或只有一个未发布候选，就直接选中
  const previous = Number(defaults && defaults.last_port);
  const fresh = cands.filter(c => !c.published);
  const pick = cands.find(c => c.port === previous) || (fresh.length === 1 ? fresh[0] : null);
  if (pick) {
    const el = list.querySelector('.cand[data-port="' + pick.port + '"]');
    if (el) selCand(el);
  }
}
function selCand(el) {
  document.querySelectorAll(".cand").forEach(x => x.classList.remove("sel"));
  el.classList.add("sel");
  selPort = el.dataset.port;
  selPortRisky = el.dataset.risky || null;
  document.getElementById("in-port").value = selPort;
  updateRisk();
}
function updateRisk() {
  const warn = document.getElementById("risk-warn");
  const check = document.getElementById("risk-check");
  const risky = pubTab === "port" ? selPortRisky : null;
  if (risky) {
    warn.textContent = "⚠ " + risky;
    warn.classList.add("show");
    check.style.display = "flex";
  } else {
    warn.classList.remove("show");
    check.style.display = "none";
    document.getElementById("risk-ack").checked = false;
  }
}

// 项目识别
async function detectProject() {
  const folder = document.getElementById("in-project").value.trim();
  const line = document.getElementById("detect-line");
  if (!folder) return;
  line.className = "detect-line show warn";
  line.textContent = "识别中…";
  const d = await api("/api/detect?folder=" + encodeURIComponent(folder));
  if (!d.ok) {
    line.className = "detect-line show err";
    line.textContent = d.error ? d.error.message : "识别失败";
    detected = null;
    return;
  }
  detected = d.data;
  if (detected.type === "static" || detected.type === "node") {
    line.className = "detect-line show ok";
    line.textContent = "✓ " + detected.detail + "，可以直接启动并发布";
  } else {
    line.className = "detect-line show warn";
    line.textContent = "△ " + detected.detail;
  }
}
let detectTimer = null;
document.addEventListener("input", e => {
  if (e.target && e.target.id === "in-project") {
    clearTimeout(detectTimer);
    detectTimer = setTimeout(detectProject, 700);
  }
});

async function doPublish() {
  const btn = document.getElementById("pub-btn");
  const pin = document.getElementById("in-pin").value.trim() || null;
  const expires = document.getElementById("in-exp").value || null;
  const share = document.getElementById("in-share").checked;
  const title = document.getElementById("in-title").value.trim() || null;
  const desc = document.getElementById("in-desc").value.trim() || null;
  let path, body;
  if (pubTab === "port") {
    const port = parseInt(document.getElementById("in-port").value, 10);
    if (!port) {
      // 留空不拦：服务端会挑上次端口或唯一候选；拿不准时会直接告诉我们
      body = {port: null, name: document.getElementById("in-name").value.trim() || null, pin, expires, share, title, desc};
      path = "/api/publish";
    } else {
      if (selPortRisky && String(port) === String(selPort) && !document.getElementById("risk-ack").checked)
        return toast("请先勾选「我了解风险」", false);
      body = {port, name: document.getElementById("in-name").value.trim() || null, pin, expires, share, title, desc};
      path = "/api/publish";
    }
  } else if (pubTab === "pages") {
    const folder = document.getElementById("in-folder").value.trim();
    if (!folder) return toast("请输入文件夹路径", false);
    body = {folder, name: document.getElementById("in-name").value.trim() || null, pin, expires, share: true, title, desc};
    path = "/api/pages";
  } else if (pubTab === "cloud") {
    const fileEl = document.getElementById("in-files");
    const folder = document.getElementById("in-cloudfolder").value.trim();
    const name = document.getElementById("in-name").value.trim() || null;
    if (fileEl.files && fileEl.files.length) {
      btn.disabled = true;
      btn.innerHTML = '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><path d="M21 12a9 9 0 11-6.2-8.56"/></svg> 上传中…';
      const files = [];
      for (const f of fileEl.files) {
        const buf = await f.arrayBuffer();
        let bin = "";
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.length; i += 0x8000)
          bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        files.push({path: f.name, content_b64: btoa(bin)});
      }
      body = {name, files};
      path = "/api/host-upload";
    } else if (folder) {
      body = {path: folder, name};
      path = "/api/host";
    } else {
      return toast("请选择文件或填写文件夹路径", false);
    }
  } else {
    const folder = document.getElementById("in-project").value.trim();
    if (!folder) return toast("请输入项目文件夹路径", false);
    if (detected && (detected.type === "python" || detected.type === "unknown"))
      return toast(detected.detail, false);
    body = {folder, name: document.getElementById("in-name").value.trim() || null,
            share, pin, expires, title, desc};
    path = "/api/run";
  }
  hidePubError();
  btn.disabled = true;
  const spin = '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:15px;height:15px"><path d="M21 12a9 9 0 11-6.2-8.56"/></svg> ';
  if (pubTab === "cloud") {
    btn.innerHTML = spin + "上传并部署中…（约 30-60 秒）";
    const d = await api(path, body);
    if (!d.ok) return pubFail(d.error);
    return pubDone(d.data);
  }
  const first = pubTab === "project" ? "准备启动项目…" : "准备发布…";
  showPubProgress({step: first, steps: [first], done: false});
  btn.innerHTML = spin + esc(first);
  // 慢动作异步跑：先拿 job id，再轮询步骤；失败时保留表单，方便直接重试
  const d = await api(path, Object.assign({}, body, {async: true}));
  if (!d.ok) return pubFail(d.error);
  if (!d.data.job) return pubDone(d.data);
  await pollPublish(d.data.job, btn, spin);
}

function showPubProgress(job) {
  const box = document.getElementById("pub-progress");
  const steps = job.steps || [];
  document.getElementById("pub-step").textContent = job.step || "准备中…";
  box.hidden = false;
  box.classList.toggle("done", !!job.done);
  // 头部已经显示当前步骤，列表只留走过的路径，避免同一句出现两遍
  const done = job.done ? steps : steps.slice(0, -1);
  document.getElementById("pub-steps").innerHTML = done.map(s =>
    '<li class="done">' + esc(s) + '</li>').join("");
  revealFeedback(box);
}
function revealFeedback(box) {
  if (!box || box.hidden) return;
  try { box.scrollIntoView({block: "center", behavior: "smooth"}); } catch (e) {}
}
function pubFail(err) {
  const btn = document.getElementById("pub-btn");
  btn.disabled = false;
  btn.textContent = pubTab === "project" ? "启动并发布" : pubTab === "cloud" ? "上传并托管" : "发布";
  const box = document.getElementById("pub-error");
  const msg = err && err.message ? err.message : "发布失败";
  const hint = err && err.hint ? err.hint : "";
  const extra = err && (err.type === "port_not_serving" || err.type === "ambiguous_port")
    ? '<button class="btn btn-sm" onclick="switchTab(\'project\')">去启动项目</button>' +
      '<button class="btn btn-sm" onclick="switchTab(\'port\');loadPublishOptions()">重新扫描</button>'
    : "";
  box.innerHTML = '<div class="pe-title">' + esc(msg) + '</div>' +
    (hint ? '<div class="pe-hint">' + esc(hint) + '</div>' : "") +
    '<div class="pe-actions"><button class="btn btn-sm btn-primary" onclick="doPublish()">重试</button>' + extra + '</div>';
  box.hidden = false;
  document.getElementById("pub-progress").hidden = true;
  revealFeedback(box);
}
function pubDone(data) {
  if (pubPoll) { clearInterval(pubPoll); pubPoll = null; }
  rememberPin(document.getElementById("in-pin").value.trim());
  closePublish();
  toast("已发布：" + (data.share_url || data.url));
  refresh();
}
function pollPublish(jobId, btn, spin) {
  return new Promise(resolve => {
    const tick = async () => {
      const d = await api("/api/job?id=" + encodeURIComponent(jobId));
      if (!d.ok) {
        pubFail(d.error || {message: "任务状态丢失，请重试"});
        return resolve(false);
      }
      const job = d.data;
      showPubProgress(job);
      if (!job.done) {
        btn.innerHTML = spin + esc(job.step || "处理中…");
        return;
      }
      if (pubPoll) { clearInterval(pubPoll); pubPoll = null; }
      if (job.ok) {
        pubDone(job.result || {});
      } else {
        pubFail(job.error || {message: "发布失败"});
      }
      resolve(!!job.ok);
    };
    if (pubPoll) clearInterval(pubPoll);
    pubPoll = setInterval(tick, 600);
    tick();
  });
}
