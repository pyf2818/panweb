// ---------- 氛围层：隧道流线 ----------
// 粒子走的是 panweb 自己的链路形状：本机（左下）→ Cloudflare 边缘（右上），
// 在线应用越多，流得越密；发布/访客事件从本机节点放一圈脉冲。
// 常驻但克制：帧率封顶 30fps、终端页与隐藏标签停笔、reduced-motion 只画一帧静图。
const fx = (() => {
  const cv = document.getElementById("fx");
  const noop = {sync() {}, page() {}};
  if (!cv || !cv.getContext) return noop;
  const ctx = cv.getContext("2d");
  const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const FRAME = 1000 / 30;      // 帧率上限：氛围不该抢 CPU
  const TAIL = 0.055;           // 拖尾长度（按曲线参数算，不是像素）

  let W = 0, H = 0, lanes = [], motes = [], rings = [];
  let flow = "51,121,107", spark = "185,151,91";
  let load = 0.3, want = 0.3, fade = 0, target = 1;
  let raf = 0, last = 0, acc = 0, onTerm = false, key = "";

  function rgb(name, fallback) {
    const v = (getComputedStyle(document.documentElement).getPropertyValue(name) || "").trim();
    if (v[0] === "#") {
      return [parseInt(v.slice(1, 3), 16), parseInt(v.slice(3, 5), 16),
              parseInt(v.slice(5, 7), 16)].join(",");
    }
    const m = v.match(/(\d+)[^\d]+(\d+)[^\d]+(\d+)/);
    return m ? [m[1], m[2], m[3]].join(",") : fallback;
  }

  function palette() {
    flow = rgb("--accent", "51,121,107");
    spark = rgb("--gold", "185,151,91");
  }

  // 一条泳道 = 三次贝塞尔 + 中间外扩的偏移，两端收拢到节点上，看起来才像"隧道"
  function laneOf(i, n) {
    const spread = Math.min(84, H * 0.075) * (i - (n - 1) / 2);
    return {
      x0: -W * 0.03, y0: H * (0.97 + i * 0.004),
      x1: W * 0.26, y1: H * 0.80,
      x2: W * 0.66, y2: H * 0.30,
      x3: W * 1.03, y3: H * (0.03 - i * 0.004),
      spread: spread
    };
  }

  function point(l, t) {
    const u = 1 - t, a = u * u * u, b = 3 * u * u * t, c = 3 * u * t * t, d = t * t * t;
    return [a * l.x0 + b * l.x1 + c * l.x2 + d * l.x3,
            a * l.y0 + b * l.y1 + c * l.y2 + d * l.y3 + l.spread * Math.sin(Math.PI * t)];
  }

  function seed() {
    const n = 4;
    lanes = [];
    for (let i = 0; i < n; i++) lanes.push(laneOf(i, n));
    motes = [];
    resizeMoties();
  }

  function resizeMoties() {
    const n = Math.max(14, Math.min(44,
      Math.round(W * H / 26000 * (0.55 + 0.45 * load))));
    while (motes.length < n) {
      motes.push({l: (Math.random() * lanes.length) | 0, t: Math.random(),
                  v: 0.045 + Math.random() * 0.075,
                  r: 0.7 + Math.random() * 1.5,
                  s: Math.random() < 0.16});
    }
    if (motes.length > n + 3) motes.length = n;
  }

  function layout() {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.6);
    W = cv.clientWidth || window.innerWidth;
    H = cv.clientHeight || window.innerHeight;
    cv.width = Math.max(1, Math.round(W * dpr));
    cv.height = Math.max(1, Math.round(H * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    palette();
    seed();
  }

  function node(x, y, r, color, a) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, "rgba(" + color + "," + (a * 0.9) + ")");
    g.addColorStop(1, "rgba(" + color + ",0)");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fill();
  }

  function draw(dt) {
    const k = fade;
    if (k <= 0.008) return false;         // 已经完全淡出：这一帧不用画
    ctx.clearRect(0, 0, W, H);
    const bright = 0.45 + 0.55 * load;
    ctx.lineCap = "round";
    // 泳道本身画得极淡，只给"方向"打底
    ctx.lineWidth = 1;
    lanes.forEach(l => {
      ctx.strokeStyle = "rgba(" + flow + "," + (0.05 * k * bright) + ")";
      ctx.beginPath();
      ctx.moveTo(l.x0, l.y0);
      ctx.bezierCurveTo(l.x1, l.y1, l.x2, l.y2, l.x3, l.y3);
      ctx.stroke();
    });
    motes.forEach(m => {
      m.t += m.v * dt * (0.75 + 0.5 * load);
      if (m.t > 1) {
        m.t -= 1;
        m.l = (Math.random() * lanes.length) | 0;
        m.v = 0.045 + Math.random() * 0.075;
        m.s = Math.random() < 0.16;
      }
      const l = lanes[m.l], a = Math.sin(Math.PI * Math.min(1, Math.max(0, m.t)));
      const p = point(l, m.t), q = point(l, Math.max(0, m.t - TAIL));
      const c = m.s ? spark : flow, al = a * k * bright;
      ctx.strokeStyle = "rgba(" + c + "," + (al * 0.5) + ")";
      ctx.lineWidth = m.r * 0.9;
      ctx.beginPath();
      ctx.moveTo(q[0], q[1]);
      ctx.lineTo(p[0], p[1]);
      ctx.stroke();
      ctx.fillStyle = "rgba(" + c + "," + (al * (m.s ? 0.85 : 0.6)) + ")";
      ctx.beginPath();
      ctx.arc(p[0], p[1], m.r * (m.s ? 1.25 : 1), 0, Math.PI * 2);
      ctx.fill();
    });
    for (let i = rings.length - 1; i >= 0; i--) {
      const r = rings[i];
      r.t += dt * 0.55;
      if (r.t >= 1) { rings.splice(i, 1); continue; }
      const rr = 18 + r.t * Math.max(W, H) * 0.22;
      ctx.strokeStyle = "rgba(" + r.c + "," + ((1 - r.t) * 0.28 * k) + ")";
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.arc(-W * 0.03, H * 0.97, rr, 0, Math.PI * 2);
      ctx.stroke();
    }
    node(-W * 0.03, H * 0.97, Math.min(300, W * 0.22), flow, 0.10 * k * bright);
    node(W * 1.03, H * 0.03, Math.min(260, W * 0.2), spark, 0.07 * k);
    return rings.length > 0;
  }

  function step(dt) {
    target = onTerm ? 0 : 1;
    fade += (target - fade) * Math.min(1, dt * 1.8);
    const alive = draw(dt);
    if (!alive && fade <= 0.008) { ctx.clearRect(0, 0, W, H); stop(); }
  }

  function loop(ts) {
    raf = requestAnimationFrame(loop);
    if (!last) last = ts;
    acc += ts - last;
    last = ts;
    if (acc < FRAME) return;              // 未到下一帧：把时间留给代理与终端
    const dt = Math.min(0.25, acc / 1000);
    acc = 0;
    step(dt);
  }

  function start() {
    if (raf || REDUCE) return;
    last = 0;
    acc = 0;
    raf = requestAnimationFrame(loop);
  }

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  }

  function still() {
    fade = 1;
    draw(0);
  }

  layout();
  if (REDUCE) {
    still();                             // 一张静态构图，不跑动画
  } else {
    start();
  }

  let rt = 0;
  addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => {
      layout();
      if (REDUCE) still();
      else if (!raf) start();
    }, 260);
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !REDUCE) start();   // 回到前台：last 归零，别把隐藏的整段时间当成一帧
  });
  new MutationObserver(palette).observe(document.documentElement,
                                        {attributes: true, attributeFilter: ["data-theme"]});

  return {
    // 控制台每轮回调一次：在线数决定密度，新动态放脉冲
    sync(state) {
      const apps = (state && state.apps) || [];
      const online = apps.filter(a => a.alive).length;
      want = Math.min(1, 0.16 + online * 0.16);
      load += (want - load) * 0.4;
      resizeMoties();
      if (REDUCE) { still(); return; }
      const top = ((state && state.activity) || [])[0];
      const k = top ? [top.ts, top.kind, top.text].join("|") : "";
      if (key && k && k !== key) {
        rings.push({t: 0, c: /发布|托管|恢复/.test(top.text || "") ? spark : flow});
        if (rings.length > 4) rings.shift();
      }
      key = k;
    },
    page(name) {
      onTerm = name === "term";
      if (REDUCE) { still(); return; }
      start();                     // 淡出也交给循环走完，别在这里单帧跳变
    },
    pulse() {
      rings.push({t: 0, c: spark});
      if (rings.length > 4) rings.shift();
      if (REDUCE) still();
      else start();
    }
  };
})();
