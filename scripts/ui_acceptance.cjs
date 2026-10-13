/* Real browser contract tests. School operations hit an isolated encrypted Mock server. */
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const [url, executablePath, reportPath] = process.argv.slice(2);
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const context = await browser.newContext({ viewport: { width: 1280, height: 840 }, timezoneId: 'Pacific/Honolulu' });
  await context.route('**/*', route => {
    const host = new URL(route.request().url()).hostname;
    return ['127.0.0.1', 'localhost'].includes(host) ? route.continue() : route.abort();
  });
  const page = await context.newPage();
  const errors = [];
  const checks = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = async (name, action) => { await action(); checks.push(name); };
  try {
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => typeof appState === 'object' && appState.accounts.length === 2);
    await check('initialization-and-paused-health', async () => {
      assert.match(await page.locator('#regularDaemonStatus').textContent(), /暂停/);
      assert.equal(await page.evaluate(() => document.body.scrollWidth <= innerWidth + 2), true);
    });
    await check('boya-tab-matches-displayed-data', async () => {
      await page.locator('#navBtnBoya').click();
      await page.waitForFunction(() => appState.boyaCourses.length === 4);
      assert.equal(await page.locator('#tabBoyaAll').evaluate(e => e.classList.contains('active')), true);
      await page.locator('#tabBoyaSelected').click();
      assert.equal(await page.locator('#boyaCoursesFeed .feed-card').count(), 2);
    });
    await check('boya-sign-and-signout-do-not-invent-exam-pass', async () => {
      await page.locator('[data-action="sign"][data-id="2001"]').click();
      await page.waitForFunction(() => appState.boyaSelected.some(c => c.courseId === 2001 && c.signed_in));
      await page.locator('[data-action="signout"][data-id="2001"]').click();
      await page.waitForFunction(() => appState.boyaSelected.some(c => c.courseId === 2001 && c.signed_out));
      assert.equal(await page.evaluate(() => appState.boyaSelected.find(c => c.courseId === 2001).final_passed), false);
    });
    await check('account-modal-and-regular-sign-refresh', async () => {
      await page.locator('#navBtnAccounts').click();
      await page.locator('[data-action="switchAccount"][data-id="fixture-account-2"]').click();
      await page.waitForFunction(() => appState.activeUsername === 'fixture-account-2' && appState.classes.some(c => c.courseSchedId === '1002'));
      await page.locator('#navBtnRegular').click();
      await page.locator('[data-action="regularSign"][data-id="1002"]').click();
      await page.waitForFunction(() => appState.classes.some(c => c.courseSchedId === '1002' && c.signStatus === 1));
      assert.equal(await page.locator('#metricSignedClasses').textContent(), '1');
    });
    await check('manual-popup-and-glass-controls', async () => {
      await page.getByRole('button', { name: '手动 ID 签到', exact: true }).click();
      assert.equal(await page.locator('#manualSignModal').evaluate(e => e.classList.contains('hidden')), false);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#manualSignModal').evaluate(e => e.classList.contains('hidden')), true);
      await page.evaluate(() => updateGlassOpacity('80', false));
      assert.equal(await page.locator('#glassPercentText').textContent(), '透光 80%');
      await page.locator('#glassControlBtn').click();
      assert.equal(await page.locator('#glassPopover').evaluate(e=>e.classList.contains('hidden')),false);
      await page.keyboard.press('Escape');
      assert.equal(await page.locator('#glassPopover').evaluate(e=>e.classList.contains('hidden')),true);
    });
    await check('unknown-calendar-and-signinfo-cannot-invent-semester-pass', async () => {
      assert.equal(await page.evaluate(() => isCourseFinalPassed({checkin:5,pass:1,signInfo:'{"signIn":null}'})), false);
      await page.evaluate(() => renderBoyaStatistics({semester_known:false,moral_completed:99}));
      assert.match(await page.locator('#boyaCompletionRate').textContent(), /不能计算/);
      assert.equal(await page.locator('#boyaEarnedCredits').textContent(), '—');
      await page.evaluate(() => renderBoyaStatistics({semester_known:true,moral_completed:1,labor_completed:0,art_completed:0,security_health_completed:0}));
      assert.equal(await page.locator('#boyaEarnedCredits').textContent(), '1');
    });
    await check('regular-window-and-unknown-state-disable-manual-button', async () => {
      await page.evaluate(() => renderClassesList([{courseSchedId:'3001',courseName:'unknown-window',signStatus:0,classBeginTime:'2000-01-01 08:00:00'}]));
      assert.equal(await page.locator('[data-action="regularSign"]').isDisabled(),true);
      assert.match(await page.locator('[data-action="regularSign"]').textContent(),/结束/);
    });
    await check('unknown-capacity-category-and-partial-id-never-become-available-art-course', async () => {
      const value=await page.evaluate(() => {
        let rejected=false;
        try { courseActionId('2001-invalid'); } catch { rejected=true; }
        appState.boyaTab='all';appState.boyaSearchKeyword='';appState.boyaCategoryFilter='全部';appState.boyaAvailableOnly=true;
        appState.boyaCourses=[{id:9001,courseName:'synthetic art title',category_key:'智育',capacity_available:false,autonomous_config_valid:false}];
        renderBoyaFeed();
        return {rejected,category:normalizeBoyaCategory({courseKind:'智育',courseName:'艺术课程'})};
      });
      assert.equal(value.rejected,true);
      assert.equal(value.category,'智育');
      assert.equal(await page.locator('#boyaCoursesFeed .feed-card').count(),0);
    });
    await check('old-account-response-cannot-overwrite-new-view', async () => {
      let release;
      await page.route('**/api/classes**', async route => {
        const username = new URL(route.request().url()).searchParams.get('username');
        if (username === 'fixture-a') await new Promise(resolve => { release = resolve; });
        await route.fulfill({ json: { status: 'success', username, classes: [{ courseSchedId: '3001', courseName: username, signStatus: 0 }] } });
      });
      await page.evaluate(() => { appState.activeUsername = 'fixture-a'; viewGeneration++; globalThis.oldRequest = fetchClasses(true); });
      for (let i = 0; !release && i < 100; i++) await page.waitForTimeout(10);
      assert.ok(release, 'first account request must have started');
      await page.evaluate(async () => { appState.activeUsername = 'fixture-b'; viewGeneration++; await fetchClasses(true); });
      release();
      await page.evaluate(async () => { await globalThis.oldRequest; });
      assert.equal(await page.evaluate(() => appState.classes[0].courseName), 'fixture-b');
    });
    await check('click-injection-and-text-injection-inert', async () => {
      await page.evaluate(() => renderClassesList([{ courseSchedId: "1001');globalThis.injected=1;//", courseName: '<img src=x onerror=globalThis.injected=2>', signStatus: 0 }]));
      const button = page.locator('[data-action="regularSign"]');
      assert.equal(await button.getAttribute('onclick'), null);
      await button.dispatchEvent('click'); // Even a forged click bypassing disabled UI stays inert.
      assert.equal(await page.evaluate(() => globalThis.injected), undefined);
      assert.equal(await page.locator('#classesFeed img').count(), 0);
    });
    assert.deepEqual(errors, []);
    fs.writeFileSync(reportPath, JSON.stringify({ passed: true, checks, script_errors: errors }, null, 2));
  } catch (error) {
    fs.writeFileSync(reportPath, JSON.stringify({ passed: false, checks, error: error.message, script_errors: errors }, null, 2));
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
