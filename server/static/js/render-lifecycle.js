/* Render visibility only; no backend, account or request lifecycle changes. */
(() => {
  'use strict';
  let nativeVisible = true, visible = true;
  const sync = () => {
    const next = nativeVisible && !document.hidden;
    // Never rewrite root styles/attributes for repeated visible hints (resize,
    // reload callbacks). Only a real hidden/restored transition changes CSS.
    if (next === visible) return;
    visible = next;
    document.documentElement.classList.toggle('buaa-render-paused', !next);
    document.documentElement.dataset.renderState = next ? 'visible' : 'paused';
    dispatchEvent(new CustomEvent('buaa:renderstate', { detail: { visible } }));
  };
  window.BUAARenderLifecycle = {
    get visible() { return visible; },
    setNativeVisible(value, reason) {
      if (nativeVisible === (value !== false)) return;
      nativeVisible = value !== false;
      document.documentElement.dataset.renderReason = nativeVisible ? 'visible' : String(reason || 'native-hidden');
      sync();
    }
  };
  document.addEventListener('visibilitychange', sync);
  sync();
})();
