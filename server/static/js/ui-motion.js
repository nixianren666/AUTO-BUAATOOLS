/* Gesture-driven presentation only. No API calls, data rewriting or idle loop. */
(() => {
  'use strict';
  const renderHidden = () => document.hidden || window.BUAARenderLifecycle?.visible === false;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const motions = new Map(), flights = new Map();
  const allowed = () => !reduced.matches && !renderHidden() && typeof Element.prototype.animate === 'function';
  function stop(key) {
    const old = motions.get(key);
    if (!old) return;
    motions.delete(key); old.animations.forEach(a => a.cancel()); old.finish?.();
  }
  function play(key, elements, distance = 12, duration = 380, stagger = 35) {
    stop(key);
    if (!allowed()) return;
    const record = { animations: [] }; motions.set(key, record);
    try {
      elements.filter(el => el?.getClientRects().length).slice(0, 7).forEach((el, index) => {
        const travel = el.matches('.modal-footer') ? 0 : distance;
        record.animations.push(el.animate([
          { opacity: .28, transform: `translateY(${travel}px)` },
          { opacity: 1, transform: 'none' }
        ], { duration, delay: index * stagger, fill: 'backwards', easing: 'cubic-bezier(.16,1,.3,1)' }));
      });
      Promise.all(record.animations.map(a => a.finished)).then(() => { if (motions.get(key) === record) motions.delete(key); }).catch(() => { if (motions.get(key) === record) stop(key); });
    } catch { stop(key); }
  }
  function revealView(view) {
    if (!view) return;
    play('view', [...view.children], 16, 440, 45);
  }
  function clearFlight(host) {
    const record = flights.get(host);
    if (!record) return;
    flights.delete(host); record.animation?.cancel(); record.plane.remove(); record.target.classList.remove('ui-highlight-target');
  }
  function fly(host, previous, target) {
    if (!allowed() || !host || !previous || target === previous || !target.classList.contains('active')) return;
    const rect = (flights.get(host)?.plane || previous).getBoundingClientRect();
    clearFlight(host);
    const next = target.getBoundingClientRect(), parent = host.getBoundingClientRect(), style = getComputedStyle(target);
    if (!next.width || !next.height || !host.getClientRects().length) return;
    const plane = document.createElement('span'); plane.className = 'ui-selection-flight'; plane.setAttribute('aria-hidden', 'true');
    Object.assign(plane.style, {
      left: next.left - parent.left - host.clientLeft + 'px', top: next.top - parent.top - host.clientTop + 'px',
      width: next.width + 'px', height: next.height + 'px', borderRadius: style.borderRadius,
      backgroundImage: style.backgroundImage, backgroundColor: style.backgroundColor,
      boxShadow: style.boxShadow, borderColor: style.borderColor, borderWidth: style.borderWidth
    });
    host.classList.add('ui-flight-host'); [...host.children].filter(el => el.matches('button')).forEach(el => el.classList.add('ui-flight-item'));
    host.append(plane); target.classList.add('ui-highlight-target');
    const record = { plane, target, animation: null }; flights.set(host, record);
    try {
      record.animation = plane.animate([
        { transform: `translate(${rect.left - next.left}px,${rect.top - next.top}px) scale(${rect.width / next.width},${rect.height / next.height})` },
        { transform: 'none' }
      ], { duration: 380, easing: 'cubic-bezier(.22,1.15,.36,1)' });
      record.animation.finished.then(() => { if (flights.get(host) === record) clearFlight(host); }).catch(() => { if (flights.get(host) === record) clearFlight(host); });
    } catch { clearFlight(host); }
  }
  const gestures = new WeakMap();
  document.addEventListener('click', event => {
    const target = event.target.closest('.origin-nav-item, .segmented-btn, .filter-pill, .feature-toggle-pill');
    if (!target || target.disabled) return;
    const nav = target.matches('.origin-nav-item');
    // Account/log action buttons without active-state navigation do not move a pill.
    const host = target.parentElement;
    const previous = host.querySelector(nav ? '.origin-nav-item.active' : '.active');
    gestures.set(event, { target, nav, host, previous });
  }, true);
  document.addEventListener('click', event => {
    const gesture = gestures.get(event);
    if (!gesture) return;
    const { target, nav, host, previous } = gesture;
      if (!target.matches('.feature-toggle-pill')) fly(host, previous, target);
      if (nav && target !== previous && target.classList.contains('active')) revealView(document.querySelector('.origin-view-section:not(.hidden)'));
      else if (target.matches('.segmented-btn, .filter-pill, .feature-toggle-pill')) {
        const view = target.closest('.origin-view-section');
        if (view?.id === 'viewBoya') { stop('view'); play('results', [...document.getElementById('boyaCoursesFeed').children], 12, 360, 28); }
        else if (view?.id === 'viewLogs') play('logs', [document.getElementById('logsContainer')], 8, 280, 0);
      }
  });
  document.addEventListener('input', event => {
    if (!event.target.matches('.origin-search-box input')) return;
    play('results', [...document.getElementById('boyaCoursesFeed').children], 8, 260, 20);
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('.origin-btn, .segmented-btn, .filter-pill, .feature-toggle-pill');
    if (!button || button.disabled || !allowed()) return;
    const rect = button.getBoundingClientRect(), size = Math.hypot(rect.width, rect.height) * 2;
    const wave = document.createElement('span'); wave.className = 'ui-glass-ripple'; wave.setAttribute('aria-hidden', 'true');
    const x = event.detail ? event.clientX - rect.left : rect.width / 2, y = event.detail ? event.clientY - rect.top : rect.height / 2;
    Object.assign(wave.style, { width: size + 'px', height: size + 'px', left: x - size / 2 + 'px', top: y - size / 2 + 'px' });
    button.classList.add('ui-ripple-host'); button.append(wave);
    const key = 'ripple-' + (button.id || button.textContent.trim());
    stop(key);
    try {
      const animation = wave.animate([{ transform: 'scale(0)', opacity: .5 }, { transform: 'scale(1)', opacity: 0 }], { duration: 460, easing: 'cubic-bezier(.2,.7,.2,1)' });
      const record = { animations: [animation], finish: () => wave.remove() }; motions.set(key, record);
      animation.finished.then(() => { if (motions.get(key) === record) { motions.delete(key); wave.remove(); } }).catch(() => { if (motions.get(key) === record) stop(key); });
    } catch { wave.remove(); }
  });
  document.addEventListener('buaa:surfacechange', event => {
    if (!event.detail?.visible) { stop('dialog-content'); return; }
    const el = document.getElementById(event.detail.id);
    if (!el?.classList.contains('origin-modal-backdrop')) return;
    // Keep content live and clickable; stagger only the established sections.
    play('dialog-content', [...el.querySelectorAll('.modal-header, .modal-body, .modal-footer')], 10, 360, 45);
  });
  document.addEventListener('DOMContentLoaded', () => {
    revealView(document.querySelector('.origin-view-section:not(.hidden)'));
    const details = document.querySelector('#viewBoya details'), form = document.getElementById('boyaTargetsForm');
    if (!details || !form) return;
    const summary = details.querySelector('summary');
    summary.addEventListener('click', event => {
      if (!allowed()) { summary.removeAttribute('aria-expanded'); form.inert = false; return; }
      event.preventDefault();
      const record = motions.get('details'), expanded = record ? !record.expanded : !details.open;
      const height = details.open ? form.getBoundingClientRect().height : 0;
      stop('details');
      details.open = true; summary.setAttribute('aria-expanded', String(expanded));
      form.inert = !expanded;
      if (!expanded && form.contains(document.activeElement)) summary.focus({ preventScroll: true });
      const full = form.scrollHeight;
      let animation;
      try { animation = form.animate([
        { height: height + 'px', opacity: height ? 1 : .1, marginTop: height ? '12px' : '0px' },
        { height: (expanded ? full : 0) + 'px', opacity: expanded ? 1 : .1, marginTop: expanded ? '12px' : '0px' }
      ], { duration: 320, easing: 'cubic-bezier(.22,1,.36,1)' }); }
      catch { details.open = expanded; summary.removeAttribute('aria-expanded'); return; }
      form.classList.add('ui-accordion-moving');
      const state = { animations: [animation], expanded, finish: () => { details.open = expanded; form.inert = !expanded; form.classList.remove('ui-accordion-moving'); summary.removeAttribute('aria-expanded'); } };
      motions.set('details', state);
      animation.finished.then(() => { if (motions.get('details') === state) { motions.delete('details'); state.finish(); } }).catch(() => { if (motions.get('details') === state) stop('details'); });
    });
  });
  const finish = () => { for (const key of [...motions.keys()]) stop(key); for (const host of [...flights.keys()]) clearFlight(host); };
  document.addEventListener('visibilitychange', () => { if (renderHidden()) finish(); });
  addEventListener('buaa:renderstate', () => { if (renderHidden()) finish(); });
  reduced.addEventListener?.('change', () => { if (reduced.matches) finish(); });
  addEventListener('resize', finish);
})();
