/* Real first-use DOM and requests, isolated from school and personal profiles. */
const assert = require('node:assert/strict');

async function verifyOnboarding(browser, url, check) {
  const metadataContext = await browser.newContext();
  let notice;
  try {
    await metadataContext.request.get(new URL('/api/session',url).href);
    notice = await (await metadataContext.request.get(new URL('/api/system/disclaimer',url).href)).json();
    assert.equal(typeof notice.commitment_text,'string');
    assert.equal(typeof notice.commitment_version,'string');
    assert.ok(notice.commitment_text.length>60);
  } finally { await metadataContext.close(); }
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
    { name: 'typed-pledge-both-requirements-and-ime', pledgeChecks: true },
    { name: 'typed-pledge-narrow-screen-and-keyboard', narrow: true },
    { name: 'mismatched-acceptance-version-stays-locked', staleSave: true },
    { name: 'notice-reference-is-mouse-selectable-without-copy-button', copyReference: true },
  ];
  for (const options of cases) await check('first-login-' + options.name, async () => {
    const context = await browser.newContext({ viewport: options.narrow ? {width:480,height:640} : { width: 1280, height: 840 }, reducedMotion: 'reduce' });
    const page = await context.newPage(), errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    let releaseAccounts, releaseNotice, releaseSave, posts = 0, notices = 0;
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
        await noticeGate; notices++; status = options.failNotice && notices===1 ? 503 : 200;
        json = { ...notice, accepted: !!options.accepted };
      } else if (path === '/api/system/disclaimer/accept') {
        posts++;
        assert.match(request.headers()['content-type']||'',/^application\/json/);
        assert.deepEqual(request.postDataJSON(),{agreed:true,commitment:notice.commitment_text,commitment_version:notice.commitment_version});
        await saveGate;
        status = options.failSave && posts === 1 ? 500 : 200;
        json = { status: 'ok', accepted: !options.invalidSave, commitment_version:options.staleSave?'old':notice.commitment_version };
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
        if(options.failNotice){
          await page.locator('#disclaimerRetryBtn').waitFor({state:'visible'});
          assert.equal(await page.locator('#disclaimerCommitmentInput').isDisabled(),true);
          await page.locator('#disclaimerRetryBtn').click();
        }
        await page.waitForFunction(()=>!document.getElementById('disclaimerCommitmentInput').disabled);
        assert.equal(await page.locator('#disclaimerCommitmentText').textContent(),notice.commitment_text);
        if(options.copyReference){
          for(const selector of ['.origin-disclaimer-text p','#disclaimerCommitmentText']){
            const paragraph=page.locator(selector).first();
            await paragraph.scrollIntoViewIfNeeded();
            const bounds=await paragraph.evaluate(el=>{
              if(getComputedStyle(el).userSelect!=='text')throw new Error('Reference text must be selectable');
              const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);
              let node;while((node=walker.nextNode())&&!node.textContent.trim()){}
              const range=document.createRange();range.setStart(node,0);range.setEnd(node,Math.min(12,node.length));
              const rect=range.getClientRects()[0];return {x:rect.x,y:rect.y,w:rect.width,h:rect.height};
            });
            await page.mouse.move(bounds.x+1,bounds.y+bounds.h/2);await page.mouse.down();
            await page.mouse.move(bounds.x+bounds.w-1,bounds.y+bounds.h/2,{steps:12});await page.mouse.up();
            const selection=await page.evaluate(()=>window.getSelection().toString().trim());
            assert.ok(selection.length>=5,'Dragging must select readable notice text');
            assert.ok((await paragraph.textContent()).includes(selection));
          }
          assert.equal(await page.locator('#disclaimerModal button').filter({hasText:/复制/}).count(),0);
        }
        assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(), false);
        await page.locator('#disclaimerCheck').check();
        assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(),false,'Checkbox alone cannot enter');
        if(options.pledgeChecks){
          await page.locator('#disclaimerCommitmentInput').fill('本人承诺');
          await page.evaluate(()=>handleDisclaimerAccept());assert.equal(posts,0);
          await page.locator('#disclaimerCommitmentInput').fill(notice.commitment_text.replace('24','48'));
          assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(),false);
          await page.keyboard.press('Escape');
          assert.equal(await page.locator('#disclaimerModal').isVisible(),true);
          await page.locator('#disclaimerCheck').uncheck();
          await page.locator('#disclaimerCommitmentInput').fill(notice.commitment_text);
          assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(),false,'Text alone cannot enter');
          await page.locator('#disclaimerCheck').check();
          await page.locator('#disclaimerCommitmentInput').dispatchEvent('compositionstart');
          assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(),false);
          await page.locator('#disclaimerCommitmentInput').dispatchEvent('compositionend');
        }
        await page.locator('#disclaimerCommitmentInput').fill(notice.commitment_text);
        assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(),true);
        if(options.narrow){
          await page.locator('#disclaimerCommitmentInput').focus();await page.keyboard.press('Tab');
          assert.equal(await page.locator('#disclaimerModal').evaluate(e=>e.scrollWidth<=e.clientWidth+1),true);
          await page.locator('#disclaimerAgreeBtn').scrollIntoViewIfNeeded();
          const box=await page.locator('#disclaimerAgreeBtn').boundingBox();assert.ok(box.y>=0&&box.y+box.height<=640);
          const header=await page.locator('#disclaimerModal .modal-header').boundingBox();
          const body=await page.locator('#disclaimerModal .modal-body').boundingBox();
          const footer=await page.locator('#disclaimerModal .modal-footer').boundingBox();
          assert.ok(header.y>=0&&header.y+header.height<=body.y+1);
          assert.ok(body.y+body.height<=footer.y+1&&footer.y+footer.height<=640);
        }
        await page.locator('#disclaimerAgreeBtn').click();
        if (options.holdSave) {
          await page.waitForFunction(() => firstLoginState.accepting);
          assert.equal(await page.locator('#disclaimerModal').isVisible(), true);
          assert.equal(await page.locator('#disclaimerAgreeBtn').isEnabled(), false);
          await page.evaluate(() => handleDisclaimerAccept());
          assert.equal(posts, 1); releaseSave();
        }
        if (options.failSave || options.invalidSave || options.staleSave) {
          await page.waitForFunction(() => !firstLoginState.accepting);
          assert.equal(await page.locator('#disclaimerModal').isVisible(), true);
          assert.equal(await page.locator('#loginModal').isVisible(), false);
          assert.match(await page.locator('#toastContainer').innerText(), /保存免责声明状态失败/);
          if (options.invalidSave || options.staleSave) {
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
