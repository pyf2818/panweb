// 滚动揭示、数字滚动、进度条与章节高亮。全部用 IntersectionObserver，不监听 scroll 做逐帧计算。
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // 同批元素错开入场：给每个观察者目标算一个组内序号
  document.querySelectorAll("main section").forEach((sec) => {
    sec.querySelectorAll(".reveal").forEach((el, i) => {
      el.style.setProperty("--i", Math.min(i, 9));
    });
  });

  const revealIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      e.target.classList.add("in");
      revealIO.unobserve(e.target);
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });
  document.querySelectorAll(".reveal, .flow, .ticker, .cards, .guard").forEach((el) => revealIO.observe(el));

  // 数字滚动：0 与定值都要走完动画，但 "0 台服务器" 只需要落在 0
  function roll(el) {
    const to = parseFloat(el.dataset.count) || 0;
    if (reduce || to === 0) { el.textContent = String(to); return; }
    const dur = 1100, t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      el.textContent = String(Math.round(to * eased));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  const countIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      roll(e.target);
      countIO.unobserve(e.target);
    });
  }, { threshold: 0.5 });
  document.querySelectorAll("[data-count]").forEach((el) => countIO.observe(el));

  // 进度条只在真正滚动时改一次 transform，用 rAF 合并
  const bar = document.querySelector(".progress i");
  const nav = document.querySelector(".nav");
  let queued = false;
  function paint() {
    queued = false;
    const max = document.documentElement.scrollHeight - innerHeight;
    const y = scrollY;
    const k = max > 0 ? Math.min(1, y / max) : 0;
    if (bar) bar.style.transform = "scaleX(" + k + ")";
    if (nav) nav.classList.toggle("stuck", y > 24);
  }
  addEventListener("scroll", () => {
    if (!queued) { queued = true; requestAnimationFrame(paint); }
  }, { passive: true });
  paint();

  // 章节高亮：以视口中线为准，谁跨过中线谁点亮
  const links = [...document.querySelectorAll(".links a")];
  const spyIO = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (!e.isIntersecting) return;
      links.forEach((a) => a.classList.toggle("active",
        a.getAttribute("href") === "#" + e.target.id));
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  links.forEach((a) => {
    const sec = document.querySelector(a.getAttribute("href"));
    if (sec) spyIO.observe(sec);
  });
})();
