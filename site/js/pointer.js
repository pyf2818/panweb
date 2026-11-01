// 指针交互：卡片光斑与倾斜、磁吸按钮、复制、主题、发布模式切换、自检结论演示。
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 主题 ---------- */
  const KEY = "panweb-site-theme";
  const html = document.documentElement;
  const stored = localStorage.getItem(KEY);
  const sysDark = matchMedia("(prefers-color-scheme: dark)").matches;
  const apply = (mode) => {
    html.dataset.theme = mode;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = mode === "light" ? "#f6f5f0" : "#141a18";
    document.dispatchEvent(new CustomEvent("panweb-theme"));
  };
  apply(stored || (sysDark ? "dark" : "dark"));   // 品牌暗色优先，浅色仍可手动切
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    if (!localStorage.getItem(KEY)) apply(e.matches ? "dark" : "light");
  });
  document.getElementById("theme").addEventListener("click", () => {
    const next = html.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(KEY, next);
    apply(next);
  });

  /* ---------- 复制 ---------- */
  const toast = document.getElementById("toast");
  let toastTimer = 0;
  function say(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1900);
  }
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const value = btn.dataset.copy;
      try {
        await navigator.clipboard.writeText(value);
      } catch (err) {
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        ta.remove();
      }
      btn.classList.add("done");
      btn.textContent = "已复制";
      setTimeout(() => { btn.classList.remove("done"); btn.textContent = "复制"; }, 1400);
      say("已复制到剪贴板");
    });
  });

  /* ---------- 卡片光斑 + 倾斜 ---------- */
  const raf = new Set();
  document.querySelectorAll("[data-tilt]").forEach((card) => {
    card.addEventListener("pointermove", (ev) => {
      const r = card.getBoundingClientRect();
      const x = (ev.clientX - r.left) / r.width, y = (ev.clientY - r.top) / r.height;
      card.style.setProperty("--mx", (x * 100).toFixed(1) + "%");
      card.style.setProperty("--my", (y * 100).toFixed(1) + "%");
      if (reduce || !raf.size) {
        if (reduce) return;
      }
      if (raf.has(card)) return;
      raf.add(card);
      requestAnimationFrame(() => {
        raf.delete(card);
        card.style.transform =
          "perspective(900px) rotateY(" + ((x - .5) * 7).toFixed(2) + "deg)" +
          " rotateX(" + ((.5 - y) * 6).toFixed(2) + "deg) translateY(-3px)";
      });
    });
    card.addEventListener("pointerleave", () => { card.style.transform = ""; });
  });

  /* ---------- 磁吸按钮 ---------- */
  document.querySelectorAll(".magnetic").forEach((el) => {
    if (reduce) return;
    el.addEventListener("pointermove", (ev) => {
      const r = el.getBoundingClientRect();
      el.style.transform = "translate(" + ((ev.clientX - r.left - r.width / 2) * .16).toFixed(1) +
        "px," + ((ev.clientY - r.top - r.height / 2) * .22).toFixed(1) + "px)";
    });
    el.addEventListener("pointerleave", () => { el.style.transform = ""; });
  });

  /* ---------- 发布模式切换 ---------- */
  const MODES = {
    publish: "发布端口：<b>panweb publish 3000</b>。隧道直接指向本机 3000，零开销；"
      + "加 <b>--share</b> 就改走内置代理，同时拿到分享页与访问统计。",
    pages: "发布文件夹：<b>panweb pages ./dist</b>。panweb 起一个只读静态服务并建隧道，"
      + "隐藏文件、指向根外的符号链接、系统根目录都会被拒绝；无扩展名深链接回退 index.html，SPA 也能跑。",
    run: "自动启动项目：<b>panweb run ./my-app</b>。识别静态站点直接发布，"
      + "Node 项目自动 npm run dev 并从日志里嗅探监听端口，一条命令直达公网；停止时项目进程一并回收。"
  };
  const tabs = document.getElementById("modes");
  if (tabs) {
    const ind = tabs.querySelector(".tab-ind");
    const out = document.getElementById("mode-body");
    const btns = [...tabs.querySelectorAll("button")];
    function move(btn) {
      ind.style.width = btn.offsetWidth + "px";
      ind.style.transform = "translateX(" + (btn.offsetLeft - 4) + "px)";
    }
    function select(btn) {
      btns.forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
      move(btn);
      out.style.opacity = "0";
      out.innerHTML = MODES[btn.dataset.mode];
      requestAnimationFrame(() => { out.style.transition = "opacity .4s"; out.style.opacity = "1"; });
      say(btn.textContent.trim());
    }
    btns.forEach((b) => b.addEventListener("click", () => select(b)));
    out.innerHTML = MODES.publish;
    const first = btns[0];
    requestAnimationFrame(() => move(first));
    addEventListener("resize", () => {
      const on = btns.find((b) => b.getAttribute("aria-selected") === "true");
      if (on) move(on);
    }, { passive: true });
  }

  /* ---------- 自检结论演示：三种结论轮播 ---------- */
  const verdict = document.getElementById("verdict");
  if (verdict) {
    const CASES = [
      { v: "ok", chip: "✓ 可访问", sigs: ["首页 200，引用的 3 个资源全通", "WebSocket 握手 101，实时功能可用"] },
      { v: "warn", chip: "△ 需留意", sigs: ["应用要求登录它自己的账号（401）", "panweb 口令只守公网入口", "可用 compat 替访客注入 Bearer 令牌"] },
      { v: "bad", chip: "✕ 打不开", sigs: ["首页 404：端口上没有这个路径", "页面引用了 .tsx 源码 — 浏览器看不懂", "🔧 已取证：本机 Host 能过、公网域名被拒 → 切 tunnel"] }
    ];
    const pill = verdict.querySelector(".pill");
    const list = verdict.querySelector(".sigs");
    let k = 0;
    function show() {
      const c = CASES[k % CASES.length];
      pill.className = "pill " + c.v;
      pill.textContent = c.chip;
      list.replaceChildren();
      c.sigs.forEach((s, i) => {
        const li = document.createElement("li");
        li.textContent = s;
        list.appendChild(li);
        setTimeout(() => li.classList.add("in"), reduce ? 0 : 90 * i + 60);
      });
      k++;
    }
    show();
    if (!reduce) setInterval(show, 4600);
  }
})();
