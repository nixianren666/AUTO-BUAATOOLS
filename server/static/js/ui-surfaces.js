/* Presentation only: exclusive floating surfaces and interruptible motion.
   No account state, requests, task controls or permanent animation loop. */
(() => {
  'use strict';
  const renderHidden = () => document.hidden || window.BUAARenderLifecycle?.visible === false;
  const ids = ['glassPopover', 'updatePanel', 'accountCardsModal', 'loginModal', 'manualSignModal', 'tdSettingsModal', 'tdCountModal', 'tdGroupModal', 'tdManualModal', 'tdLicenseModal', 'wechatModal', 'disclaimerModal'];
  const triggers = { glassPopover: 'glassControlBtn', updatePanel: 'updateCheckBtn' };
  const running = new Map(), returnFocus = new Map();
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const isOpen = el => el && !el.classList.contains('hidden');
  const sample = el => {
    if (!running.has(el)) return null;
    const target = el.querySelector('.origin-modal-dialog') || el;
    const style = getComputedStyle(target), backdrop = getComputedStyle(el);
    return { opacity: style.opacity, transform: style.transform, backdrop: backdrop.backgroundColor };
  };

  function settle(el) {
    const record = running.get(el);
    if (record) {
      running.delete(el); // Invalidate completion callbacks before cancelling.
      record.animations.forEach(animation => animation.cancel());
    }
    delete el.dataset.uiExiting;
  }

  function motion(el, opening, current) {
    if (reduced.matches || renderHidden() || typeof el.animate !== 'function') return;
    const dialog = el.querySelector('.origin-modal-dialog');
    const target = dialog || el;
    const enter = opening ? [
      { opacity: .35, transform: `translateY(${dialog ? 6 : 4}px) scale(.985)`, offset: 0 },
      { opacity: 1, transform: 'translateY(-.25px) scale(1.001)', offset: .76 },
      { opacity: 1, transform: 'none', offset: 1 }
    ] : [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(2px) scale(.992)' }];
    if (current) Object.assign(enter[0], { opacity: current.opacity, transform: current.transform });
    const record = { animations: [] };
    try {
      record.animations.push(target.animate(enter, {
        duration: opening ? (dialog ? 300 : 240) : 130,
        easing: opening ? 'cubic-bezier(.2,.8,.2,1)' : 'cubic-bezier(.4,0,1,1)'
      }));
      if (dialog) {
        const tint = getComputedStyle(el).backgroundColor;
        // Fading the whole backdrop flattens its live blur during compositing.
        // Keep the optical plane fixed; interpolate only its dimming tint.
        record.animations.push(el.animate(
          [{ backgroundColor: current?.backdrop ?? (opening ? 'transparent' : tint) },
            { backgroundColor: opening ? tint : 'transparent' }],
          { duration: opening ? 180 : 130, easing: 'ease-out' }
        ));
      }
      running.set(el, record);
      Promise.all(record.animations.map(animation => animation.finished)).then(() => {
        if (running.get(el) !== record) return;
        running.delete(el);
        delete el.dataset.uiExiting;
      }).catch(() => {
        // External animation cancellation also has to release a visual exit.
        if (running.get(el) === record) settle(el);
      });
    } catch {
      record.animations.forEach(animation => animation.cancel());
      running.delete(el);
      delete el.dataset.uiExiting;
    }
  }

  function hide(el, immediate = false, restore = true) {
    const wasOpen = isOpen(el);
    if (wasOpen) document.dispatchEvent(new CustomEvent('buaa:surfacechange', { detail: { id: el.id, visible: false } }));
    const current = sample(el);
    settle(el);
    el.classList.add('hidden');
    el.inert = true;
    el.setAttribute('aria-hidden', 'true');
    const trigger = document.getElementById(triggers[el.id]);
    trigger?.setAttribute('aria-expanded', 'false');
    if (wasOpen && restore && el.contains(document.activeElement)) {
      const previous = trigger || returnFocus.get(el);
      if (previous?.isConnected && !previous.closest('.hidden, [inert]')) previous.focus({ preventScroll: true });
      else document.activeElement.blur();
    }
    if (wasOpen && !immediate && !reduced.matches && !renderHidden() && typeof el.animate === 'function') {
      // The closed layer is purely visual during its short exit: never hit-testable
      // or keyboard-focusable. Switching to another surface always ends it first.
      el.dataset.uiExiting = '';
      motion(el, false, current);
    }
    if (immediate) returnFocus.delete(el);
  }

  function set(id, visible) {
    if (window.BUAATDAccess?.blocksSurface(id, visible)) return false;
    const el = document.getElementById(id);
    if (!el || !ids.includes(id)) return false;
    if (!visible) { hide(el); return false; }
    if (id !== 'disclaimerModal' && isOpen(document.getElementById('disclaimerModal'))) return false;
    if (isOpen(el)) return true;
    const previous = document.activeElement;
    const current = sample(el);
    ids.forEach(otherId => {
      const other = document.getElementById(otherId);
      if (other && other !== el) hide(other, true, false);
    });
    settle(el);
    returnFocus.set(el, previous);
    el.classList.remove('hidden');
    el.inert = false;
    el.setAttribute('aria-hidden', 'false');
    document.getElementById(triggers[id])?.setAttribute('aria-expanded', 'true');
    motion(el, true, current);
    document.dispatchEvent(new CustomEvent('buaa:surfacechange', { detail: { id, visible: true } }));
    if (el.classList.contains('origin-modal-backdrop')) {
      el.querySelector('button:not(:disabled), input:not(:disabled), select:not(:disabled)')?.focus({ preventScroll: true });
    }
    return true;
  }
  window.BUAAUiSurfaces = { set };
  document.addEventListener('click', event => {
    for (const [id, wrapperId] of [['glassPopover', 'glassControlWrapper'], ['updatePanel', 'updateControl']]) {
      const el = document.getElementById(id), wrapper = document.getElementById(wrapperId);
      if (isOpen(el) && wrapper && !wrapper.contains(event.target)) hide(el);
    }
  }, true); // Observe outside clicks even when business controls stop bubbling.
  document.addEventListener('DOMContentLoaded', () => {
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.dataset.uiManaged = '';
      if (!isOpen(el)) hide(el, true, false);
    });
  });
  const finish = () => { for (const el of [...running.keys()]) settle(el); };
  document.addEventListener('visibilitychange', () => { if (renderHidden()) finish(); });
  addEventListener('buaa:renderstate', () => { if (renderHidden()) finish(); });
  reduced.addEventListener?.('change', () => { if (reduced.matches) finish(); });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const modal = ids.map(id => document.getElementById(id)).find(el => isOpen(el) && el.classList.contains('origin-modal-backdrop'));
    if (!modal) return;
    const controls = [...modal.querySelectorAll('button, input, select, textarea, a[href], [tabindex]')]
      .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length && !el.closest('[inert]'));
    const first = controls[0], last = controls[controls.length - 1];
    if (!first) return;
    if (!modal.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus({ preventScroll: true });
    }
  });
})();
