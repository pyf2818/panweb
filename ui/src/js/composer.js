// ---------- 中栏：快捷模板 / 语法提示（复用后端解析）/ ↑↓ 历史（仅内存） ----------
const CMD_HISTORY = [];
let cmdHistPos = 0;
let cmdHistDraft = "";
let hintTimer = null;
let hintSeq = 0;

// 历史里绝不保留口令：pin=xxx / pin xxx 整段剥离后再入栈。
function stripPin(text) {
  return String(text || "")
    .replace(/(pin)(\s*=\s*|\s+)(?:"[^"]*"|'[^']*'|\S+)/gi, "")
    .replace(/\s+/g, " ").trim();
}

function rememberCommand(text) {
  const clean = stripPin(text);
  if (!clean) return;
  if (CMD_HISTORY[CMD_HISTORY.length - 1] !== clean) CMD_HISTORY.push(clean);
  while (CMD_HISTORY.length > 30) CMD_HISTORY.shift();
  cmdHistPos = CMD_HISTORY.length;
  cmdHistDraft = "";
}

function recallCommand(delta) {
  if (!CMD_HISTORY.length) return;
  const input = document.getElementById("cmd-input");
  if (cmdHistPos === CMD_HISTORY.length) cmdHistDraft = input.value;
  const next = Math.max(0, Math.min(CMD_HISTORY.length, cmdHistPos + delta));
  if (next === cmdHistPos) return;
  cmdHistPos = next;
  input.value = cmdHistPos === CMD_HISTORY.length
    ? cmdHistDraft : CMD_HISTORY[cmdHistPos];
  const end = input.value.length;
  input.setSelectionRange(end, end);
  autoGrowCommand();
  updateCmdHint(input.value);
}

function fillTemplate(text, token) {
  const input = document.getElementById("cmd-input");
  input.value = text;
  input.focus();
  if (token) {
    const at = text.indexOf(token);
    if (at >= 0) input.setSelectionRange(at, at + token.length);
  }
  autoGrowCommand();
  updateCmdHint(text);
}

function setCmdHint(text, kind) {
  const line = document.getElementById("cmd-hint-line");
  if (!line) return;
  line.textContent = text || "";
  line.className = "cmd-hint-line" + (kind ? " " + kind : "");
}

function updateCmdHint(value) {
  clearTimeout(hintTimer);
  const input = document.getElementById("cmd-input");
  const text = String(value == null ? input.value : value).trim();
  if (!text) {
    hintSeq += 1;
    setCmdHint("");
    return;
  }
  // 快捷模板里的占位符不是真实指令，先提示替换，别让后端的转义错误误导人。
  if (/<[^>]+>/.test(text)) {
    hintSeq += 1;
    setCmdHint("把占位符换成实际值再回车，例如：发布 3000", "");
    return;
  }
  hintTimer = setTimeout(() => checkCmdSyntax(text), 400);
}

async function checkCmdSyntax(text) {
  const seq = ++hintSeq;
  const d = await api("/api/command", {text: text});
  if (seq !== hintSeq) return;
  if (document.getElementById("cmd-input").value.trim() !== text) return;
  if (!d.ok) {
    const err = d.error || {};
    return setCmdHint(err.hint || err.message || "语法还不完整", "warn");
  }
  const data = d.data || {};
  const action = {publish: "发布端口", pages: "发布文件夹", run: "启动项目",
    stop: "停止", check: "自检", help: "帮助"}[data.action] || "指令";
  setCmdHint("语法可执行 · " + action, "ok");
}

function initComposer() {
  const input = document.getElementById("cmd-input");
  if (!input) return;
  input.addEventListener("input", () => updateCmdHint(input.value));
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      recallCommand(-1);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      recallCommand(1);
    }
  });
  input.addEventListener("blur", () => setCmdHint(""));
}

initComposer();
