const assert = require('node:assert/strict');
exports.verifySso = async function(browser, url, check) {
  const context = await browser.newContext({viewport:{width:1280,height:840},reducedMotion:'reduce'});
  await context.route('**/*', route => ['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  const page = await context.newPage();
  let handler, requests=[];
  await page.route('**/api/login', async route => { requests.push(route.request().postDataJSON()); await handler(route); });
  const image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6n9sAAAAASUVORK5CYII=';
  const fill=async()=>{await page.evaluate(()=>openLoginModal());await page.locator('#loginUsername').fill('fixture-login');await page.locator('#loginPassword').fill('fixture password ');await page.locator('#loginModeSelect').selectOption('direct',{force:true});};
  try {
    await page.goto(url);await page.waitForFunction(()=>!!window.appState || typeof appState !== 'undefined');
    await page.waitForFunction(()=>!document.documentElement.classList.contains('startup-running'));
    await check('sso-captcha-retains-password-and-network-binding', async()=>{
      handler=r=>r.fulfill({json:{status:'captcha_required',mode:'webvpn',captcha_id:'fixture-captcha',captcha_image:image,message:'请输入学校验证码'}});
      await fill();await page.locator('#loginSubmitBtn').click();await page.locator('#loginCaptchaGroup').waitFor({state:'visible'});
      assert.equal(requests[0].password,'fixture password ');
      assert.equal(await page.locator('#loginModeSelect').inputValue(),'webvpn');
      assert.equal(await page.locator('#loginCaptchaInput').getAttribute('required'),'');
      await page.locator('#loginCaptchaInput').fill('fixture-answer');
      handler=async r=>{await new Promise(resolve=>setTimeout(resolve,120));await r.fulfill({json:{status:'success',authenticated:true,iclass_ready:true,boya_ready:true}});};
      await page.locator('#loginForm').evaluate(form=>{for(let i=0;i<2;i++)form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));});
      await page.locator('#loginModal').waitFor({state:'hidden'});
      assert.equal(requests.length,2);assert.equal(requests[1].captcha,'fixture-answer');assert.equal(requests[1].captcha_id,'fixture-captcha');assert.equal(requests[1].mode,'webvpn');
      assert.equal(await page.locator('#loginSubmitBtn').isEnabled(),true);
    });
    await check('sso-captcha-late-response-cannot-bind-to-another-account',async()=>{
      let release;const hold=new Promise(r=>{release=r;});
      handler=async r=>{await hold;await r.fulfill({json:{status:'captcha_required',mode:'direct',captcha_id:'late',captcha_image:image}});};
      await fill();const n=requests.length;await page.locator('#loginSubmitBtn').click();await page.waitForFunction(n=>loginInFlight,n);
      await page.locator('#loginUsername').fill('fixture-other');release();
      await page.waitForFunction(()=>!loginInFlight);
      assert.equal(requests.length,n+1);assert.equal(await page.locator('#loginCaptchaGroup').isVisible(),false);
      assert.equal(await page.evaluate(()=>appState.currentCaptchaId),'');
    });
    await check('sso-captcha-image-must-be-local-data-and-can-refresh',async()=>{
      handler=r=>r.fulfill({json:{status:'captcha_required',mode:'direct',captcha_id:'fixture-captcha',captcha_image:'https://attacker.test/tracker',message:'验证码暂未加载'}});
      await fill();await page.locator('#loginSubmitBtn').click();await page.waitForFunction(()=>!loginInFlight);
      assert.equal(await page.locator('#loginCaptchaImage').getAttribute('src'),null);
      assert.equal(await page.locator('#loginCaptchaInput').evaluate(el=>el.required),false);
      handler=r=>r.fulfill({json:{status:'captcha_required',mode:'direct',captcha_id:'fresh',captcha_image:image}});
      await page.getByRole('button',{name:'换一张',exact:true}).click();await page.waitForFunction(()=>!loginInFlight);
      assert.equal(await page.evaluate(()=>appState.currentCaptchaId),'fresh');
      await page.locator('#loginUsername').fill('fixture-changed');
      assert.equal(await page.locator('#loginCaptchaGroup').isVisible(),false);
    });
    await check('sso-network-error-releases-submit-and-partial-readiness-is-not-success',async()=>{
      await fill();handler=r=>r.abort();await page.locator('#loginSubmitBtn').click();await page.waitForFunction(()=>!loginInFlight);
      assert.equal(await page.locator('#loginSubmitBtn').isEnabled(),true);assert.equal(await page.locator('#loginModal').isVisible(),true);
      handler=r=>r.fulfill({json:{status:'success',authenticated:true,iclass_ready:false,boya_ready:false}});
      await page.locator('#loginSubmitBtn').click();await page.locator('#loginModal').waitFor({state:'hidden'});
      assert.ok((await page.locator('#toastContainer').innerText()).includes('部分业务尚未就绪'));
    });
  } finally { await context.close(); }
};
