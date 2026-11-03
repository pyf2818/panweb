// ---------- 终端页：把本机 Agent 的真终端（PTY）挂进网页 ----------
// 这一页只搬运字节：键盘直通进去，画面原样出来，所以彩色、进度条、分页器、
// Ctrl+C、↑↓ 翻历史都按 Agent 自己的样子工作。
let tmAgents = [];
let tmAgent = null;
let tmTerm = null;
let tmFit = null;
let tmStream = null;
let tmSession = null;
let tmOffset = 0;
let tmDead = false;
let tmRetry = null;
let tmQueue = Promise.resolve();
let tmFails = 0;
let tmSessions = [];

const TM_RETRY_MAX = 6;
// 点一下就把话打进取代手敲；回车由主人自己按，不替你做决定
const TM_QUICK = [
  ["看能发什么", "看看这台电脑上有哪些能发布的应用，列给我，再挑一个发到公网"],
  ["发端口", "把 3000 端口发布到公网，给我一个手机上能打开的网址"],
  ["发文件夹", "把这个文件夹发布成只读网页："],
  ["启动项目", "帮我启动这个项目并发布到公网："],
  ["打不开", "我有个发布打开只有壳/一直转圈，帮我自检一下并修好"],
  ["收掉", "把现在公开的发布都停掉，然后告诉我停了几条"]
];

function tmB64ToBytes(text) {
  const bin = atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < out.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function tmBytesToB64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 8192) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 8192));
  }
  return btoa(s);
}

function tmEnsureTerm() {
  if (tmTerm) return tmTerm;
  tmTerm = new Terminal({
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: 12.5, lineHeight: 1.28, cursorBlink: true, scrollback: 5000,
    macOptionIsMeta: true, tabStopWidth: 4,
    theme: {background: "#0d1614", foreground: "#dfeae6", cursor: "#7fd6bb",
            selectionBackground: "#2f5a52"},
  });
  tmFit = new FitAddon.FitAddon();
  tmTerm.loadAddon(tmFit);
  // 画布渲染器：Agent 的 TUI 整屏重绘很频繁，DOM 渲染会明显跟不上
  try {
    tmTerm.loadAddon(new CanvasAddon.CanvasAddon());
  } catch (e) {
    /* 没有画布就用默认的 DOM 渲染，画面一样对 */
  }
  tmTerm.open(document.getElementById("tm-screen"));
  tmTerm.onData(data => tmInput(new TextEncoder().encode(data)));
  tmTerm.onResize(() => tmPushSize());
  window.addEventListener("resize", tmFitSoon);
  // 画面区的高度会被工具条/快捷语/标签挤来挤去，只有盯着容器本身才不会算错格数
  if (window.ResizeObserver) {
    new ResizeObserver(tmFitSoon).observe(document.getElementById("tm-screen"));
  }
  return tmTerm;
}

function tmFitSoon() {
  clearTimeout(tmFitSoon.t);
  tmFitSoon.t = setTimeout(() => {
    if (tmTerm && currentPage === "term") { tmFit.fit(); tmTerm.focus(); }
  }, 120);
}

// 把网页里的真实格数推给 PTY：子进程按这个尺寸重画，画面才对得上
// （只在 onResize 里发不够——刷新后 xterm 的格数没变，但 PTY 可能还是旧尺寸）
function tmPushSize() {
  if (tmSession && !tmDead && tmTerm) {
    api("/api/term/resize", {id: tmSession, cols: tmTerm.cols, rows: tmTerm.rows});
  }
}

function tmSyncSize() {
  if (!tmTerm) return;
  tmFit.fit();
  tmPushSize();
}

function tmInput(bytes) {
  if (!tmSession || tmDead) return;
  // 键盘字节必须按敲的顺序到 PTY：并发 fetch 会被不同线程处理，粘长文时会乱序
  const id = tmSession, data = tmBytesToB64(bytes);
  tmQueue = tmQueue.then(() => api("/api/term/input", {id, data}));
}

function tmLed(status) {
  const led = document.getElementById("tm-led");
  if (led) led.className = "tm-led " + (status || "idle");
}

function tmState(text) {
  const el = document.getElementById("tm-state");
  if (el) el.textContent = text || "";
}

async function tmLoadAgents() {
  const d = await api("/api/term/agents");
  if (!d.ok) return;
  tmAgents = d.data.agents || [];
  const box = document.getElementById("tm-agents");
  box.innerHTML = tmAgents.map(a =>
    '<button class="tm-pill' + (a.ready ? "" : " off") +
    (a.id === tmAgent ? " on" : "") + '" onclick="tmPick(\'' + a.id + '\')">' +
    esc(a.name) +
    (a.connected ? '<i title="已装 panweb 技能">✓技能</i>'
                 : '<i class="warn" title="还没装 panweb 技能">无技能</i>') +
    (a.ready ? "" : '<i class="warn">未安装</i>') + "</button>").join("") ||
    '<div class="feed-empty">没找到可用的 Agent 命令行</div>';
  if (!tmAgent) {
    const first = tmAgents.find(a => a.ready);
    if (first) tmPick(first.id);
  }
}

function tmPick(id) {
  tmAgent = id;
  const a = tmAgents.find(x => x.id === id) || {};
  document.getElementById("tm-note").textContent = (a.name || id) + " · " +
    (a.note || "") + (a.connected ? "" : " · 它还没装 panweb 技能，去「连接 Agent」点一下会更上手");
  document.querySelectorAll(".tm-pill").forEach(el =>
    el.classList.toggle("on", el.textContent.startsWith(a.name || id)));
}

async function tmLoadSessions() {
  const d = await api("/api/term/sessions");
  if (!d.ok) return;
  tmSessions = d.data.sessions || [];
  const box = document.getElementById("tm-tabs");
  box.innerHTML = tmSessions.map(s =>
    '<button class="tm-tab' + (s.id === tmSession ? " on" : "") +
    '" data-id="' + esc(s.id) + '" onclick="tmAttach(\'' + esc(s.id) + '\')">' +
    esc(s.name) + "<i>" + (s.alive ? "运行中" : "已退出") + "</i></button>").join("") ||
    '<div class="tm-hint">还没有终端：选好 Agent 和工作目录，点「开终端」。</div>';
  if (!tmSession && tmSessions.length) tmAttach(tmSessions[tmSessions.length - 1].id);
}

function tmDetachStream() {
  clearTimeout(tmRetry);
  if (tmStream) { tmStream.close(); tmStream = null; }
}

function tmConnect() {
  if (!tmSession) return;
  tmDetachStream();
  tmStream = new EventSource("/api/term/output?id=" +
                             encodeURIComponent(tmSession) + "&after=" + tmOffset);
  tmStream.onmessage = ev => { tmFails = 0; tmFrame(JSON.parse(ev.data)); };
  tmStream.onerror = () => {
    tmDetachStream();
    if (tmDead) return;
    tmFails += 1;
    if (tmFails > TM_RETRY_MAX) {       // 别再闷头重试：把话说明白
      tmLed("failed");
      tmState("连不上控制台了，这一屏是最后的画面（刷新页面可重连）");
      return;
    }
    tmState("与控制台的连接断了，正在重连 " + tmFails + "/" + TM_RETRY_MAX + "…");
    clearTimeout(tmRetry);
    tmRetry = setTimeout(tmConnect, 1200);   // 带着游标续接，别把画面重播一遍
  };
}

async function tmAttach(id) {
  if (!id || (id === tmSession && tmStream)) return;
  const s = tmSessions.find(x => x.id === id);
  tmDetachStream();
  tmSession = id;
  tmOffset = 0;
  tmDead = !(s ? s.alive : true);
  tmEnsureTerm().reset();
  document.getElementById("tm-title").textContent =
    s ? s.name + " · " + s.cwd : "终端 " + id;
  document.getElementById("tm-close").disabled = tmDead;
  document.querySelectorAll(".tm-tab").forEach(el =>
    el.classList.toggle("on", el.dataset.id === id));
  if (tmDead) { tmLed("stopped"); tmState("这个终端里的程序已经退出"); }
  else { tmLed("running"); tmState("已连接 · 键盘直通"); }
  tmConnect();
  // 等布局落定再对尺寸：PTY 与网页画面必须同一格数，否则整屏重绘会错位
  requestAnimationFrame(tmSyncSize);
  setTimeout(tmSyncSize, 260);
}

function tmFrame(f) {
  if (f.meta) {
    document.getElementById("tm-title").textContent =
      f.meta.name + " · " + f.meta.cwd;
    if (!f.meta.alive) { tmDead = true; tmExit(f.meta.exit_code); }
    return;
  }
  if (typeof f.o === "number") tmOffset = f.o;
  if (f.gap) {
    // 输出太快、环形缓冲把旧的丢了：接着画只会是半截转义序列，不如重开一屏
    tmTerm.reset();
    tmTerm.write("\r\n（前面那段画面太长，已滚出缓冲；从这里开始是新的）\r\n");
  }
  if (f.d) tmTerm.write(tmB64ToBytes(f.d));
  if (typeof f.exit !== "undefined") { tmDead = true; tmExit(f.exit); }
}

function tmExit(code) {
  tmDetachStream();
  tmLed("failed");
  tmState(code === null || code === undefined ? "进程已结束"
        : "进程已结束（退出码 " + code + "）");
  document.getElementById("tm-close").disabled = true;
  tmLoadSessions();
}

async function tmOpenTerm() {
  const term = tmEnsureTerm();
  tmFit.fit();          // 先按当前画面格数落地，再让 PTY 以同一尺寸出生
  const d = await api("/api/term/open", {
    agent: tmAgent, cwd: document.getElementById("tm-cwd").value.trim(),
    cols: term.cols, rows: term.rows,
  });
  if (!d.ok) {
    return toast(d.error.message + (d.error.hint ? " · " + d.error.hint : ""), false);
  }
  tmSession = null;
  tmOffset = 0;
  tmDead = false;
  tmTerm.reset();
  toast("真终端已就绪：" + d.data.name);
  await tmLoadSessions();
  tmAttach(d.data.id);
  term.focus();
}

async function tmCloseTerm() {
  if (!tmSession) return;
  const d = await api("/api/term/close", {id: tmSession});
  if (!d.ok) return toast(d.error.message, false);
  tmDetachStream();
  tmSession = null;
  tmDead = false;
  tmLed("idle");
  tmState("");
  document.getElementById("tm-close").disabled = true;
  document.getElementById("tm-title").textContent = "还没启动";
  await tmLoadSessions();
}

function tmClear() {
  if (tmTerm) { tmTerm.reset(); tmTerm.focus(); }
}

function tmCopy() {
  const text = tmTerm ? tmTerm.getSelection() : "";
  if (!text) return toast("先选中画面里的内容", false);
  navigator.clipboard.writeText(text).then(
    () => toast("已复制选中内容"),
    () => toast("浏览器不让复制，用键盘选中后再试", false));
}

function tmFillChip(btn) {
  if (!tmSession || tmDead) return toast("先开一个终端", false);
  // 必须走输入通道：term.write() 只是往画面上画字，Agent 那边什么都收不到
  tmInput(new TextEncoder().encode(btn.dataset.t));
  tmTerm.focus();
}

function tmEnterPage() {
  tmEnsureTerm();
  tmLoadAgents();
  tmLoadSessions();
  const quick = document.getElementById("tm-quick");
  if (quick && !quick.childElementCount) {
    quick.innerHTML = TM_QUICK.map(q =>
      '<button class="tm-chip" onclick="tmFillChip(this)" data-t="' +
      esc(q[1]) + '">' + esc(q[0]) + "</button>").join("");
  }
  // 回到这一页要把推流接回来（离开时只是断了观看，终端还在跑）
  if (tmSession && !tmStream && !tmDead) tmConnect();
  tmSyncSize();
}

function tmLeavePage() {
  tmDetachStream();          // 离开这一页只是不看画面，终端里的 Agent 继续跑
}
