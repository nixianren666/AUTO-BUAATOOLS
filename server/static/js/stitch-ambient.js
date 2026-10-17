/* Decorative optics only: no API calls, account state or attendance decisions. */
(() => {
  'use strict';
  const active = new WeakSet();
  window.BuaaStitchAmbient = { start(canvas) {
    if (!canvas || active.has(canvas)) return;
    active.add(canvas);
    const motionControl = document.getElementById('ambientMotionToggle');
    const pointerControl = document.getElementById('ambientPointerToggle');
    const hint = document.getElementById('ambientMotionHint');
    const veil = document.getElementById('glassVeil');
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
    const write = (key, value) => { try { localStorage.setItem(key, value); } catch { /* Optional preference. */ } };
    let motionChoice = read('origin_ambient_motion'), pointerChoice = read('origin_ambient_pointer');
    const enabled = value => value === 'on' || (value !== 'off' && !reduced.matches);
    let ctx, dots, dotCtx, grid, gridCtx, points = [], failed = false, width = 0, height = 0;
    let needsResize = false;
    const hidden = () => document.hidden || window.BUAARenderLifecycle?.visible === false;
    let frame = 0, last = 0, lastFluid = 0, lastDots = 0, time = 0, dotTime = 0, frames = 0, pointer = null;
    let pitch = 16, columns = 0, rows = 0, dpr = 1, dirty = null, gradients = null;
    const moving = new Set(), buckets = Array.from({ length: 32 }, () => []);
    const palette = Array.from({ length: 32 }, (_, i) => {
      const tint = Math.floor(i / 8), alpha = .28 * (1 - (i % 8) / 7 * .55);
      return `rgba(${[137,132,133,150][tint]},${[148,151,175,155][tint]},${[181,203,205,216][tint]},${alpha})`;
    });
    function dotFallback() {
      dots?.remove(); dots = dotCtx = grid = gridCtx = null; points = []; moving.clear(); dirty = null; pointer = null;
      if (veil) delete veil.dataset.dots;
      if (pointerControl) pointerControl.disabled = true;
    }
    function fallback() {
      failed = true; cancelAnimationFrame(frame); frame = 0;
      canvas.width = canvas.width;
      canvas.dataset.renderer = 'css'; canvas.dataset.motion = 'fallback';
      delete canvas.dataset.optics; dotFallback();
      if (motionControl) motionControl.disabled = true;
      if (hint) hint.textContent = '当前使用静态背景，其他功能不受影响';
    }
    try { ctx = canvas.getContext('2d'); } catch { fallback(); return; }
    if (!ctx) { fallback(); return; }
    canvas.dataset.renderer = 'canvas2d';
    canvas.dataset.optics = 'filter' in ctx ? 'canvas-blur' : 'css-blur';
    try {
      if (veil) {
        dots = document.createElement('canvas'); dots.className = 'stitch-dot-plane';
        dots.setAttribute('aria-hidden', 'true'); dotCtx = dots.getContext('2d');
        grid = document.createElement('canvas'); gridCtx = grid.getContext('2d');
        if (dotCtx && gridCtx) { veil.appendChild(dots); veil.dataset.dots = 'canvas'; } else dotFallback();
      }
    } catch { dotFallback(); }
    function paintFluid() {
      if (failed || hidden()) return;
      try {
        const w = width, h = height, k = Math.min(w / 1280, h / 800), phase = time * Math.PI / 12000;
        ctx.clearRect(0, 0, w, h); ctx.fillStyle = '#050508'; ctx.fillRect(0, 0, w, h);
        ctx.fillStyle = gradients.wash; ctx.fillRect(0, 0, w, h);
        // Cross-section, folds and channels evolve with time, never with input.
        const sections = [];
        for (let i = 0; i <= 72; i++) {
          const u = i / 72;
          const sway = Math.sin(phase + u * 3.4), fold = Math.sin(u * 8.2 - phase * 1.3);
          const x = (-.18 + 1.36 * u) * w;
          const y = (.35 + .55 * Math.sin(Math.PI * u) + .12 * sway + .035 * fold) * h;
          const slope = (.55 * Math.PI * Math.cos(Math.PI * u) + .408 * Math.cos(phase + u * 3.4)
            + .287 * Math.cos(u * 8.2 - phase * 1.3)) * h / (1.36 * w);
          const normal = Math.sqrt(1 + slope * slope);
          const thickness = (87 + 29 * Math.sin(u * 5.1 + phase * .8) + 14 * fold) * k;
          sections.push({ x, y, nx: -slope / normal, ny: 1 / normal, thickness,
            twist: .1 * Math.sin(u * 7.4 - phase * .8) });
        }
        const band = (lo, hi, offset, color, blur, alpha) => {
          ctx.save(); ctx.filter = `blur(${blur * k}px)`; ctx.globalAlpha = alpha;
          ctx.fillStyle = color; ctx.beginPath();
          const vertex = (i, edge, first = false) => {
            const s = sections[i], cross = (edge + offset + s.twist * .35) * s.thickness;
            const x = s.x + s.nx * cross, y = s.y + s.ny * cross;
            first ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
          };
          for (let i = 0; i <= 72; i++) vertex(i, lo, i === 0);
          for (let i = 72; i >= 0; i--) vertex(i, hi);
          ctx.closePath(); ctx.fill(); ctx.restore();
        };
        const { spectrum, crest } = gradients;
        band(-1.1, 1.1, 0, spectrum, 36, .68);
        band(-.8, .6, 0, spectrum, 15, .63);
        band(-.61, -.38, .1 * Math.sin(phase * .7), crest, 10, .7);
        // A restrained inner reflection gives the broad glow a readable fold.
        band(-.53, -.49, .1 * Math.sin(phase * .7), crest, 2.5, .42);
        band(.18, .42, .16 * Math.sin(phase + 2), '#363366', 14, .62);
        band(.62, .78, .13 * Math.cos(phase), spectrum, 12, .47);
        ctx.fillStyle = gradients.haze; ctx.fillRect(0, 0, w, h); canvas.dataset.frames = String(++frames);
      } catch { fallback(); }
    }
    function paintDots(dt, reset = false) {
      if (!dotCtx || hidden()) return;
      try {
        if (reset) {
          for (const p of moving) p.dx = p.dy = p.effect = 0;
          moving.clear(); dirty = null;
          dotCtx.clearRect(0, 0, innerWidth, innerHeight); dotCtx.drawImage(grid, 0, 0, grid.width / dpr, grid.height / dpr); return;
        }
        const radius = Math.min(460, Math.max(280, innerWidth * .28)), r2 = radius * radius;
        if (pointer && enabled(pointerChoice)) {
          const left = Math.max(0, Math.floor((pointer.x - radius - 7) / pitch));
          const right = Math.min(columns - 1, Math.ceil((pointer.x + radius - 7) / pitch));
          const top = Math.max(0, Math.floor((pointer.y - radius - 7) / pitch));
          const bottom = Math.min(rows - 1, Math.ceil((pointer.y + radius - 7) / pitch));
          for (let y = top; y <= bottom; y++) for (let x = left; x <= right; x++) {
            const p = points[y * columns + x], dx = p.x - pointer.x, dy = p.y - pointer.y;
            if (dx * dx + dy * dy < r2) moving.add(p);
          }
        }
        // Restore only the previous changed rectangle from a retained grid.
        if (dirty) {
          const { x, y, w, h } = dirty;
          dotCtx.clearRect(x, y, w, h);
          dotCtx.drawImage(grid, x * dpr, y * dpr, w * dpr, h * dpr, x, y, w, h);
        }
        const ease = 1 - Math.exp(-dt / 100), st = Math.sin(dotTime * .00055), ct = Math.cos(dotTime * .00055);
        let minX = innerWidth, minY = innerHeight, maxX = 0, maxY = 0;
        for (const bucket of buckets) bucket.length = 0;
        for (const p of moving) {
          let tx = 0, ty = 0, effect = 0;
          if (pointer && enabled(pointerChoice)) {
            const dx = p.x - pointer.x, dy = p.y - pointer.y, distance2 = dx * dx + dy * dy;
            if (distance2 < r2) {
              const distance = Math.sqrt(distance2), f = 1 - distance / radius;
              effect = f * f;
              const force = 28 * f * f * f;
              tx = (distance > .01 ? dx / distance : p.cx) * force;
              ty = (distance > .01 ? dy / distance : p.sx) * force;
              tx += (p.sx * ct + p.cx * st) * p.cy * 2.2 * effect;
              ty += (p.sy * ct - p.cy * st) * p.cx * 2.2 * effect;
            }
          }
          p.dx += (tx - p.dx) * ease; p.dy += (ty - p.dy) * ease;
          p.effect += (effect - p.effect) * ease;
          if (Math.abs(p.dx) < .02 && Math.abs(p.dy) < .02 && p.effect < .002 && effect < .002) {
            p.dx = p.dy = p.effect = 0; moving.delete(p); continue;
          }
          minX = Math.min(minX, p.x - 34); maxX = Math.max(maxX, p.x + 34);
          minY = Math.min(minY, p.y - 34); maxY = Math.max(maxY, p.y + 34);
          const tint = Math.min(3, Math.floor(p.effect * 3.9));
          const alpha = Math.min(7, Math.floor(p.effect * 7.9));
          buckets[tint * 8 + alpha].push(p);
        }
        dirty = moving.size ? { x: Math.max(0, Math.floor(minX)), y: Math.max(0, Math.floor(minY)),
          w: Math.min(innerWidth, Math.ceil(maxX)) - Math.max(0, Math.floor(minX)),
          h: Math.min(innerHeight, Math.ceil(maxY)) - Math.max(0, Math.floor(minY)) } : null;
        // One opaque mask erases all displaced anchors; one path per palette
        // bucket replaces thousands of single-dot fill calls. No ghost grid.
        dotCtx.save(); dotCtx.globalCompositeOperation = 'destination-out'; dotCtx.fillStyle = '#000'; dotCtx.beginPath();
        for (const p of moving) { dotCtx.moveTo(p.x + 1.6, p.y); dotCtx.arc(p.x, p.y, 1.6, 0, Math.PI * 2); }
        dotCtx.fill(); dotCtx.restore();
        for (let i = 0; i < buckets.length; i++) {
          if (!buckets[i].length) continue;
          dotCtx.fillStyle = palette[i]; dotCtx.beginPath();
          for (const p of buckets[i]) {
            const x = p.x + p.dx, y = p.y + p.dy;
            dotCtx.moveTo(x + .72, y); dotCtx.arc(x, y, .72, 0, Math.PI * 2);
          }
          dotCtx.fill();
        }
        dots.dataset.active = String(moving.size);
      } catch { dotFallback(); }
    }
    function requestFrame() { if (!frame && !failed && !hidden()) frame = requestAnimationFrame(tick); }
    function tick(now) {
      frame = 0; if (failed || hidden()) return;
      const elapsed = last ? now - last : 17; last = now;
      dotTime += Math.min(elapsed, 100);
      if ((pointer || moving.size) && now - lastDots >= 1000 / 60 - .5) {
        const dt = lastDots ? Math.min(now - lastDots, 100) : 17;
        lastDots = now; paintDots(dt);
      }
      if (enabled(motionChoice) && now - lastFluid >= 1000 / 30 - .5) {
        time += lastFluid ? Math.min(now - lastFluid, 100) : 34;
        lastFluid = now; paintFluid();
      }
      if (enabled(motionChoice) || pointer || moving.size) requestFrame();
    }
    function sync() {
      cancelAnimationFrame(frame); frame = 0; last = lastDots = lastFluid = 0; if (failed) return;
      if (hidden()) { canvas.dataset.motion = 'hidden'; return; }
      if (needsResize) resize();
      if (!enabled(pointerChoice) || hidden()) { pointer = null; paintDots(0, true); }
      canvas.dataset.motion = hidden() ? 'hidden' : enabled(motionChoice) ? 'animated' : 'still';
      canvas.dataset.interaction = enabled(pointerChoice) && dotCtx ? 'dot-repulsion' : 'off';
      if (motionControl) { motionControl.disabled = false; motionControl.checked = enabled(motionChoice); }
      if (pointerControl) { pointerControl.disabled = !dotCtx; pointerControl.checked = enabled(pointerChoice) && !!dotCtx; }
      if (hint) hint.textContent = reduced.matches && motionChoice !== 'on' ? '已跟随系统减少动态，可单独开启' : '流光独立流动，鼠标仅排开附近点阵；隐藏时暂停';
      if (!hidden()) { paintFluid(); if (enabled(motionChoice) || pointer || moving.size) requestFrame(); }
    }
    function resize() {
      if (failed) return;
      if (hidden()) { needsResize = true; return; }
      needsResize = false;
      try {
      const scale = Math.min(1, 1280 / innerWidth, 800 / innerHeight);
      width = Math.max(1, Math.round(innerWidth * scale)); height = Math.max(1, Math.round(innerHeight * scale));
      canvas.width = width; canvas.height = height;
      const wash = ctx.createRadialGradient(width * .74, height * .42, 0, width * .74, height * .42, width * .72);
      wash.addColorStop(0, 'rgba(72,59,135,.18)'); wash.addColorStop(1, 'rgba(0,0,0,0)');
      const spectrum = ctx.createLinearGradient(0, height * .4, width, height * .9);
      [[0,'#6553b8'],[.22,'#7774d0'],[.42,'#83cdd5'],[.6,'#6872bf'],[.8,'#7961cc'],[1,'#b0a2e5']].forEach(([s,c]) => spectrum.addColorStop(s,c));
      const crest = ctx.createLinearGradient(0, 0, width, 0);
      [[0,'rgba(140,126,234,.12)'],[.3,'rgba(159,229,234,.8)'],[.55,'rgba(129,177,232,.6)'],[1,'rgba(189,154,240,.2)']].forEach(([s,c]) => crest.addColorStop(s,c));
      const haze = ctx.createRadialGradient(width * .3, height * 1.15, 0, width * .3, height * 1.15, width * .65);
      haze.addColorStop(0, 'rgba(67,42,116,.38)'); haze.addColorStop(1, 'rgba(0,0,0,0)');
      gradients = { wash, spectrum, crest, haze };
      if (dotCtx) {
        try {
        // Crisp dots stay separate from the low-resolution blurred fluid.
        dpr = Math.min(devicePixelRatio || 1, 1.5, 2560 / innerWidth, 1600 / innerHeight);
        dots.width = Math.max(1, Math.round(innerWidth * dpr)); dots.height = Math.max(1, Math.round(innerHeight * dpr));
        grid.width = dots.width; grid.height = dots.height;
        dotCtx.setTransform(dpr, 0, 0, dpr, 0, 0); gridCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        points = []; moving.clear(); pitch = Math.max(16, Math.sqrt(innerWidth * innerHeight / 14000));
        columns = Math.ceil((innerWidth - 7) / pitch); rows = Math.ceil((innerHeight - 7) / pitch);
        gridCtx.fillStyle = palette[0]; gridCtx.beginPath();
        for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
          const x = 7 + col * pitch, y = 7 + row * pitch;
          points.push({ x, y, dx: 0, dy: 0, effect: 0, sx: Math.sin(x * .026), cx: Math.cos(x * .026), sy: Math.sin(y * .019), cy: Math.cos(y * .019) });
          gridCtx.moveTo(x + .72, y); gridCtx.arc(x, y, .72, 0, Math.PI * 2);
        }
        gridCtx.fill();
        paintDots(0, true);
        } catch { dotFallback(); }
      }
      if (!hidden()) paintFluid();
      } catch { fallback(); }
    }
    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('pointermove', e => {
      if (!dotCtx || !enabled(pointerChoice) || e.pointerType === 'touch' || hidden()) return;
      pointer = { x: e.clientX, y: e.clientY }; requestFrame();
    }, { passive: true });
    const release = () => { pointer = null; if (dotCtx) requestFrame(); };
    document.documentElement.addEventListener('pointerleave', release); window.addEventListener('blur', release);
    document.addEventListener('visibilitychange', sync); window.addEventListener('buaa:renderstate', sync); reduced.addEventListener('change', sync);
    motionControl?.addEventListener('change', () => { motionChoice = motionControl.checked ? 'on' : 'off'; write('origin_ambient_motion', motionChoice); sync(); });
    pointerControl?.addEventListener('change', () => { pointerChoice = pointerControl.checked ? 'on' : 'off'; write('origin_ambient_pointer', pointerChoice); sync(); });
    resize(); sync();
  }};
})();
