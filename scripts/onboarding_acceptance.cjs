/* Real first-use DOM and requests, isolated from school and personal profiles. */
const assert = require('node:assert/strict');

async function verifyOnboarding(browser, url, check) {
  const cases = [
    { name: 'notice-arrives-first', order: 'notice' },
    { name: 'accounts-arrive-first', order: 'accounts' },
    { name: 'accepted-before-slow-accounts', order: 'notice', lateAccounts: true },
    { name: 'previously-accepted-empty-profile', accepted: true },
    { name: 'existing-account-not-interrupted', existing: true },
    { name: 'failed-save-stays-open-and-retries', failSave: true },
    { name: 'unconfirmed-save-stays-open', invalidSave: true },
    { name: 'pending-save-no-double-submit', holdSave: true },
    { name: 'unavailable-notice-requires-confirmation', failNotice: true },
    { name: 'unknown-accounts-never-assumed-empty', malformedAccounts: true, accepted: true },
    { name: 'failed-accounts-never-assumed-empty', failAccounts: true, accepted: true },
    { name: 'fallback-without-motion-module', fallback: true },
  ];
  for (const options of cases) await check('first-login-' + options.name, async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 840 }, reducedMotion: 'reduce' });
    const page = await context.newPage(), errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    let releaseAccounts, releaseNotice, releaseSave, posts = 0;
    const accountsGate = new Promise(resolve => { releaseAccounts = resolve; });
    const noticeGate = new Promise(resolve => { releaseNotice = resolve; });
    const saveGate = new Promise(resolve => { releaseSave = resolve; });
    if (options.order !== 'notice') releaseAccounts();
    if (options.order !== 'accounts') releaseNotice();
    if (!options.holdSave) releaseSave();
    await context.route('**/*', async route => {
      const request = route.request(), parsed = new URL(request.url()), path = parsed.pathname;
      if (!['127.0.0.1', 'localhost'].includes(parsed.hostname)) return route.abort();
      if (options.fallback && path.endsWith('/ui-surfaces.js')) return route.abort();
      if (!path.startsWith('/api/')) return route.continue();
      requests.push({ path, method: request.method() });
      let json = { status: 'ok' }, status = 200;
      if (path === '/api/session') json = { csrf: 'synthetic-first-use-csrf' };
      else if (path === '/api/status') json = { authenticated: false, mode: 'direct' };
      else if (path === '/api/accounts') {
        await accountsGate;
        status = options.failAccounts ? 503 : 200;
        json = options.malformedAccounts ? {} : { accounts: options.existing ? [{ username: 'fixture-first-use', name: '演示账号', auto_checkin: false }] : [], active_username: options.existing ? 'fixture-first-use' : '' };
      } else if (path === '/api/system/disclaimer') {
        await noticeGate; status = options.failNotice ? 503 : 200;
        json = { accepted: !!options.accepted };
      } else if (path === '/api/system/disclaimer/accept') {
        posts++; await saveGate;
        status = options.failSave && posts === 1 ? 500 : 200;
        json = { status: 'ok', accepted: !options.invalidSave };
      } else if (path === '/api/config') json = { global_auto_checkin: false };
      else if (path === '/api/classes') json = { classes: [] };
      else if (path === '/api/boya/courses') json = { courses: [] };
      else if (path === '/api/boya/selected') json = { selected: [] };
      else if (path === '/api/boya/statistics') json = { statistics: {} };
      else if (path === '/api/logs') json = { logs: [] };
      return route.fulfill({ status, json });
    });
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => !document.documentElement.classList.contains('startup-running'));
      if (options.order === 'accounts') {
        await page.waitForFunction(() => firstLoginState.accountsReady);
        assert.equal(await page.locator('#loginModal').isVisible(), false, 'Login must wait for notice response');
        releaseNotice();
      }
      if (!options.accepted) {
        await page.locator('#disclaimerModal').waitFor({ state: 'visible' });
        assert.equal(await page.locator('#loginModal').isVisible(), false, 'Login must stay below notice');
        if (!options.lateAccounts) {
          releaseAccounts(); await page.waitForFunction(() => firstLoginState.accountsReady);
        }
        assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(), false);
        await page.locator('#disclaimerCheck').check();
        await page.locator('#disclaimerAgreeBtn').click();
        if (options.holdSave) {
          await page.waitForFunction(() => firstLoginState.accepting);
          assert.equal(await page.locator('#disclaimerModal').isVisible(), true);
          assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(), false);
          await page.evaluate(() => handleDisclaimerAccept());
          assert.equal(posts, 1); releaseSave();
        }
        if (options.failSave || options.invalidSave) {
          await page.waitForFunction(() => !firstLoginState.accepting);
          assert.equal(await page.locator('#disclaimerModal').isVisible(), true);
          assert.equal(await page.locator('#loginModal').isVisible(), false);
          assert.match(await page.locator('#toastContainer').innerText(), /保存免责声明状态失败/);
          if (options.invalidSave) {
            assert.deepEqual(errors, []);
            assert.equal(posts, 1);
            assert.equal(requests.filter(x => x.path === '/api/login').length, 0);
            return;
          }
          await page.locator('#disclaimerAgreeBtn').click();
        }
        await page.locator('#disclaimerModal').waitFor({ state: 'hidden' });
        if (options.lateAccounts) {
          assert.equal(await page.locator('#loginModal').isVisible(), false);
          releaseAccounts();
        }
      }
      if (options.existing || options.malformedAccounts || options.failAccounts) {
        await page.waitForFunction(() => firstLoginState.disclaimerAccepted);
        assert.equal(await page.locator('#loginModal').isVisible(), false, 'Existing or unconfirmed accounts must not prompt login');
      } else {
        await page.locator('#loginModal').waitFor({ state: 'visible' });
        assert.equal(await page.locator('#disclaimerModal').isVisible(), false);
        assert.equal(await page.locator('.origin-modal-backdrop:not(.hidden)').count(), 1);
        await page.keyboard.press('Escape');
        await page.locator('#loginModal').waitFor({ state: 'hidden' });
        await page.evaluate(() => fetchInitialState());
        assert.equal(await page.locator('#loginModal').isVisible(), false);
        await page.locator('#navBtnAccounts').click();
        await page.getByRole('button', { name: '+ 添加新学生账号', exact: true }).click();
        await page.locator('#loginModal').waitFor({ state: 'visible' });
      }
      assert.deepEqual(errors, []);
      assert.equal(requests.filter(x => x.path === '/api/login').length, 0, 'No school authentication before explicit login');
      assert.equal(requests.some(x => /^\/api\/(signin|boya\/(select|sign|drop))$/.test(x.path)), false);
    } finally {
      releaseAccounts(); releaseNotice(); releaseSave(); await context.close();
    }
  });
}
module.exports = { verifyOnboarding };
