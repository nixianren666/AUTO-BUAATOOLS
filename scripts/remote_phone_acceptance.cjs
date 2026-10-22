/* Real browser emulation of phone layout. Only synthetic local accounts/media;
   this is not a physical iPhone, iPad or Mac/VPN connectivity claim. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1';
const android = 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 Chrome/140.0.0.0 Mobile Safari/537.36';
const protect = c => c.route('**/*',r => ['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname) ? r.continue() : r.abort());
async function fits(page, selector) {
  const result=await page.locator(selector).evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,scroll:el.scrollWidth,client:el.clientWidth,viewport:innerWidth};});
  assert.ok(result.x>=-1 && result.x+result.width<=result.viewport+1,selector+' bounds '+JSON.stringify(result));
  assert.ok(result.scroll<=result.client+2,selector+' overflow '+JSON.stringify(result));
}
exports.verifyRemotePhone=async(browser,url,check)=>{
  const context=await browser.newContext({viewport:{width:390,height:844},screen:{width:390,height:844},isMobile:true,hasTouch:true,userAgent:iphone,reducedMotion:'reduce'});
  await protect(context);const page=await context.newPage(),errors=[],writes=[];
  // Playwright setViewportSize also changes screen size. A real phone's screen
  // does not shrink when its software keyboard changes the visual viewport.
  await page.addInitScript(()=>Object.defineProperties(screen,{width:{get:()=>390},height:{get:()=>844}}));
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()!=='GET'&&new URL(r.url()).pathname.startsWith('/api/'))writes.push({url:r.url(),method:r.method(),body:r.postData()});});
  const navigate=async(id)=>{await page.locator('#remotePhoneMenuBtn').click();await page.locator('#'+id).click();};
  const capture=async(name)=>{if(process.env.BUAA_TEST_REPORT_DIR){const dir=path.join(process.env.BUAA_TEST_REPORT_DIR,'phone-screenshots');fs.mkdirSync(dir,{recursive:true});if(!await page.locator('.origin-modal-backdrop:not(.hidden)').count())await page.locator('#mainContentScroll').evaluate(e=>e.scrollTop=0);await page.screenshot({path:path.join(dir,name+'.png')});}};
  try {
    await page.goto(url,{waitUntil:'networkidle'});await page.waitForFunction(()=>appState.accounts.length===2);
    await check('phone-headless-classification-and-device-boundaries',async()=>{
      assert.equal(await page.evaluate(()=>document.documentElement.hasAttribute('data-remote-phone')),true);
      const table=await page.evaluate(({iphone,android})=>{
        const base={mode:'headless',ua:iphone,platform:'iPhone',touch:5,coarse:true,screenWidth:390,screenHeight:844,width:390};
        return [
          [{},true], [{width:844},true], [{screenWidth:320,screenHeight:568,width:320},true],
          [{ua:android,platform:'Linux armv8l'},true],
          [{mode:'desktop'},false],[{touch:0},false],[{coarse:false},false],[{width:1025},false],
          [{screenWidth:600,screenHeight:960,width:390},false],
          [{ua:'Mozilla/5.0 (iPad; CPU OS 18) Mobile',screenWidth:768,screenHeight:1024},false],
          [{ua:'Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari',platform:'MacIntel'},false],
          [{ua:'Mozilla/5.0 (Linux; Android 15) Chrome Safari',platform:'Linux armv8l'},false],
          [{ua:'Mozilla/5.0 (Windows NT 10.0) Chrome',platform:'Win32'},false],
          [{screenWidth:700,screenHeight:900},false],[{ua:'unknown'},false]
        ].map(([patch,expected])=>({patch,expected,actual:BUAARemotePhone.classify({...base,...patch})}));
      },{iphone,android});
      for(const row of table)assert.equal(row.actual,row.expected,JSON.stringify(row.patch));
    });
    await check('phone-regular-320-390-430-portrait-and-landscape-fit',async()=>{
      for(const [width,height] of [[320,568],[390,844],[430,932],[844,390]]) {
        await page.setViewportSize({width,height});
        for(const selector of ['.origin-topbar','#viewRegular','.hero-metrics-strip','#classesFeed'])await fits(page,selector);
        assert.equal(await page.evaluate(()=>document.body.scrollWidth<=innerWidth+2),true);
        assert.ok(await page.locator('#remotePhoneMenuBtn').isVisible());
      }
      await page.setViewportSize({width:390,height:844});await capture('regular-portrait');
    });
    await check('phone-original-menu-labels-focus-backdrop-and-no-requests',async()=>{
      const before=writes.length;await page.locator('#remotePhoneMenuBtn').click();
      for(const id of ['navBtnRegular','navBtnBoya','navBtnTD','navBtnAccounts','navBtnLogs','modeText'])assert.equal(await page.locator('#'+id).isVisible(),true);
      assert.equal(await page.locator('.origin-main').evaluate(e=>e.inert),true);
      await page.keyboard.press('Shift+Tab');assert.equal(await page.evaluate(()=>document.querySelector('.origin-sidebar').contains(document.activeElement)),true);
      await page.keyboard.press('Escape');assert.equal(await page.locator('#remotePhoneMenuBtn').getAttribute('aria-expanded'),'false');
      assert.equal(await page.locator('.origin-main').evaluate(e=>e.inert),false);
      await page.locator('#remotePhoneMenuBtn').click();await page.locator('.remote-phone-shade').click({position:{x:380,y:200}});
      assert.equal(await page.locator('#remotePhoneMenuBtn').getAttribute('aria-expanded'),'false');assert.equal(writes.length,before);
    });
    await check('phone-boya-search-tabs-and-filters-retain-semantics',async()=>{
      await navigate('navBtnBoya');await page.waitForFunction(()=>appState.boyaCourses.length>0);
      assert.equal(await page.locator('.remote-phone-section-label').textContent(),'自动博雅套件');
      for(const width of [320,390,844]) {
        await page.setViewportSize({width,height:width===844?390:844});
        for(const selector of ['#viewBoya','#viewBoya .boya-controls-group','.boya-milestone-pills','.boya-toolbar','#boyaFilterMatrix','#boyaCoursesFeed'])await fits(page,selector);
      }
      await page.setViewportSize({width:390,height:844});await page.locator('#boyaSearchInput').fill('synthetic-unmatched');
      assert.equal(await page.locator('#boyaCoursesFeed .feed-card').count(),0);
      await page.locator('#boyaSearchInput').fill('');await page.locator('#tabBoyaSelected').click();
      assert.equal(await page.locator('#boyaFilterMatrix').isVisible(),false);
      assert.equal(await page.locator('#selectedTimeFilterStrip').isVisible(),true);
      await capture('boya-portrait');
    });
    await check('phone-accounts-login-and-manual-dialog-actions-reachable',async()=>{
      await navigate('navBtnAccounts');await fits(page,'#accountCardsModal .origin-modal-dialog');
      await page.keyboard.press('Escape');await page.evaluate(()=>openLoginModal());
      for(const [width,height] of [[390,844],[844,390],[390,350]]) {
        await page.setViewportSize({width,height});
        try { await page.waitForFunction(()=>Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--phone-visual-height'))-visualViewport.height)<2,{},{timeout:3000}); }
        catch(error) {throw new Error('Phone visual viewport '+JSON.stringify(await page.evaluate(()=>({width:innerWidth,screen:[screen.width,screen.height],visual:[visualViewport.width,visualViewport.height],style:document.documentElement.getAttribute('style'),active:document.documentElement.hasAttribute('data-remote-phone'),hidden:document.hidden,overflow:[...document.querySelectorAll('body *')].filter(e=>e.getClientRects().length&&e.getBoundingClientRect().right>innerWidth+2).map(e=>e.id||e.className).slice(0,12)}))));}
        await fits(page,'#loginModal .origin-modal-dialog');
        const r=await page.locator('#loginModal .modal-footer').boundingBox();assert.ok(r.y+r.height<=height+1);
        assert.equal(await page.locator('#loginUsername').evaluate(e=>getComputedStyle(e).fontSize),'16px');
      }
      await page.setViewportSize({width:390,height:844});await capture('login-portrait');
      await page.keyboard.press('Escape');await page.evaluate(()=>openManualSignModal());await fits(page,'#manualSignModal .origin-modal-dialog');
      await page.keyboard.press('Escape');
    });
    const active={active:true,expires_at:'2099-12-31T23:59:59+08:00',expires_epoch:4102444799};
    let licenseAllowed=false,phase='idle',queued=false;
    await page.route('**/api/td/license/status?**',r=>r.fulfill({json:{license:licenseAllowed?active:{active:false,reason:'合成未激活'}}}));
    await page.route('**/api/td/status?**',async r=>{
      const response=await r.fetch(),state=await response.json();
      await r.fulfill({response,json:{...state,license:active,rules_valid:true,within_window:true,server_time:new Date().toISOString(),
        batch:{allowed:!queued,active:queued,mode:'manual',start_before:Date.now()/1000+3600},
        task:{...state.task,state:phase,due:Date.now()/1000+180},
        settings:{...state.settings,confirmed:true},
        images:[{id:'phone-entry',name:'synthetic'},{id:'phone-exit',name:'synthetic'}],
        groups:[{id:'phone-pair',entry_image:'phone-entry',exit_image:'phone-exit',name:'合成照片组',in_use:queued}]}});
    });
    await page.route('**/api/td/images/**',r=>r.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="160"><rect width="120" height="160" fill="#34556f"/></svg>'}));
    await page.route('**/api/td/batch?**',r=>{queued=true;phase='waiting_exit';return r.fulfill({json:{status:'ok',queued:true}});});
    await check('phone-td-locked-gate-remains-locked-and-can-return',async()=>{
      await navigate('navBtnTD');await page.locator('#tdLicenseBack').waitFor({state:'visible'});
      await fits(page,'#tdLicenseModal .origin-modal-dialog');
      await page.keyboard.press('Escape');assert.equal(await page.locator('#tdLicenseModal').isVisible(),true);
      assert.equal(await page.locator('#viewTD').isVisible(),false);
      await page.locator('#tdLicenseBack').click();
      assert.equal(await page.evaluate(()=>appState.currentMainView),'regular');
    });
    await check('phone-td-rules-calendar-gallery-and-photo-editor-fit',async()=>{
      licenseAllowed=true;await navigate('navBtnTD');await page.waitForFunction(()=>!document.getElementById('tdSettingsBtn').disabled);
      await page.locator('#tdSettingsBtn').click();await fits(page,'#tdSettingsModal .origin-modal-dialog');
      await page.locator('#tdStart + .td-date-trigger').click();await fits(page,'.td-calendar');
      await page.keyboard.press('Escape');await page.keyboard.press('Escape');
      await page.locator('#tdDropzone').click();await fits(page,'#tdGroupModal .origin-modal-dialog');
      await fits(page,'.td-group-editor');await page.keyboard.press('Escape');
      if(!await page.locator('#tdLibrary').evaluate(e=>e.open))await page.locator('#tdLibrary summary').click();
      await page.locator('#tdGallery .td-photo').waitFor({state:'visible'});
      await fits(page,'#tdGallery');await fits(page,'#tdGallery .td-photo');await capture('td-portrait');
    });
    await check('phone-td-once-confirmed-request-keeps-account-csrf-and-grey-state',async()=>{
      await page.locator('#tdManualBtn').click();await fits(page,'#tdManualModal .origin-modal-dialog');
      await page.locator('#tdManualConfirmed').check();await page.locator('#tdManualSave').click();
      await page.waitForFunction(()=>document.getElementById('tdManualBtn').disabled&&document.getElementById('tdTaskText').textContent.includes('等待出口'));
      const posted=writes.filter(r=>new URL(r.url).pathname==='/api/td/batch');assert.equal(posted.length,1);
      assert.equal(JSON.parse(posted[0].body).confirmed,true);
      assert.equal(new URL(posted[0].url).searchParams.get('username'),await page.evaluate(()=>appState.activeUsername));
      for(const selector of ['.td-controls','#tdActionToolbar','.td-task-strip'])await fits(page,selector);
      assert.equal(await page.locator('#tdBatchStopBtn').isVisible(),true);
      const status=await page.locator('.td-task-strip').boundingBox(),progress=await page.locator('.td-progress-grid').boundingBox();
      assert.ok(status.y<progress.y,'Live task state precedes progress on a phone');
      assert.equal(await page.locator('#tdActionToolbar').evaluate(e=>e.parentElement.classList.contains('td-hero')),true);
      const hit=await page.locator('#tdAutoToggle').boundingBox();assert.ok(hit.width>=44&&hit.height>=44);
      assert.doesNotMatch(await page.locator('#tdTaskAnnouncement').textContent(),/剩余 \d+ 秒/);
      await page.locator('#mainContentScroll').evaluate(e=>e.scrollTop=0);await capture('td-queue-portrait');
      await page.setViewportSize({width:1200,height:840});
      await page.waitForFunction(()=>!document.documentElement.hasAttribute('data-remote-phone'));
      assert.equal(await page.locator('#tdActionToolbar').evaluate(e=>e.parentElement.id),'viewTD');
      await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.documentElement.hasAttribute('data-remote-phone'));
    });
    await check('phone-logs-glass-update-and-rotation-keep-controls-available',async()=>{
      await navigate('navBtnLogs');await fits(page,'#viewLogs');await fits(page,'.terminal-header');
      await page.locator('#glassControlBtn').click();await fits(page,'#glassPopover');
      await page.locator('#updateCheckBtn').click();await fits(page,'#updatePanel');
      await page.locator('#updateCloseBtn').click();
      await page.setViewportSize({width:844,height:390});await page.locator('#remotePhoneMenuBtn').click();
      await fits(page,'.origin-sidebar');await page.locator('#remotePhoneMenuClose').click();
      assert.equal(await page.locator('.origin-main').evaluate(e=>e.inert),false);
      assert.deepEqual(errors,[]);
      assert.equal(writes.filter(r=>!new URL(r.url).pathname.startsWith('/api/td/batch')).length,0,'Layout/navigation must never send a mutation');
    });
  } finally { await context.close(); }
  await check('phone-actual-desktop-tablet-and-native-contexts-stay-normal',async()=>{
    const cases=[
      {viewport:{width:390,height:844},screen:{width:1440,height:900},hasTouch:false},
      {viewport:{width:390,height:844},screen:{width:768,height:1024},hasTouch:true,isMobile:true,userAgent:'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) Mobile Safari'},
      {viewport:{width:390,height:844},screen:{width:800,height:1280},hasTouch:true,isMobile:true,userAgent:'Mozilla/5.0 (Linux; Android 15) Chrome Safari'},
      {viewport:{width:390,height:844},screen:{width:390,height:844},hasTouch:true,isMobile:true,userAgent:iphone,native:true},
      {viewport:{width:390,height:844},screen:{width:390,height:844},hasTouch:true,isMobile:true,userAgent:android}
    ];
    for(const options of cases){
      const {native,...settings}=options,c=await browser.newContext({...settings,reducedMotion:'reduce'});await protect(c);
      if(native)await c.route('**/',async r=>{const response=await r.fetch();await r.fulfill({response,body:(await response.text()).replace('data-runtime-mode="headless"','data-runtime-mode="desktop"')});});
      try{const p=await c.newPage();await p.goto(url,{waitUntil:'networkidle'});
        const expected=options.userAgent===android;
        assert.equal(await p.evaluate(()=>document.documentElement.hasAttribute('data-remote-phone')),expected,JSON.stringify(options));
        assert.equal(await p.locator('.origin-sidebar').evaluate(e=>e.inert),expected);
      }finally{await c.close();}
    }
  });
  await check('phone-desktop-and-tablet-geometry-equals-unadapted-page',async()=>{
    for(const [width,height,touch] of [[1280,840,false],[768,1024,true],[390,844,false]]){
      const c=await browser.newContext({viewport:{width,height},screen:{width:touch?768:1440,height:touch?1024:900},hasTouch:touch,reducedMotion:'reduce'});await protect(c);
      const measure=p=>p.evaluate(()=>['.origin-sidebar','.origin-main','.origin-topbar','#mainContentScroll','.hero-card','.hero-metrics-strip','#classesFeed','#navBtnBoya'].map(selector=>{
        const e=document.querySelector(selector),r=e.getBoundingClientRect(),s=getComputedStyle(e);
        return {selector,x:r.x,y:r.y,width:r.width,height:r.height,display:s.display,padding:s.padding,font:s.fontSize};
      }));
      try{
        const p=await c.newPage();await p.goto(url,{waitUntil:'networkidle'});await p.waitForFunction(()=>appState.accounts.length===2&&appState.classes.length>0);const adapted=await measure(p);
        await c.route('**/static/**/remote-phone.*',r=>r.abort());
        await p.reload({waitUntil:'networkidle'});await p.waitForFunction(()=>appState.accounts.length===2&&appState.classes.length>0);
        assert.deepEqual(await measure(p),adapted,`Unchanged computer layout ${width}x${height}`);
      }finally{await c.close();}
    }
  });
  await check('phone-startup-preserves-timeline-and-lands-on-visible-header-logo',async()=>{
    const c=await browser.newContext({viewport:{width:390,height:844},screen:{width:390,height:844},isMobile:true,hasTouch:true,userAgent:iphone});await protect(c);
    await c.route('**/',async r=>{const response=await r.fetch();await r.fulfill({response,body:(await response.text()).replace('data-startup-enabled="false"','data-startup-enabled="true"')});});
    try{
      const p=await c.newPage(),now=Date.now();await p.clock.install({time:now});await p.clock.pauseAt(now+100);
      await p.goto(url,{waitUntil:'domcontentloaded'});await p.clock.runFor(5400);
      const sample=await p.evaluate(()=>{
        const logo=document.querySelector('.remote-phone-logo').getBoundingClientRect(),emblem=document.getElementById('startupEmblemFlight').getBoundingClientRect();
        return {phase:document.getElementById('startupStage').dataset.phase,logo:{x:logo.x,y:logo.y},emblem:{x:emblem.x,y:emblem.y}};
      });
      assert.equal(sample.phase,'flying');assert.ok(sample.logo.x>=0&&sample.logo.y>=0);
      assert.ok(sample.emblem.x<195&&sample.emblem.y<422,'Emblem flies toward the visible phone header');
      await p.clock.runFor(2000);assert.equal(await p.evaluate(()=>document.documentElement.dataset.startupResult),'complete');
    }finally{await c.close();}
  });
};

exports.verifyPhoneManagement=async(browser,url,password,check)=>{
  const context=await browser.newContext({viewport:{width:390,height:844},screen:{width:390,height:844},isMobile:true,hasTouch:true,userAgent:iphone,reducedMotion:'reduce'});
  await protect(context);const page=await context.newPage();let acceptPosts=0;
  await page.addInitScript(()=>Object.defineProperties(screen,{width:{get:()=>390},height:{get:()=>844}}));
  await page.route('**/api/system/disclaimer',async route=>{
    if(route.request().method()!=='GET'){acceptPosts++;return route.abort();}
    const response=await route.fetch();if(!response.ok())return route.fulfill({response});
    await route.fulfill({response,json:{...await response.json(),accepted:false}});
  });
  try{
    await check('phone-password-management-real-cookie-and-reachable-login',async()=>{
      assert.equal((await context.request.get(new URL('/api/accounts',url).href)).status(),401);
      await page.goto(url,{waitUntil:'domcontentloaded'});await page.locator('#managementLoginSubmit').waitFor({state:'visible'});
      await fits(page,'#managementLoginModal .origin-modal-dialog');
      assert.equal(await page.locator('#disclaimerModal').isVisible(),false);
      await page.locator('#managementPassword').fill(password);await page.locator('#managementLoginSubmit').click();
      await page.locator('#managementLoginModal').waitFor({state:'hidden'});
      assert.equal((await context.request.get(new URL('/api/accounts',url).href)).status(),200);
    });
    await check('phone-first-use-terms-scroll-portrait-landscape-keyboard-no-signing',async()=>{
      await page.locator('#disclaimerModal').waitFor({state:'visible'});
      for(const [width,height] of [[320,568],[390,350],[844,390]]){
        await page.setViewportSize({width,height});
        await page.waitForFunction(()=>Math.abs(parseFloat(document.documentElement.style.getPropertyValue('--phone-visual-height'))-visualViewport.height)<2);
        await fits(page,'#disclaimerModal .origin-modal-dialog');
        const footer=await page.locator('#disclaimerModal .modal-footer').boundingBox();assert.ok(footer.y+footer.height<=height+1);
        await page.locator('#disclaimerCommitmentInput').scrollIntoViewIfNeeded();
        assert.equal(await page.locator('#disclaimerAgreeBtn').isDisabled(),true);
      }
      await page.keyboard.press('Escape');assert.equal(await page.locator('#disclaimerModal').isVisible(),true);assert.equal(acceptPosts,0);
    });
    await check('phone-remote-reload-reuses-cookie-without-replaying-service-startup',async()=>{
      await page.reload({waitUntil:'networkidle'});await page.locator('#disclaimerModal').waitFor({state:'visible'});
      assert.equal(await page.locator('#managementLoginModal').isVisible(),false);
      assert.equal(await page.evaluate(()=>document.documentElement.dataset.startupResult),'already-shown');assert.equal(acceptPosts,0);
    });
  }finally{await context.close();}
};
