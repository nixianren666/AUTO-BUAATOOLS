/* Startup presentation only. School requests, initialization and schedulers run unchanged. */
(() => {
  'use strict';
  const renderHidden = () => document.hidden || window.BUAARenderLifecycle?.visible === false;
  const boot = window.BUAAStartupBoot;
  const stage = document.getElementById('startupStage');
  if (!boot && document.documentElement.dataset.startupEnabled === 'false') { stage?.remove(); return; }
  if (!boot || !stage || !document.documentElement.classList.contains('startup-running')) return;
  if(typeof requestAnimationFrame!=='function'||typeof cancelAnimationFrame!=='function'){boot.release('unsupported-animation');return;}
  const emblem = document.getElementById('startupEmblemFlight');
  const name = document.getElementById('startupSchoolName');
  const notice = document.getElementById('startupStudyNotice');
  const veil = document.getElementById('startupBlackout');
  const canvas = document.getElementById('startupScatter');
  const workspace = document.querySelector('.origin-app-layout');
  const layers = [workspace, document.getElementById('ambientParticlesCanvas'), document.getElementById('glassVeil')].filter(Boolean);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = value => Math.max(0, Math.min(1, value));
  const ease = t => t < .5 ? 4*t*t*t : 1-Math.pow(-2*t+2,3)/2;
  const originalFocus = document.activeElement;
  const wasInert = workspace?.inert;
  const previousFilters = layers.map(el => el.style.filter);
  const icon = document.querySelector('.origin-logo-mark');
  const previousVisibility = icon?.style.visibility || '';
  let frame = 0, readyFrame = 0, timer = 0, afterPaint, cycle = performance.now(), flightStart = 0, hiddenAt = 0;
  let phase = 'drawing', ready = false, fading = false, closed = false, context = null, pixels = [], particles = [];
  const motion = {emblem:2500, name:1800, hold:380, reset:240, flight:1300, burst:440};
  const cycleEnd = motion.emblem + motion.name + motion.hold;
  const cycleLength = cycleEnd + motion.reset;
  let emblemPaths, letterPaths;

  function target() {
    const rect = icon?.getBoundingClientRect();
    if (!rect || !rect.width || !rect.height) return null;
    return {x:rect.x+rect.width/2, y:rect.y+rect.height/2, size:Math.min(rect.width,rect.height)};
  }
  function cleanup(reason) {
    if (closed) return;
    closed = true; cancelAnimationFrame(frame); cancelAnimationFrame(readyFrame); clearTimeout(timer);
    removeEventListener('resize', resize); document.removeEventListener('DOMContentLoaded', afterPaint);
    document.removeEventListener('visibilitychange', visibility);removeEventListener('buaa:renderstate',visibility);
    document.removeEventListener('keydown', guardKeys, true);
    if(reduced.removeEventListener)reduced.removeEventListener('change',preferenceChanged);
    else reduced.removeListener?.(preferenceChanged);
    layers.forEach((el,i) => { el.style.filter = previousFilters[i]; });
    if (workspace) workspace.inert = wasInert;
    if (icon) icon.style.visibility = previousVisibility;
    stage.remove();
    boot.release(reason);
    // Restore presentation focus, without triggering or submitting any control.
    const modal = document.querySelector('.origin-modal-backdrop:not(.hidden)');
    const focus = modal?.querySelector('button:not(:disabled),input:not(:disabled)') || originalFocus;
    if (focus instanceof HTMLElement && focus !== document.body && !focus.closest('[inert]')) focus.focus({preventScroll:true});
  }
  function guardKeys(event) {
    if (!event.ctrlKey && !event.altKey && !event.metaKey && ['Tab','Enter','Escape',' ','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key)) {
      event.preventDefault();event.stopImmediatePropagation();
    }
  }
  function paths(svgId, sequential) {
    const list = [...document.getElementById(svgId).querySelectorAll('path')].map(p => {
      p.setAttribute('pathLength','1000');const box=p.getBBox();return {p,x:box.x+box.width/2};
    });
    if (sequential) list.sort((a,b)=>a.x-b.x);
    return list;
  }
  function draw(list, elapsed, total, sequential) {
    for (let i=0;i<list.length;i++) {
      const offset=i/Math.max(1,list.length)*total*(sequential?.76:.47);
      const v=clamp((elapsed-offset)/(total*(sequential?.24:.53)));
      if(list[i].last===v)continue;
      list[i].last=v;const p=list[i].p;
      p.style.strokeDashoffset=String(1000*(1-v));
      p.style.fillOpacity=String(clamp((v-.68)/.32));
      p.style.strokeOpacity=String(1-clamp((v-.85)/.15)*.7);
    }
  }
  function resize() {
    if (!context || renderHidden()) return;
    const dpr=Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(innerWidth*dpr);canvas.height=Math.round(innerHeight*dpr);
    context.setTransform(dpr,0,0,dpr,0,0);
  }
  function preparePixels() {
    // Scatter actual emblem pixels, rather than an unrelated circular particle effect.
    const sample=document.getElementById('startupEmblem').cloneNode(true);
    sample.setAttribute('xmlns','http://www.w3.org/2000/svg');sample.setAttribute('width','96');sample.setAttribute('height','96');
    for (const p of sample.querySelectorAll('path')) {p.removeAttribute('style');p.setAttribute('fill','#eef5ff');p.setAttribute('stroke','none');}
    const image=new Image();
    image.onload=()=>{
      if(closed)return;
      try {const c=document.createElement('canvas');c.width=c.height=96;const x=c.getContext('2d');x.drawImage(image,0,0,96,96);const a=x.getImageData(0,0,96,96).data;
        for(let y=0;y<96;y+=4)for(let v=0;v<96;v+=4)if(a[(y*96+v)*4+3]>90)pixels.push({x:(v-48)/96,y:(y-48)/96});
      } catch { /* Missing particle sampling must never block startup. */ }
    };
    image.src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(sample));
  }
  function onReady() {
    if(closed)return;
    ready=true;stage.dataset.ready='true';
    // A late successful load gets a whole remaining round plus travel. The early
    // no-load watchdog must not cut off a valid final drawing at its old deadline.
    clearTimeout(boot.timer);clearTimeout(timer);
    timer=setTimeout(()=>cleanup('completion-watchdog'),cycleLength+motion.flight+motion.burst+2000);
  }
  function preferenceChanged() {if(reduced.matches&&ready)cleanup('reduced-motion');}
  function visibility() {
    if(renderHidden()){if(!hiddenAt)hiddenAt=performance.now();cancelAnimationFrame(frame);cancelAnimationFrame(readyFrame);frame=readyFrame=0;}
    else if(!closed){
      const gap=hiddenAt?performance.now()-hiddenAt:0;cycle+=gap;flightStart+=gap;hiddenAt=0;
      // A minimized/autostart window must not preserve a stale blocking splash.
      if(ready){cleanup('restored-ready');return;}
      resize();
      frame=requestAnimationFrame(tick);
    }
  }
  function beginFlight(now) {
    draw(emblemPaths,motion.emblem,motion.emblem,false);draw(letterPaths,motion.name,motion.name,true);
    if (!target()) {cleanup('missing-target');return;}
    emblem.style.opacity=name.style.opacity='1';
    phase='flying';flightStart=now;stage.dataset.phase=phase;
  }
  function burst(now) {
    const t=target();if(!t){cleanup('missing-target');return;}
    phase='burst';flightStart=now;stage.dataset.phase=phase;
    particles=pixels.map((q,i)=>{const a=Math.atan2(q.y,q.x);return {x:t.x+q.x*t.size,y:t.y+q.y*t.size,vx:Math.cos(a)*(13+i%7*4),vy:Math.sin(a)*(13+i%5*5),r:.65+i%3*.3};});
    emblem.style.opacity='0';name.style.opacity='0';veil.style.opacity='0';
    if(notice)notice.style.opacity='0';
    layers.forEach((el,i)=>{el.style.filter=previousFilters[i];});
    if(icon)icon.style.visibility=previousVisibility;
  }
  function tick(now) {
    if(closed||renderHidden())return;
    try {
      if (reduced.matches && ready) {cleanup('reduced-motion');return;}
      if(phase==='drawing') {
        let t=now-cycle;
        if(t>=cycleEnd&&ready&&!fading)beginFlight(now);
        else {
          if(t>=cycleLength){cycle=now;t=0;fading=false;stage.dataset.cycles=String(1+Number(stage.dataset.cycles||0));}
          if(t>=cycleEnd)fading=true;
          stage.dataset.phase=fading?'resetting':'drawing';
          emblem.style.opacity=name.style.opacity=String(1-clamp((t-cycleEnd)/motion.reset));
          draw(emblemPaths,t,motion.emblem,false);draw(letterPaths,t-motion.emblem,motion.name,true);
        }
      }
      if(phase==='flying'&&!closed) {
        const raw=clamp((now-flightStart)/motion.flight),p=ease(raw),t=target();
        if(!t){cleanup('missing-target');return;}
        // Start coordinates remain valid through resize because the CSS-centered origin moves.
        const base=emblem.offsetWidth,ox=innerWidth/2,oy=innerHeight/2;
        const scale=1+(t.size/base-1)*p;
        emblem.style.transform=`translate3d(${(t.x-ox)*p}px,${(t.y-oy)*p}px,0) scale(${scale})`;
        name.style.filter=`blur(${p*20}px)`;name.style.opacity=String(1-Math.pow(p,.8));
        if(notice){notice.style.filter=name.style.filter;notice.style.opacity=name.style.opacity;}
        veil.style.opacity=String(1-p);layers.forEach(el=>{el.style.filter=`blur(${18*(1-p)}px)`;});
        if(raw>=1)burst(now);
      }
      if(phase==='burst'&&!closed) {
        const p=clamp((now-flightStart)/motion.burst);
        if(context){context.clearRect(0,0,innerWidth,innerHeight);context.fillStyle='#d5e8ff';context.globalAlpha=(1-p)*(1-p);
          context.beginPath();for(const q of particles){const x=q.x+q.vx*p,y=q.y+q.vy*p,r=Math.max(.1,q.r*(1-p));context.moveTo(x+r,y);context.arc(x,y,r,0,Math.PI*2);}context.fill();context.globalAlpha=1;
        }
        if(p>=1){cleanup('complete');return;}
      }
      if(!closed)frame=requestAnimationFrame(tick);
    } catch {cleanup('renderer-fallback');}
  }
  try {
    if(!workspace||!emblem||!name||!veil||!canvas)throw new Error('Incomplete startup presentation');
    if(getComputedStyle(stage).getPropertyValue('--startup-style-ready').trim()!=='1')throw new Error('Missing startup stylesheet');
    context=canvas.getContext('2d');
    emblemPaths=paths('startupEmblem',false);letterPaths=paths('startupWordmark',true);
    if(!emblemPaths.length||!letterPaths.length)throw new Error('Missing emblem paths');
    workspace.inert=true;if(icon)icon.style.visibility='hidden';
    stage.dataset.phase='drawing';stage.tabIndex=-1;stage.focus({preventScroll:true});
    document.addEventListener('keydown',guardKeys,true);
    addEventListener('resize',resize);document.addEventListener('visibilitychange',visibility);addEventListener('buaa:renderstate',visibility);
    if(reduced.addEventListener)reduced.addEventListener('change',preferenceChanged);
    else reduced.addListener?.(preferenceChanged);
    boot.onRelease=cleanup;
    // Local DOM and two paint frames define UI readiness. Optional fonts/images
    // must not postpone flight until the whole-document load watchdog removes it.
    afterPaint=()=>{readyFrame=requestAnimationFrame(()=>{readyFrame=requestAnimationFrame(onReady);});};
    if(document.readyState!=='loading')afterPaint();else document.addEventListener('DOMContentLoaded',afterPaint,{once:true});
    timer=setTimeout(()=>cleanup('watchdog'),16000);
    resize();preparePixels();frame=requestAnimationFrame(tick);
  } catch {cleanup('initialization-fallback');}
})();
