/* UI-only synthetic authorization; real signature/storage tests run separately. */
const assert = require('node:assert/strict');
exports.verifyTDGate = async (page, check) => {
  const user = await page.evaluate(() => appState.activeUsername);
  const active = {active:true,expires_epoch:4102444799,expires_at:'2099-12-31T23:59:59+08:00',reason:''};
  let allowed=false, unavailable=false, writes=0;
  const events=[];
  const listener=r=>{const p=new URL(r.url()).pathname;if(p.startsWith('/api/td/'))events.push(p);};
  page.on('request',listener);
  const status=r=>r.fulfill(unavailable?{status:503,json:{detail:'synthetic unavailable'}}:{json:{license:allowed?active:{active:false,reason:'尚未激活'}}});
  const full=async r=>{const response=await r.fetch();await r.fulfill({response,json:{...await response.json(),license:allowed?active:{active:false,reason:'尚未激活'}}});};
  const activate=async r=>{writes++;if(writes===1)return r.fulfill({status:409,json:{detail:'synthetic invalid license'}});allowed=true;return r.fulfill({json:{license:active}});};
  const request=r=>r.fulfill({json:{request:'TDR1.synthetic-request-only'}});
  await page.route('**/api/td/license/status?**',status);
  await page.route('**/api/td/status?**',full);
  await page.route('**/api/td/license/activate?**',activate);
  await page.route('**/api/td/license/request?**',request);
  const locked=async()=>{
    assert.equal(await page.locator('#viewTD').isVisible(),false);
    assert.notEqual(await page.evaluate(()=>appState.currentMainView),'td');
    assert.equal(await page.locator('#tdLicenseModal').isVisible(),true);
  };
  await check('td-entrance-check-before-page-gallery-or-task-read',async()=>{
    await page.locator('#navBtnTD').click();await page.waitForFunction(()=>!document.getElementById('tdLicenseRequestBtn').disabled);
    await locked();assert.deepEqual(events,['/api/td/license/status']);
    assert.equal(await page.locator('[data-td-close="tdLicenseModal"]:visible').count(),0);
    assert.match(await page.locator('#tdLicenseAccessState').textContent(),/未激活/);
  });
  await check('td-unactivated-escape-backdrop-and-other-surface-cannot-dismiss',async()=>{
    await page.keyboard.press('Escape');await locked();
    await page.locator('#tdLicenseModal').click({position:{x:8,y:8}});await locked();
    await page.evaluate(()=>{setUISurface('tdLicenseModal',false);openAccountCardsModal();window.BUAAUiSurfaces?.set('updatePanel',true);});
    await locked();assert.equal(await page.locator('#accountCardsModal').isVisible(),false);
  });
  await check('td-entrance-request-failed-activation-keeps-page-locked',async()=>{
    await page.locator('#tdLicenseRequestBtn').click();await page.waitForFunction(()=>document.getElementById('tdLicenseRequest').value.startsWith('TDR1.'));
    await page.locator('#tdLicenseCode').fill('TDL1.'+'synthetic'.repeat(15));await page.locator('#tdLicenseActivateBtn').click();
    await page.waitForFunction(()=>document.getElementById('tdLicenseError').textContent.includes('invalid'));
    await locked();assert.equal(writes,1);
  });
  await check('td-entrance-success-admits-current-account-only',async()=>{
    await page.locator('#tdLicenseActivateBtn').click();await page.waitForFunction(()=>appState.currentMainView==='td'&&!document.getElementById('tdSettingsBtn').disabled);
    await page.locator('#tdLicenseModal').waitFor({state:'hidden'});
    assert.equal(await page.locator('#tdLicenseModal').isVisible(),false);assert.equal(writes,2);
    await page.locator('#tdLicenseBtn').click();await page.keyboard.press('Escape');
    assert.equal(await page.locator('#tdLicenseModal').evaluate(e=>e.classList.contains('hidden')),true);
  });
  await check('td-expired-view-returns-to-gate-without-locked-page',async()=>{
    allowed=false;await page.locator('#tdRefreshBtn').click();await page.waitForFunction(()=>!document.getElementById('tdLicenseRequestBtn').disabled);
    await locked();await page.locator('#tdLicenseBack').click();await page.waitForFunction(()=>document.getElementById('tdLicenseModal').classList.contains('hidden'));
    assert.equal(await page.evaluate(()=>appState.currentMainView),'regular');
  });
  await check('td-entrance-local-service-error-fails-closed-and-can-return',async()=>{
    unavailable=true;await page.locator('#navBtnTD').click();await page.waitForFunction(()=>document.getElementById('tdLicenseError').textContent.includes('未完成'));
    await locked();await page.locator('#tdLicenseBack').click();unavailable=false;
  });
  await check('td-active-entry-slow-status-never-opens-or-paints-activation-card',async()=>{
    allowed=true;
    for (const menu of ['navBtnRegular','navBtnBoya']) {
      await page.locator('#'+menu).click();
      await page.evaluate(()=>{window.gateOpens=0;window.gatePaints=0;window.gateSampling=true;window.gateOpened=e=>{if(e.detail?.id==='tdLicenseModal'&&e.detail.visible)window.gateOpens++;};document.addEventListener('buaa:surfacechange',window.gateOpened);const sample=()=>{if(document.getElementById('tdLicenseModal').getClientRects().length)window.gatePaints++;if(window.gateSampling)requestAnimationFrame(sample);};requestAnimationFrame(sample);});
      const slow=async r=>{await new Promise(done=>setTimeout(done,450));await r.fulfill({json:{license:active}});};
      await page.route('**/api/td/license/status?**',slow);await page.locator('#navBtnTD').click();
      await page.waitForTimeout(180);assert.notEqual(await page.evaluate(()=>appState.currentMainView),'td');assert.equal(await page.locator('#tdLicenseModal').isVisible(),false);
      await page.waitForFunction(()=>appState.currentMainView==='td');await page.waitForTimeout(160);
      const seen=await page.evaluate(()=>{window.gateSampling=false;document.removeEventListener('buaa:surfacechange',window.gateOpened);return {opens:window.gateOpens,paints:window.gatePaints};});
      assert.deepEqual(seen,{opens:0,paints:0});await page.unroute('**/api/td/license/status?**',slow);
    }
    await page.locator('#navBtnRegular').click();allowed=false;
  });
  await check('td-pending-entry-cancelled-by-navigation-or-other-surface',async()=>{
    for(const action of ['navigation','surface']) {
      let release;const held=async r=>{await new Promise(done=>release=done);try{await r.fulfill({json:{license:active}});}catch{}};
      await page.route('**/api/td/license/status?**',held);await page.locator('#navBtnTD').click();
      for(let i=0;!release&&i<100;i++)await page.waitForTimeout(10);assert.ok(release);
      if(action==='navigation')await page.locator('#navBtnBoya').click();else await page.locator('#navBtnAccounts').click();
      release();await page.waitForTimeout(100);assert.notEqual(await page.evaluate(()=>appState.currentMainView),'td');assert.equal(await page.locator('#tdLicenseModal').isVisible(),false);
      if(action==='surface'){assert.equal(await page.locator('#accountCardsModal').isVisible(),true);await page.keyboard.press('Escape');}
      await page.unroute('**/api/td/license/status?**',held);
    }
    await page.locator('#navBtnRegular').click();
  });
  await check('td-renewal-controls-open-only-for-current-accounts-renewal-window',async()=>{
    allowed=true;await page.locator('#navBtnTD').click();await page.waitForFunction(()=>appState.currentMainView==='td'&&!document.getElementById('tdLicenseBtn').disabled);
    await page.locator('#tdLicenseBtn').click();assert.equal(await page.locator('#tdLicenseRequestBtn').isDisabled(),true);await page.keyboard.press('Escape');
    const renewable=async r=>{const response=await r.fetch();await r.fulfill({response,json:{...await response.json(),license:{...active,renewable:true}}});};
    await page.route('**/api/td/status?**',renewable);await page.locator('#tdRefreshBtn').click();await page.waitForFunction(()=>!document.getElementById('tdLicenseBtn').disabled);
    await page.locator('#tdLicenseBtn').click();assert.equal(await page.locator('#tdLicenseRequestBtn').isDisabled(),false);assert.equal(await page.locator('#tdLicenseActivateBtn').isDisabled(),false);
    assert.match(await page.locator('#tdLicenseAccessState').textContent(),/续期窗口/);
    await page.locator('#tdLicenseRequestBtn').click();await page.waitForFunction(()=>document.getElementById('tdLicenseRequest').value.startsWith('TDR1.'));
    await page.keyboard.press('Escape');await page.unroute('**/api/td/status?**',renewable);await page.locator('#navBtnRegular').click();allowed=false;
  });
  await check('td-entrance-late-authorization-cannot-reopen-after-return',async()=>{
    let release;const held=async r=>{await new Promise(done=>release=done);try{await r.fulfill({json:{license:active}});}catch{}};
    await page.route('**/api/td/license/status?**',held);await page.locator('#navBtnTD').click();
    for(let i=0;!release&&i<100;i++)await page.waitForTimeout(10);assert.ok(release);
    await page.locator('#navBtnRegular').click();release();await page.waitForTimeout(100);
    assert.equal(await page.evaluate(()=>appState.currentMainView),'regular');assert.equal(await page.locator('#viewTD').isVisible(),false);
    await page.unroute('**/api/td/license/status?**',held);
  });
  await check('td-gate-fallback-without-optional-surface-module',async()=>{
    await page.evaluate(()=>{window.savedSurfaces=window.BUAAUiSurfaces;window.BUAAUiSurfaces=null;});
    await page.locator('#navBtnTD').click();await page.waitForFunction(()=>!document.getElementById('tdLicenseRequestBtn').disabled);await locked();
    await page.keyboard.press('Escape');await locked();await page.locator('#tdLicenseBack').click();
    await page.evaluate(()=>{window.BUAAUiSurfaces=window.savedSurfaces;delete window.savedSurfaces;});
  });
  await check('td-entrance-account-change-discards-previous-authorization',async()=>{
    allowed=true;await page.locator('#navBtnTD').click();await page.waitForFunction(()=>appState.currentMainView==='td');
    allowed=false;await page.evaluate(user=>{appState.activeUsername=user==='fixture-account-1'?'fixture-account-2':'fixture-account-1';document.dispatchEvent(new CustomEvent('buaa:accountview'));},user);
    await page.waitForFunction(()=>!document.getElementById('tdLicenseRequestBtn').disabled);await locked();
    await page.locator('#tdLicenseBack').click();
    await page.evaluate(user=>{appState.activeUsername=user;document.dispatchEvent(new CustomEvent('buaa:accountview'));},user);
  });
  await page.unroute('**/api/td/license/status?**',status);await page.unroute('**/api/td/status?**',full);
  await page.unroute('**/api/td/license/activate?**',activate);await page.unroute('**/api/td/license/request?**',request);
  page.off('request',listener);
};
