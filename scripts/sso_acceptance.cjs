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
    await check('sms-requires-explicit-send-and-does-not-include-saved-password', async () => {
      await fill();
      await page.locator('#loginUsername').fill('00000001');
      await page.locator('#loginMethod').selectOption('sms', {force:true});
      const start = requests.length;
      await page.locator('#loginSubmitBtn').click();
      assert.equal(requests.length, start);
      handler = route => route.fulfill({json:{status:'sms_sent', sms_challenge:'fixture-sms', expires_in:180}});
      await page.locator('#loginSmsSend').click();
      await page.waitForFunction(() => !loginInFlight && loginSmsChallenge === 'fixture-sms');
      assert.equal(requests[start].sms_action, 'send');
      assert.equal(requests[start].password, undefined);
      assert.equal(await page.locator('#loginSmsSend').isDisabled(), true);
      handler = route => route.fulfill({json:{status:'success',authenticated:true,iclass_ready:true,boya_ready:true}});
      await page.locator('#loginSmsCode').fill('010203');
      await page.locator('#loginSubmitBtn').click();
      await page.locator('#loginModal').waitFor({state:'hidden'});
      assert.equal(requests[start + 1].sms_code, '010203');
      assert.equal(requests[start + 1].sms_challenge, 'fixture-sms');
      assert.equal(requests[start + 1].password, undefined);
      assert.equal(await page.locator('#loginSmsCode').inputValue(), '');
    });
    await check('conditional-sms-shows-official-verification-without-triggering-send', async () => {
      await page.evaluate(() => openLoginModal());
      await page.locator('#loginMethod').selectOption('password', {force:true});
      await fill();
      const start = requests.length;
      handler = route => route.fulfill({json:{status:'sms_required', mode:'webvpn'}});
      await page.locator('#loginSubmitBtn').click();
      await page.locator('#loginVerificationHelp').waitFor({state:'visible'});
      assert.equal(requests.length, start + 1);
      assert.equal(requests[start].sms_action, undefined);
      assert.equal(await page.locator('#loginVerificationHelp a').getAttribute('href'), 'https://sso.buaa.edu.cn/login');
      await page.locator('#loginUseSms').click();
      assert.equal(await page.locator('#loginMethod').inputValue(), 'sms');
      assert.equal(await page.locator('#loginPassword').inputValue(), '');
      assert.equal(requests.length, start + 1);
      handler = route => route.fulfill({json:{status:'sms_sent', sms_challenge:'fixture-sms-from-prompt', expires_in:180}});
      await page.locator('#loginSmsSend').click();
      await page.waitForFunction(() => !loginInFlight && loginSmsChallenge === 'fixture-sms-from-prompt');
      assert.equal(requests.length, start + 2);
      assert.equal(requests[start + 1].sms_action, 'send');
      assert.equal(requests[start + 1].mode, 'webvpn');
      assert.equal(requests[start + 1].password, undefined);
    });
  } finally { await context.close(); }
};
