/* Progressive glass select presentation. The original select remains the only
   value/form source; its input/change events keep the established API path. */
(() => {
  'use strict';
  const renderHidden = () => document.hidden || window.BUAARenderLifecycle?.visible === false;
  const widgets = new Map();
  let current = null, typed = '', typedAt = 0;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const enabled = widget => [...widget.select.options].map((o, i) => !o.disabled && !o.hidden ? i : -1).filter(i => i >= 0);

  function close(restore = false) {
    if (!current) return;
    const widget = current;
    current = null;
    widget.menu.getAnimations?.({ subtree: true }).forEach(a => a.cancel());
    widget.menu.remove();
    widget.button.setAttribute('aria-expanded', 'false');
    widget.button.removeAttribute('aria-activedescendant');
    widget.button.removeAttribute('aria-controls');
    if (restore && !widget.button.closest('.hidden, [inert]')) widget.button.focus({ preventScroll: true });
  }
  function syncSelect(select) {
    const widget = widgets.get(select);
    if (!widget) return;
    const signature = [...select.options].map(o => [o.value, o.textContent, o.disabled, o.hidden].join(':')).join('|');
    if (current === widget && (widget.value !== select.value || widget.signature !== signature || select.disabled)) close();
    widget.value = select.value; widget.signature = signature;
    widget.text.textContent = select.selectedOptions[0]?.textContent || '';
    widget.button.disabled = select.disabled;
    widget.button.setAttribute('aria-required', String(select.required));
  }
  function highlight(widget, index) {
    widget.index = index;
    [...widget.menu.children].forEach(option => option.setAttribute('aria-selected', String(Number(option.dataset.index) === index)));
    const option = widget.menu.querySelector(`[data-index="${index}"]`);
    if (option) {
      widget.button.setAttribute('aria-activedescendant', option.id);
      const top = option.offsetTop, bottom = top + option.offsetHeight;
      if (top < widget.menu.scrollTop) widget.menu.scrollTop = top;
      else if (bottom > widget.menu.scrollTop + widget.menu.clientHeight) widget.menu.scrollTop = bottom - widget.menu.clientHeight;
    }
  }
  function commit(widget, index) {
    if (widget.select.disabled || !enabled(widget).includes(index)) return;
    const changed = widget.select.selectedIndex !== index;
    widget.select.selectedIndex = index;
    close(true);
    syncSelect(widget.select);
    if (changed) {
      widget.select.dispatchEvent(new Event('input', { bubbles: true }));
      widget.select.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
  function open(widget) {
    if (widget.select.disabled) return;
    if (current === widget) { close(true); return; }
    close();
    // Avoid an anchored list drifting while its parent is still entering.
    const owner = widget.select.closest('.origin-modal-backdrop, .origin-view-section');
    owner?.getAnimations?.({ subtree: true }).forEach(a => { try { a.finish(); } catch { a.cancel(); } });
    syncSelect(widget.select);
    widget.menu.replaceChildren();
    [...widget.select.options].forEach((option, index) => {
      if (option.hidden) return;
      const row = document.createElement('div');
      row.className = 'ui-select-option'; row.id = widget.select.id + 'Option' + index;
      row.setAttribute('role', 'option'); row.dataset.index = String(index);
      row.setAttribute('aria-disabled', String(option.disabled));
      const label = document.createElement('span'); label.textContent = option.textContent;
      const mark = document.createElement('span'); mark.className = 'ui-select-check'; mark.textContent = '✓'; mark.setAttribute('aria-hidden', 'true');
      row.append(label, mark); widget.menu.append(row);
      row.addEventListener('pointerdown', e => e.preventDefault()); // Keep focus on the combobox.
      row.addEventListener('pointermove', () => { if (!option.disabled) highlight(widget, index); });
      row.addEventListener('click', () => commit(widget, index));
    });
    const parent = widget.select.closest('.origin-modal-backdrop') || document.body;
    parent.append(widget.menu);
    current = widget;
    widget.button.setAttribute('aria-expanded', 'true');
    widget.button.setAttribute('aria-controls', widget.menu.id);
    const rect = widget.button.getBoundingClientRect(), width = Math.min(Math.max(rect.width, 240), innerWidth - 24);
    widget.menu.style.width = width + 'px';
    const desired = widget.menu.scrollHeight + 2, above = rect.top - 20, below = innerHeight - rect.bottom - 20;
    const upward = below < desired && above > below;
    const height = Math.min(desired, Math.max(48, upward ? above : below), 260);
    Object.assign(widget.menu.style, {
      width: width + 'px', maxHeight: height + 'px',
      left: Math.max(12, Math.min(rect.left, innerWidth - width - 12)) + 'px',
      top: Math.max(12, upward ? rect.top - height - 8 : rect.bottom + 8) + 'px',
      transformOrigin: upward ? 'bottom center' : 'top center'
    });
    highlight(widget, enabled(widget).includes(widget.select.selectedIndex) ? widget.select.selectedIndex : enabled(widget)[0]);
    if (!reduced.matches && !renderHidden()) {
      try {
        widget.menu.animate([
          { clipPath: upward ? 'inset(65% 0 0 0 round 12px)' : 'inset(0 0 65% 0 round 12px)', transform: `translateY(${upward ? 5 : -5}px)` },
          { clipPath: 'inset(0 0 0 0 round 12px)', transform: 'none' }
        ], { duration: 280, easing: 'cubic-bezier(.2,.9,.25,1)' });
        [...widget.menu.children].forEach((row, i) => row.animate([{ opacity: .35 }, { opacity: 1 }], { duration: 220, delay: i * 30, fill: 'backwards', easing: 'ease-out' }));
      } catch { /* Native value/control remain available. */ }
    }
  }
  function enhance(select, caption) {
    const shell = document.createElement('span'), button = document.createElement('button');
    const text = document.createElement('span'), arrow = document.createElement('span'), menu = document.createElement('div');
    shell.className = 'ui-select-shell';
    button.type = 'button'; button.id = select.id + 'Trigger'; button.className = 'origin-select ui-select-trigger';
    text.className = 'ui-select-text'; arrow.className = 'ui-select-chevron'; arrow.setAttribute('aria-hidden', 'true');
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg'), path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    icon.setAttribute('viewBox', '0 0 24 24'); icon.setAttribute('width', '16'); icon.setAttribute('height', '16'); icon.setAttribute('fill', 'none'); icon.setAttribute('stroke', 'currentColor'); icon.setAttribute('stroke-width', '1.7'); path.setAttribute('d', 'm6 9 6 6 6-6'); icon.append(path); arrow.append(icon);
    button.append(text, arrow); button.setAttribute('role', 'combobox'); button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false'); button.setAttribute('aria-label', caption);
    menu.id = select.id + 'Listbox'; menu.className = 'ui-select-menu'; menu.setAttribute('role', 'listbox'); menu.setAttribute('aria-label', caption);
    const widget = { select, button, text, menu, index: select.selectedIndex };
    select.before(shell); shell.append(select, button);
    if (getComputedStyle(shell).position !== 'relative') throw new Error('Optional control skin unavailable');
    select.classList.add('ui-select-native'); select.tabIndex = -1; select.setAttribute('aria-hidden', 'true');
    widgets.set(select, widget); syncSelect(select);
    button.addEventListener('click', () => open(widget));
    button.addEventListener('focus', () => { if (current !== widget) syncSelect(select); });
    select.addEventListener('change', () => syncSelect(select));
    new MutationObserver(() => syncSelect(select)).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'selected', 'hidden', 'label'] });
    select.form?.addEventListener('reset', () => queueMicrotask(() => syncSelect(select)));
    button.addEventListener('keydown', event => {
      const options = enabled(widget), shown = current === widget;
      if (!options.length || select.disabled) return;
      const key = event.key;
      if (key === 'Escape' && shown) { event.preventDefault(); event.stopPropagation(); close(true); return; }
      if (key === 'Tab') { if (shown) commit(widget, widget.index); return; }
      if (['Enter', ' '].includes(key)) {
        event.preventDefault(); event.stopPropagation();
        if (shown) commit(widget, widget.index); else open(widget);
        return;
      }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(key)) {
        event.preventDefault(); event.stopPropagation();
        if (!shown) { open(widget); if (['ArrowDown', 'ArrowUp'].includes(key)) return; }
        const position = options.indexOf(widget.index);
        highlight(widget, key === 'Home' ? options[0] : key === 'End' ? options.at(-1) : options[Math.max(0, Math.min(options.length - 1, position + (key === 'ArrowDown' ? 1 : -1)))]);
      } else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        const now = performance.now(); typed = now - typedAt > 700 ? key : typed + key; typedAt = now;
        if (!shown) open(widget);
        const index = options.find(i => select.options[i].textContent.trim().toLowerCase().startsWith(typed.toLowerCase()));
        if (index !== undefined) highlight(widget, index);
      }
    });
  }
  window.BUAAUiControls = { syncSelect, closeSelect: close };
  document.addEventListener('DOMContentLoaded', () => {
    for (const [id, caption] of [['loginModeSelect', '登录网络通道'], ['boyaCampusSelect', '生源校区'], ['tdCampusSelect', 'TD锻炼校区'], ['tdQuickCampusSelect', 'TD锻炼校区'], ['tdEntryExisting','已有入口照'], ['tdExitExisting','已有出口照']]) {
      const select = document.getElementById(id);
      if (!select) continue;
      try { enhance(select, caption); } catch {
        const widget = widgets.get(select), shell = select.closest('.ui-select-shell');
        widget?.menu.remove(); shell?.before(select); shell?.remove(); widgets.delete(select);
        select.classList.remove('ui-select-native'); select.removeAttribute('tabindex'); select.removeAttribute('aria-hidden');
      }
    }
  });
  document.addEventListener('click', e => { if (current && !current.button.contains(e.target) && !current.menu.contains(e.target)) close(); }, true);
  document.addEventListener('focusin', e => { if (current && e.target !== current.button) close(); });
  document.addEventListener('buaa:surfacechange', () => close());
  document.addEventListener('visibilitychange', () => { if (renderHidden()) close(); });
  addEventListener('buaa:renderstate', () => { if (renderHidden()) close(); });
  reduced.addEventListener?.('change', () => { if (reduced.matches) current?.menu.getAnimations?.({ subtree: true }).forEach(a => a.cancel()); });
  addEventListener('resize', () => close());
  document.addEventListener('scroll', e => { if (current && e.target !== current.menu && !current.menu.contains(e.target)) close(); }, true);
})();
