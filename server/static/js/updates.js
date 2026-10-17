/* GitHub release checks only. Never access student data or task controls. */
(() => {
  'use strict';
  const day = 86400000, key = 'origin_updates_auto', stampKey = 'origin_updates_checked';
  const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const write = (key, value) => { try { localStorage.setItem(key, value); } catch { /* Optional preference. */ } };
  document.addEventListener('DOMContentLoaded', () => {
    const button = document.getElementById('updateCheckBtn'), panel = document.getElementById('updatePanel');
    if (!button || !panel) return;
    const status = document.getElementById('updateStatus'), detail = document.getElementById('updateDetail');
    const retry = document.getElementById('updateRetryBtn'), link = document.getElementById('updateReleaseLink');
    const toggle = document.getElementById('updateAutoToggle'), indicator = document.getElementById('updateIndicator');
    let pending = null, timer = 0, lastAttempt = 0;
    toggle.checked = read(key) !== 'off';
    const closed = () => panel.classList.contains('hidden');
    const show = visible => { setUISurface('updatePanel', visible); button.setAttribute('aria-expanded', String(!closed())); };
    async function check(manual) {
      if (pending) return pending;
      retry.disabled = true; panel.setAttribute('aria-busy', 'true');
      write(stampKey, String(Date.now()));
      status.textContent = '正在检查正式版本…'; detail.textContent = '只查询版本信息，不影响后台任务'; link.classList.add('hidden');
      pending = (async () => {
        try {
          const response = await apiFetch('/api/system/updates' + (manual ? '?manual=true' : ''));
          const result = await response.json();
          const validStates = ['update_available', 'up_to_date', 'local_ahead', 'unavailable'];
          if (!validStates.includes(result.status)) throw new Error('Invalid release state');
          status.textContent = result.message; status.dataset.state = result.status;
          detail.textContent = `当前 v${result.current_version}` + (result.latest_version ? ` · 正式版 v${result.latest_version}` : '');
          indicator.classList.toggle('hidden', result.status !== 'update_available');
          document.getElementById('updateCheckLabel').textContent = result.status === 'update_available' ? '发现新版' : '检查更新';
          // Do not trust remote HTML/links: only the fixed project and stable tag.
          if (result.status === 'update_available' && /^\d+\.\d+\.\d+$/.test(result.latest_version || '')) {
            link.href = 'https://github.com/nixianren666/AUTO-BUAATOOLS/releases/tag/v' + result.latest_version;
            link.classList.remove('hidden');
          }
          if (result.status !== 'unavailable') write(stampKey, String(Date.now()));
        } catch {
          status.textContent = '暂时无法检查更新，请稍后重试'; status.dataset.state = 'unavailable'; detail.textContent = '后台任务照常运行';
        } finally {
          lastAttempt = Date.now(); pending = null; retry.disabled = false; panel.removeAttribute('aria-busy'); schedule();
        }
      })();
      return pending;
    }
    function schedule() {
      clearTimeout(timer); timer = 0;
      if (!toggle.checked || document.hidden) return;
      const saved = Number(read(stampKey)), now = Date.now();
      const last = Number.isFinite(saved) && saved > 0 && saved <= now ? saved : 0;
      const delay = Math.max(30000, last ? day - (now - last) : 30000, lastAttempt ? day - (now - lastAttempt) : 0);
      timer = setTimeout(() => { timer = 0; if (toggle.checked && !document.hidden) check(false); }, delay);
    }
    button.addEventListener('click', () => { show(closed()); if (!closed()) check(true); });
    retry.addEventListener('click', () => check(true));
    document.getElementById('updateCloseBtn').addEventListener('click', () => { show(false); button.focus(); });
    document.addEventListener('click', e => { if (!window.BUAAUiSurfaces && !document.getElementById('updateControl').contains(e.target)) show(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !closed()) { show(false); button.focus(); } });
    toggle.addEventListener('change', () => { write(key, toggle.checked ? 'on' : 'off'); schedule(); });
    document.addEventListener('visibilitychange', schedule); schedule();
  });
})();
