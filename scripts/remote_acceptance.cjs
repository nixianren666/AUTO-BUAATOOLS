/* Real cookie/password bootstrap; no school accounts, writes or native prompt. */
const assert=require('node:assert/strict'),fs=require('node:fs');
const {chromium}=require('playwright');
(async()=>{
 const [url,executablePath,reportPath]=process.argv.slice(2),checks=[];
 const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
 const context=await browser.newContext({viewport:{width:1000,height:760},reducedMotion:'reduce'});
 const errors=[];let prompts=0,loginPosts=0,writePosts=0;
 const protect=async c=>c.route('**/*',async route=>{
  const r=route.request(),u=new URL(r.url());
  if(!['127.0.0.1','localhost'].includes(u.hostname))return route.abort();
  if(u.pathname==='/api/session'&&r.method()==='POST')loginPosts++;
  if(u.pathname==='/api/logs/clear'&&r.method()==='POST')writePosts++;
  if(u.pathname==='/api/system/updates')return route.fulfill({json:{current_version:'1.4.11',latest_version:'1.4.11',status:'up_to_date',message:'当前已是最新版本'}});
  return route.continue();
 });
 await protect(context);const p=await context.newPage();
 p.on('pageerror',e=>errors.push(e.message));p.on('dialog',async d=>{prompts++;await d.dismiss();});
 const check=async(name,fn)=>{fs.writeFileSync(reportPath,JSON.stringify({passed:false,current:name,checks}));await fn();checks.push(name);};
 const login=async()=>{await p.locator('#managementPassword').fill(process.env.BUAA_ACCEPTANCE_ADMIN);await p.locator('#managementLoginSubmit').click();await p.locator('#managementLoginModal').waitFor({state:'hidden'});};
 try{
  await check('remote-first-use-glass-login-without-native-prompt',async()=>{
   await p.goto(url,{waitUntil:'domcontentloaded'});await p.locator('#managementLoginModal').waitFor({state:'visible'});
   assert.equal(prompts,0);assert.equal(await p.locator('#disclaimerModal').isVisible(),false);
   await p.locator('#managementPassword').fill('synthetic-wrong-password');await p.locator('#managementLoginSubmit').click();
   await p.waitForFunction(()=>document.getElementById('managementLoginStatus').textContent.includes('不正确'));
   assert.equal(await p.locator('#managementPassword').inputValue(),'');
  });
  await check('remote-password-cookie-protects-real-notice-and-accounts',async()=>{
   await login();await p.waitForFunction(()=>appState.accounts.length===2);
   const notice=await context.request.get(new URL('/api/system/disclaimer',url).href);assert.equal(notice.status(),200);assert.ok((await notice.json()).commitment_text.length>60);
   assert.equal(loginPosts,2);assert.equal(await p.locator('#autostartWidget').isVisible(),false);
  });
  await check('refresh-reuses-password-cookie-and-no-repeated-splash',async()=>{
   await p.reload({waitUntil:'domcontentloaded'});await p.waitForFunction(()=>appState.accounts.length===2);
   assert.equal(await p.evaluate(()=>document.documentElement.dataset.startupResult),'already-shown');
   assert.equal(await p.locator('#startupStage').isVisible(),false);assert.equal(loginPosts,2);
   assert.equal(await p.locator('#managementLoginModal').isVisible(),false);
  });
  await check('remote-modules-switch-and-preserve-account-isolation',async()=>{
   await p.locator('#navBtnBoya').click();await p.waitForFunction(()=>appState.currentMainView==='boya');
   await p.locator('#navBtnTD').click();await p.locator('#tdLicenseModal').waitFor({state:'visible'});
   await p.locator('#tdLicenseModal').getByRole('button',{name:'返回常规课堂'}).click();
   await p.evaluate(()=>switchStudentAccount('fixture-account-2'));await p.waitForFunction(()=>appState.activeUsername==='fixture-account-2');
   await p.evaluate(()=>switchMainView('logs'));assert.equal(await p.evaluate(()=>appState.activeUsername),'fixture-account-2');
  });
  await check('parallel-expired-reads-require-one-login-and-retry-reads-only',async()=>{
   await context.clearCookies();
   await p.evaluate(()=>{window.remoteReads=Promise.all([apiFetch('/api/status'),apiFetch('/api/config'),apiFetch('/api/accounts')]).then(rs=>rs.every(r=>r.ok));});
   await p.locator('#managementLoginModal').waitFor({state:'visible'});await login();assert.equal(await p.evaluate(()=>remoteReads),true);assert.equal(loginPosts,3);
  });
  await check('expired-write-is-never-replayed-after-management-login',async()=>{
   await context.clearCookies();await p.evaluate(()=>{window.remoteWrite=apiFetch('/api/logs/clear?username=fixture-account-1',{method:'POST'}).then(()=>'',e=>e.message);});
   await p.locator('#managementLoginModal').waitFor({state:'visible'});assert.match(await p.evaluate(()=>remoteWrite),/没有自动重复提交/);
   await login();assert.equal(writePosts,1);assert.equal(loginPosts,4);
  });
  await check('server-autostart-rejected-without-changing-host-or-service',async()=>{
   const csrf=(await(await context.request.get(new URL('/api/session',url).href)).json()).csrf;
   const r=await context.request.post(new URL('/api/system/autostart',url).href,{headers:{'X-BUAA-CSRF':csrf},data:{enabled:true}});assert.equal(r.status(),409);
   assert.equal((await context.request.get(new URL('/api/health',url).href)).status(),200);
  });
  await check('new-tab-and-unavailable-browser-storage-do-not-replay-startup',async()=>{
   const tab=await context.newPage();await tab.addInitScript(()=>{Object.defineProperty(window,'localStorage',{get(){throw new Error('synthetic-disabled-storage')}});});
   await tab.goto(url,{waitUntil:'domcontentloaded'});await tab.waitForFunction(()=>appState.accounts.length===2);
   assert.equal(await tab.evaluate(()=>document.documentElement.dataset.startupResult),'already-shown');assert.equal(loginPosts,4);await tab.close();
  });
  await check('offline-bootstrap-can-reconnect-with-cookie-without-password-post',async()=>{
   let failed=false;const c=await browser.newContext({storageState:await context.storageState(),reducedMotion:'reduce'});await protect(c);
   await c.route('**/api/session',r=>{if(!failed&&r.request().method()==='GET'){failed=true;return r.abort();}return r.fallback();});
   const tab=await c.newPage();await tab.goto(url,{waitUntil:'domcontentloaded'});await tab.locator('#managementLoginSubmit').waitFor({state:'visible'});
   assert.equal(await tab.locator('#managementLoginSubmit').textContent(),'重新连接');await tab.locator('#managementLoginSubmit').click();
   await tab.waitForFunction(()=>appState.accounts.length===2);assert.equal(loginPosts,4);await c.close();
  });
  await check('server-exit-logs-out-browser-without-stopping-background',async()=>{
   p.removeAllListeners('dialog');p.on('dialog',d=>d.accept());
   await p.locator('[onclick="requestAppExit()"]').click();await p.waitForURL('about:blank');
   assert.equal((await context.request.get(new URL('/api/health',url).href)).status(),200);
   assert.equal((await context.request.get(new URL('/api/accounts',url).href)).status(),401);
  });
  assert.deepEqual(errors,[]);fs.writeFileSync(reportPath,JSON.stringify({passed:true,checks,native_prompts:prompts,script_errors:errors,school_writes:0},null,2));
 }catch(e){fs.writeFileSync(reportPath,JSON.stringify({passed:false,checks,error:e.message,stack:e.stack,script_errors:errors},null,2));throw e;}
 finally{await context.close();await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
