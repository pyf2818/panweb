// ---------- 终端页：驱动本机 Agent 命令行，让它替你部署 ----------
let tmAgents = [];
let tmAgent = null;
let tmSession = null;
let tmTimer = null;
let tmAfter = 0;
let tmBusy = false;

const TM_QUICK = [
  ["列一发", "看看这台电脑上有哪些能发布的应用，挑一个发出去，给我一个手机上能打开的网址"],
  ["发文件夹", "把这个文件夹发布成只读网页：<填一个本机目录>"],
  ["启动项目", "帮我启动这个项目并发布到公网：<项目目录>"],
  ["打不开", "我有个发布打开只有壳/一直转圈，帮我自检一下并修好"],
  ["收掉", "把现在公开的发布都停掉，然后告诉我停了几条"]
];

function tmLed(status) {
  const led = document.getElementById("tm-led");
  if (led) led.className = "tm-led " + (status || "idle");
}

function tmAppend(text, cls) {
  const out = document.getElementById("tm-out");
  if (!text) return;
  const empty = out.querySelector(".feed-empty");
  if (empty) empty.remove();
  const line = document.createElement("div");
  line.className = "tm-line" + (cls ? " " + cls : "");
  line.textContent = text;
  out.appendChild(line);
  while (out.childElementCount > 900) out.removeChild(out.firstElementChild);
  out.scrollTop = out.scrollHeight;
}

function tmEcho(text) {
  tmAppend("你 › " + text, "tm-you");
}

async function tmLoadAgents() {
  const d = await api("/api/agent/agents");
  if (!d.ok) return;
  tmAgents = d.data.agents || [];
  const box = document.getElementById("tm-agents");
  box.innerHTML = tmAgents.map(a =>
    '<button class="tm-pill' + (a.ready ? "" : " off") + (a.id === tmAgent ? " on" : "") +
    '" onclick="tmPick(\'' + a.id + '\')">' + esc(a.name) +
    (a.connected ? '<i title="已装 panweb 技能">✓技能</i>' : '<i class="warn" title="还没装 panweb 技能">无技能</i>') +
    (a.ready ? "" : '<i class="warn">未安装</i>') + '</button>').join("") ||
    '<div class="feed-empty">没找到可用的 Agent 命令行</div>';
  if (!tmAgent) {
    const first = tmAgents.find(a => a.ready);
    if (first) tmPick(first.id);
  }
}

function tmPick(id) {
  tmAgent = id;
  const a = tmAgents.find(x => x.id === id) || {};
  const note = document.getElementById("tm-note");
  note.innerHTML = '<b>' + esc(a.name || id) + '</b> · ' + esc(a.note || "") +
    (a.connected ? "" : ' · 这个 Agent 还没装 panweb 技能，去「连接 Agent」点一下连接，它会更快上手');
  document.querySelectorAll(".tm-pill").forEach(el =>
    el.classList.toggle("on", el.textContent.startsWith(a.name || id)));
}

async function tmStart() {
  const cwd = document.getElementById("tm-cwd").value.trim();
  const d = await api("/api/agent/start", {agent: tmAgent, cwd: cwd});
  if (!d.ok) return toast(d.error.message + (d.error.hint ? " · " + d.error.hint : ""), false);
  tmSession = d.data.id;
  tmAfter = 0;
  document.getElementById("tm-title").textContent =
    (tmAgents.find(a => a.id === d.data.agent) || {}).name + " · " + d.data.cwd;
  toast("终端已启动");
  tmPoll();
}

async function tmSend() {
  const box = document.getElementById("tm-text");
  const text = box.value.trim();
  if (!text) return;
  if (!tmSession) {
    const cwd = document.getElementById("tm-cwd").value.trim();
    const d = await api("/api/agent/start", {agent: tmAgent, cwd: cwd, text: text});
    if (!d.ok) return toast(d.error.message + (d.error.hint ? " · " + d.error.hint : ""), false);
    tmSession = d.data.id;
    tmAfter = 0;
    document.getElementById("tm-title").textContent =
      (tmAgents.find(a => a.id === d.data.agent) || {}).name + " · " + d.data.cwd;
    box.value = "";
    tmEcho(text);
    tmPoll();
    return;
  }
  const d = await api("/api/agent/send", {id: tmSession, text: text});
  if (!d.ok) return toast(d.error.message, false);
  box.value = "";
  tmEcho(text);
  tmPoll();
}

async function tmStop() {
  if (!tmSession) return;
  const d = await api("/api/agent/stop", {id: tmSession});
  if (d.ok) toast("已停止这一轮");
}

function tmClear() {
  const out = document.getElementById("tm-out");
  out.innerHTML = '<div class="feed-empty">已清屏。继续说就行。</div>';
}

async function tmPoll() {
  if (!tmSession || tmBusy) return;
  tmBusy = true;
  let s = null;
  try {
    const d = await api("/api/agent/output?id=" + encodeURIComponent(tmSession) +
                        "&after=" + tmAfter);
    if (d.ok) s = d.data;
    else if (d.error && d.error.type === "not_found") { tmStopPolling(); tmBusy = false; return toast("会话已经不在了", false); }
  } finally {
    tmBusy = false;
  }
  if (!s) return;                       // 偶发的网络/服务抖动：下一轮再试，别就此停住
  if (s.text) tmAppend(s.text);
  tmAfter = s.after;
  tmLed(s.status);
  const state = document.getElementById("tm-state");
  document.getElementById("tm-stop").disabled = s.status !== "running";
  if (s.status === "running") {
    const secs = Math.max(0, Math.round(Date.now() / 1000 - s.since));
    state.textContent = "正在思考 · " + secs + "s";
    return;
  }
  if (s.error) {
    state.textContent = "· " + s.error;
    tmAppend("⚠ " + s.error, "tm-err");
  } else {
    state.textContent = "· 空闲";
  }
  tmStopPolling();
}

function tmStopPolling() {
  if (tmTimer) { clearInterval(tmTimer); tmTimer = null; }
}

function tmStartPolling() {
  if (!tmTimer) tmTimer = setInterval(tmPoll, 900);
}

function tmInitPage() {
  tmLoadAgents();
  const quick = document.getElementById("tm-quick");
  if (quick && !quick.childElementCount) {
    quick.innerHTML = TM_QUICK.map(q =>
      '<button class="tm-chip" onclick="tmFill(this)" data-t="' + esc(q[1]) + '">' +
      esc(q[0]) + '</button>').join("");
  }
  const box = document.getElementById("tm-text");
  if (box && !box.dataset.wired) {
    box.dataset.wired = "1";
    box.addEventListener("keydown", ev => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        tmSend();
      }
    });
  }
  if (tmSession) tmPoll();
  tmStartPolling();
}

function tmFill(btn) {
  const box = document.getElementById("tm-text");
  box.value = btn.dataset.t;
  box.focus();
}
