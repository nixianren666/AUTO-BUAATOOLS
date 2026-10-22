/* Headless phone presentation only. No storage, account state or network calls. */
(() => {
  'use strict';
  const root = document.documentElement;
  function classify({mode, ua, platform, touch, coarse, screenWidth, screenHeight, width}) {
    if (mode !== 'headless' || !coarse || touch < 1 || width > 1024) return false;
    // Screen dimensions survive a keyboard resize and distinguish a narrow
    // tablet/desktop window from a phone. Foldables >=600px use the desktop UI.
    const short = Math.min(screenWidth, screenHeight), long = Math.max(screenWidth, screenHeight);
    if (!(short >= 240 && short < 600 && long <= 1024 && long / short >= 1.45)) return false;
    if (/iPad|Tablet|Silk|Kindle/i.test(ua) || (/Mac/i.test(platform) && touch > 1)) return false;
    if (/Android/i.test(ua)) return /Mobile/i.test(ua);
    if (/iPhone|iPod/i.test(ua)) return true;
    if (/Windows NT|Macintosh|X11|CrOS/i.test(ua)) return false;
    return /Mobile/i.test(ua); // Unknown devices keep the normal layout.
  }
  const snapshot = () => ({mode:root.dataset.runtimeMode, ua:navigator.userAgent,
    platform:navigator.platform, touch:navigator.maxTouchPoints || 0,
    coarse:matchMedia('(any-pointer: coarse)').matches || matchMedia('(pointer: coarse)').matches, screenWidth:screen.width,
    screenHeight:screen.height, width:innerWidth});
  let active = false, open = false, frame = 0, trigger, closeButton, shade, logo;
  const sidebar = document.querySelector('.origin-sidebar');
  const main = document.querySelector('.origin-main');
  const tdToolbar = document.getElementById('tdActionToolbar');
  const tdToolbarHome = document.createComment('TD action toolbar desktop position');
  tdToolbar?.before(tdToolbarHome);
  const visibleModal = () => document.querySelector('.origin-modal-backdrop:not(.hidden)');
  function close(restore = false) {
    if (!open) return;
    open = false;
    root.removeAttribute('data-phone-menu');
    main.inert = false;
    sidebar.inert = active;
    sidebar.setAttribute('aria-hidden', String(active));
    trigger.setAttribute('aria-expanded', 'false');
    sidebar.removeAttribute('aria-modal');sidebar.removeAttribute('role');sidebar.removeAttribute('aria-label');
    shade.hidden = true;
    if (restore && !visibleModal()) trigger.focus({preventScroll:true});
  }
  function show() {
    if (!active || visibleModal()) return;
    window.BUAAUiSurfaces?.set('glassPopover', false);
    window.BUAAUiSurfaces?.set('updatePanel', false);
    open = true;
    root.dataset.phoneMenu = 'open';
    sidebar.inert = false;
    sidebar.setAttribute('aria-hidden', 'false');
    sidebar.setAttribute('role', 'dialog');sidebar.setAttribute('aria-modal', 'true');sidebar.setAttribute('aria-label', '功能菜单');
    main.inert = true;
    trigger.setAttribute('aria-expanded', 'true');
    shade.hidden = false;
    closeButton.focus({preventScroll:true});
  }
  function createControls() {
    if (trigger || !sidebar || !main) return;
    sidebar.id ||= 'remotePhoneNavigation';
    trigger = document.createElement('button');
    trigger.type = 'button';trigger.id = 'remotePhoneMenuBtn';
    trigger.className = 'origin-icon-btn remote-phone-only';
    trigger.setAttribute('aria-label', '打开功能菜单');
    trigger.setAttribute('aria-controls', sidebar.id);
    trigger.setAttribute('aria-expanded', 'false');
    trigger.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h16"/></svg>';
    trigger.addEventListener('click', () => open ? close(true) : show());
    main.querySelector('.origin-topbar').prepend(trigger);
    closeButton = document.createElement('button');
    closeButton.type = 'button';closeButton.className = 'origin-icon-btn remote-phone-only remote-phone-menu-close';
    closeButton.id = 'remotePhoneMenuClose';closeButton.setAttribute('aria-label', '收起功能菜单');
    closeButton.textContent = '✕';closeButton.addEventListener('click', () => close(true));
    sidebar.querySelector('.origin-brand').append(closeButton);
    shade = document.createElement('button');
    shade.type = 'button';shade.className = 'remote-phone-shade';shade.hidden = true;
    shade.setAttribute('aria-label', '收起功能菜单');shade.tabIndex = -1;
    shade.addEventListener('click', () => close(true));sidebar.after(shade);
    logo = sidebar.querySelector('.origin-logo-mark').cloneNode(true);
    logo.classList.add('remote-phone-only', 'remote-phone-logo');
    logo.setAttribute('aria-hidden', 'true');main.querySelector('.topbar-breadcrumb').prepend(logo);
    const current = document.getElementById('topbarCurrentSection'), label = document.createElement('span');
    label.className = 'remote-phone-only remote-phone-section-label';current.after(label);
    const heading = () => {
      const title = current.textContent.split(' / ')[0];
      if (active && label.textContent !== title) document.getElementById('mainContentScroll').scrollTop = 0;
      label.textContent = title;
    };
    heading();new MutationObserver(heading).observe(current,{childList:true,subtree:true,characterData:true});
    document.getElementById('glassControlBtn').setAttribute('aria-label', '玻璃与背景设置');
    sidebar.addEventListener('click', event => {
      if (active && !event.target.closest('#remotePhoneMenuClose') && event.target.closest('.origin-nav-item,.origin-user-capsule,.origin-network-btn')) {
        close(false);
        queueMicrotask(() => { if (!visibleModal()) trigger.focus({preventScroll:true}); });
      }
    }, true);
    document.addEventListener('buaa:surfacechange', event => { if (event.detail.visible) close(false); });
    document.addEventListener('keydown', event => {
      if (!open) return;
      if (event.key === 'Escape') { event.preventDefault();event.stopImmediatePropagation();close(true); }
      if (event.key === 'Tab') {
        const items = [...sidebar.querySelectorAll('button,[tabindex]')].filter(el => !el.disabled && el.getClientRects().length);
        const first = items[0], last = items.at(-1);
        if (!sidebar.contains(document.activeElement) || (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
          event.preventDefault();(event.shiftKey ? last : first)?.focus();
        }
      }
    }, true);
  }
  function update() {
    frame = 0;
    const next = classify(snapshot());
    if (next) createControls();
    if (active !== next) {
      close(false);active = next;
      root.toggleAttribute('data-remote-phone', active);
      if (tdToolbar) {
        if (active) document.querySelector('.td-progress-grid').before(tdToolbar);
        else tdToolbarHome.after(tdToolbar);
      }
      if (sidebar) {
        sidebar.inert = active;
        if (active) sidebar.setAttribute('aria-hidden', 'true');
        else sidebar.removeAttribute('aria-hidden');
      }
      if (!active) {
        main.inert = false;
        root.style.removeProperty('--phone-visual-height');root.style.removeProperty('--phone-visual-top');
      }
      if (active) {
        const meta = document.querySelector('meta[name=viewport]');
        if (meta && !meta.content.includes('viewport-fit')) meta.content += ', viewport-fit=cover';
      }
    }
    if (active) {
      const viewport = window.visualViewport;
      root.style.setProperty('--phone-visual-height', `${viewport?.height || innerHeight}px`);
      root.style.setProperty('--phone-visual-top', `${viewport?.offsetTop || 0}px`);
    }
  }
  const queue = () => { if (!frame) frame = requestAnimationFrame(update); };
  window.BUAARemotePhone = {classify};
  update();
  addEventListener('resize', queue);
  window.visualViewport?.addEventListener('resize', queue);
  window.visualViewport?.addEventListener('scroll', queue);
  document.addEventListener('visibilitychange', () => { if (document.hidden) close(false); });
})();
