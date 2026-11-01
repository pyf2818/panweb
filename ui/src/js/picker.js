// ---------- 文件夹选择器：浏览器拿不到绝对路径，所以由本机这一侧列目录 ----------
let fkTarget = null;      // 要回填的输入框 id
let fkPath = "";          // 当前浏览到的目录
let fkParent = "";        // 上一层（由后端给出，不自己截字符串）

async function fkLoad(path) {
  const list = document.getElementById("fk-list");
  list.innerHTML = '<div class="feed-empty">读取中…</div>';
  const d = await api("/api/folders?path=" + encodeURIComponent(path || ""));
  if (!d.ok) {
    list.innerHTML = '<div class="feed-empty">' + esc(d.error.message) + '</div>';
    const hint = document.getElementById("fk-hint");
    hint.textContent = d.error.hint || "";
    return;
  }
  const r = d.data;
  fkPath = r.path;
  fkParent = r.parent || "";
  document.getElementById("fk-path").textContent = r.path;
  document.getElementById("fk-up").disabled = !r.parent;
  document.getElementById("fk-quick").innerHTML = (r.quick || []).map(q =>
    '<button class="fk-chip" onclick="fkGo(\'' + esc(q.path) + '\')">' +
    esc(q.label) + '</button>').join("");
  if (!r.entries.length) {
    list.innerHTML = '<div class="feed-empty">这里没有子文件夹 · 可以直接「选这里」</div>';
  } else {
    list.innerHTML = r.entries.map(e =>
      '<button class="fk-row" onclick="fkGo(\'' + esc(e.path) + '\')" title="' +
      esc(e.path) + '"><span class="fk-ic">▸</span>' + esc(e.name) + '</button>').join("") +
      (r.truncated ? '<div class="feed-empty">还有 ' + r.truncated + ' 个没显示，先往下层找</div>' : "");
  }
  const hint = document.getElementById("fk-hint");
  hint.className = "fk-hint" + (r.publishable.ok ? " ok" : " bad");
  hint.textContent = r.publishable.ok
    ? "这个目录可以直接发布成只读网页"
    : "这个目录不适合直接发布：" + r.publishable.reason;
}

function fkGo(path) { fkLoad(path); }
function fkGoUp() { if (fkParent) fkLoad(fkParent); }

function openFolderPicker(inputId) {
  fkTarget = inputId;
  const current = (document.getElementById(inputId).value || "").trim();
  document.getElementById("folder-overlay").classList.add("show");
  fkLoad(current);
}

function fkClose() { document.getElementById("folder-overlay").classList.remove("show"); }

function fkChoose() {
  if (!fkTarget || !fkPath) return toast("先翻到一个目录", false);
  const box = document.getElementById(fkTarget);
  box.value = fkPath;
  fkClose();
  toast("已选中目录");
  // 启动项目那栏选中后顺手识别一次，省一次点击
  if (fkTarget === "in-project" && typeof detectProject === "function") detectProject();
  box.dispatchEvent(new Event("change", {bubbles: true}));
}
