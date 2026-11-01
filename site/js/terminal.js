// 终端演示：循环播放「发布 → 访客自检 → 上游兼容」三段真实输出。
(() => {
  const body = document.getElementById("term-body");
  if (!body) return;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const SCENES = [
    [
      { cls: "p", pre: "$ ", t: "panweb publish 3000 --share" },
      { cls: "dim", t: "   正在建立隧道（预热池命中）…" },
      { cls: "ok", t: "✅ 已发布：port-3000" },
      { cls: "", t: "   公网网址：https://gulf-maple-sail-bear.trycloudflare.com" },
      { cls: "", t: "   分享页：https://gulf-maple-sail-bear.trycloudflare.com/__panweb/share/9Kd2xQ" },
      { cls: "dim", t: "   正在按访客视角自检…" },
      { cls: "ok", t: "✅ 可访问 · 首页 200，3 个资源全通，WebSocket 握手 101" },
      { cls: "dim", t: "   关掉终端不影响，网址继续可用" }
    ],
    [
      { cls: "p", pre: "$ ", t: "panweb check 我的应用" },
      { cls: "warn", t: "⚠️ 需留意 · 应用要求登录它自己的账号（401）" },
      { cls: "dim", t: "   · 首页返回 401，静态资源正常 → 是应用自己在要账号" },
      { cls: "dim", t: "   · panweb 口令只守公网入口，不等于应用登录" },
      { cls: "p", pre: "$ ", t: "panweb compat 我的应用 --host-mode tunnel" },
      { cls: "ok", t: "   Host 模式改为「公网域名」，正在复验…" },
      { cls: "ok", t: "✅ 可访问 · 访客现在能直接进应用" }
    ],
    [
      { cls: "p", pre: "$ ", t: "panweb pages ./季度报告 --name Q3" },
      { cls: "ok", t: "✅ 已发布：Q3（只读静态服务）" },
      { cls: "", t: "   公网网址：https://reef-film-lime-hawk.trycloudflare.com" },
      { cls: "p", pre: "$ ", t: "panweb publish 3000 --expires 1d" },
      { cls: "ok", t: "✅ 已发布：port-3000 · 一天后自动收回" },
      { cls: "dim", t: "   隐藏文件与指向根外的符号链接不会被提供" }
    ]
  ];

  const wait = (ms) => new Promise((r) => setTimeout(r, reduce ? 0 : ms));

  function line(spec) {
    const el = document.createElement("span");
    el.className = "line " + (spec.cls || "");
    if (spec.pre) el.appendChild(text(spec.pre, "p"));
    body.appendChild(el);
    return el;
  }

  function text(str, cls) {
    const s = document.createElement("i");
    s.style.fontStyle = "normal";
    if (cls) s.className = cls;
    s.textContent = str;
    return s;
  }

  async function type(el, str) {
    if (reduce) { el.appendChild(text(str)); return; }
    for (let i = 0; i < str.length; i++) {
      el.appendChild(text(str[i]));
      // URL 之类长行快一点，标点处略停，读起来像人在敲
      await wait(str[i] === " " ? 26 : /[，。：）、]/.test(str[i]) ? 90 : 15);
      if (i % 6 === 0) body.scrollTop = body.scrollHeight;
    }
  }

  async function scene(specs) {
    for (const spec of specs) {
      const el = line(spec);
      if (spec.cls === "p") await type(el, spec.t);
      else el.appendChild(text(spec.t));
      body.scrollTop = body.scrollHeight;
      await wait(spec.cls === "p" ? 520 : 340);
    }
    await wait(4200);
  }

  async function loop() {
    for (;;) {
      for (const specs of SCENES) await scene(specs);
      body.replaceChildren();
      await wait(320);
    }
  }

  // 只在画面里时播放，离开就停——省 CPU 也避免切回来时看到半截
  let playing = false;
  new IntersectionObserver((entries) => {
    const on = entries[0].isIntersecting && !document.hidden;
    if (on && !playing) { playing = true; loop(); }
    if (!on) playing = false;
  }, { threshold: 0.25 }).observe(document.getElementById("term"));
})();
