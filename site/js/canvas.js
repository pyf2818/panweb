// 首屏隧道网格：出站连接从本机节点流向边缘节点，粒子按访客数复用。
(() => {
  const cv = document.getElementById("mesh");
  if (!cv) return;
  const ctx = cv.getContext("2d");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let W = 0, H = 0, dpr = 1, running = true, frame = 0, seen = false;
  let lanes = [], motes = [], rings = [], c = {};
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };

  function palette() {
    const s = getComputedStyle(document.documentElement);
    const pick = (n, f) => (s.getPropertyValue(n) || f).trim();
    c = { accent: pick("--accent", "#4da08f"), accent2: pick("--accent-2", "#6fcbaf"),
          gold: pick("--gold", "#d3ab6b"), ink: pick("--ink", "#e6ede9"),
          line: pick("--line-strong", "rgba(230,237,233,.2)") };
  }

  function alpha(rgba, a) {
    return rgba.startsWith("#")
      ? "rgba(" + parseInt(rgba.slice(1, 3), 16) + "," + parseInt(rgba.slice(3, 5), 16) +
        "," + parseInt(rgba.slice(5, 7), 16) + "," + a + ")"
      : rgba.replace(/[\d.]+\)$/, a + ")");
  }

  function resize() {
    const r = cv.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(1, Math.round(r.width));
    H = Math.max(1, Math.round(r.height));
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    build();
  }

  // 每条车道是一段三次贝塞尔：本机端口 → 边缘；弯曲度决定视觉层次
  function build() {
    const src = { x: W * 0.16, y: H * 0.72 };
    const edge = { x: W * 0.80, y: H * 0.30 };
    lanes = [];
    const n = 7;
    for (let i = 0; i < n; i++) {
      const k = (i - (n - 1) / 2) / n;
      lanes.push({
        p0: { x: src.x, y: src.y + k * 46 },
        p1: { x: W * 0.38, y: H * (0.30 + k * 0.52) },
        p2: { x: W * 0.56, y: H * (0.16 + k * 0.68) },
        p3: { x: edge.x, y: edge.y + k * 52 },
        wide: 0.5 + Math.abs(k)
      });
    }
    motes = [];
    const count = reduce ? 0 : (W < 700 ? 26 : 54);
    for (let i = 0; i < count; i++) {
      motes.push({
        lane: i % lanes.length, u: Math.random(),
        v: 0.0016 + Math.random() * 0.0032,
        r: 0.7 + Math.random() * 1.9,
        gold: Math.random() < 0.22
      });
    }
    rings = [];
  }

  function at(l, u) {
    const m = 1 - u, a = m * m * m, b = 3 * m * m * u, d = 3 * m * u * u, e = u * u * u;
    return { x: a * l.p0.x + b * l.p1.x + d * l.p2.x + e * l.p3.x,
             y: a * l.p0.y + b * l.p1.y + d * l.p2.y + e * l.p3.y };
  }

  function grid(ox, oy) {
    const step = 62;
    ctx.save();
    ctx.globalAlpha = 0.5;
    ctx.strokeStyle = alpha(c.line, 0.13);
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = ((ox % step) + step) % step; x < W; x += step) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
    for (let y = ((oy % step) + step) % step; y < H; y += step) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
    ctx.stroke();
    ctx.restore();
  }

  function node(x, y, label, color, pulse) {
    ctx.save();
    ctx.translate(x, y);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 58);
    g.addColorStop(0, alpha(color, 0.26));
    g.addColorStop(1, alpha(color, 0));
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(0, 0, 58, 0, 6.2832); ctx.fill();
    ctx.strokeStyle = alpha(color, 0.75); ctx.lineWidth = 1.4;
    ctx.beginPath(); ctx.arc(0, 0, 7, 0, 6.2832); ctx.stroke();
    if (!reduce) {
      const t = (frame % 240) / 240;
      ctx.globalAlpha = 1 - t;
      ctx.beginPath(); ctx.arc(0, 0, 7 + t * pulse, 0, 6.2832); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    if (label) {
      ctx.font = "500 11px " + getComputedStyle(document.body).fontFamily;
      ctx.fillStyle = alpha(c.ink, 0.5);
      ctx.textAlign = "center";
      ctx.fillText(label, 0, 28);
    }
    ctx.restore();
  }

  function draw() {
    frame++;
    const ox = pointer.x * 18, oy = pointer.y * 12;
    ctx.clearRect(0, 0, W, H);
    grid(ox, oy);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";

    ctx.lineWidth = 1;
    for (const l of lanes) {
      ctx.beginPath();
      ctx.moveTo(l.p0.x + ox, l.p0.y + oy);
      ctx.bezierCurveTo(l.p1.x + ox, l.p1.y + oy, l.p2.x + ox, l.p2.y + oy,
                        l.p3.x + ox, l.p3.y + oy);
      ctx.strokeStyle = alpha(c.accent, 0.07 + l.wide * 0.03);
      ctx.stroke();
    }

    for (const m of motes) {
      if (!reduce) m.u += m.v;
      if (m.u > 1) { m.u = 0; m.lane = (m.lane + 1) % lanes.length; m.gold = Math.random() < 0.22; }
      const l = lanes[m.lane], p = at(l, m.u);
      const q = at(l, Math.max(0, m.u - 0.045));
      const col = m.gold ? c.gold : c.accent2;
      ctx.strokeStyle = alpha(col, 0.16);
      ctx.lineWidth = m.r * 0.8;
      ctx.beginPath(); ctx.moveTo(q.x + ox, q.y + oy); ctx.lineTo(p.x + ox, p.y + oy); ctx.stroke();
      ctx.fillStyle = alpha(col, 0.9);
      ctx.beginPath(); ctx.arc(p.x + ox, p.y + oy, m.r, 0, 6.2832); ctx.fill();
    }

    const tail = lanes[Math.floor(lanes.length / 2)];
    ctx.restore();

    const s = tail.p0, e = tail.p3;
    node(s.x + ox, s.y + oy, "127.0.0.1", c.accent2, 34);
    node(e.x + ox, e.y + oy, "Cloudflare 边缘", c.gold, 46);
    if (!reduce) {
      // 边缘出去之后分给三个访客设备：静态位置，靠呼吸透明度表现"有人在看"
      const outs = [[0.90, 0.52], [0.94, 0.12], [0.86, 0.74]];
      outs.forEach((o, i) => {
        const a = 0.28 + 0.22 * Math.sin(frame / 42 + i * 2.1);
        ctx.fillStyle = alpha(c.ink, a);
        ctx.beginPath(); ctx.arc(W * o[0] + ox, H * o[1] + oy, 2.6, 0, 6.2832); ctx.fill();
        ctx.strokeStyle = alpha(c.accent, a * 0.34);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(e.x + ox, e.y + oy);
        ctx.lineTo(W * o[0] + ox, H * o[1] + oy);
        ctx.stroke();
      });
    }
  }

  function tick() {
    if (!running) return;
    pointer.x += (pointer.tx - pointer.x) * 0.05;
    pointer.y += (pointer.ty - pointer.y) * 0.05;
    draw();
    raf = requestAnimationFrame(tick);
  }

  function start() {
    if (running) return;
    running = true;
    tick();
  }
  function stop() {
    running = false;
    cancelAnimationFrame(raf);
  }

  addEventListener("resize", () => { resize(); if (reduce) draw(); }, { passive: true });
  addEventListener("pointermove", (ev) => {
    pointer.tx = (ev.clientX / innerWidth - 0.5) * 2;
    pointer.ty = (ev.clientY / innerHeight - 0.5) * 2;
  }, { passive: true });
  document.addEventListener("panweb-theme", () => { palette(); if (reduce) draw(); });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden || !seen) stop(); else start();
  });

  palette();
  resize();
  draw();
  if (!reduce) {
    new IntersectionObserver((entries) => {
      seen = entries[0].isIntersecting;
      if (seen && !document.hidden) start(); else stop();
    }, { threshold: 0.04 }).observe(cv);
  }
})();
