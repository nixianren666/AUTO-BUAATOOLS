const assert=require('node:assert/strict');
exports.verify=async(page,browser,url,check)=>{
 const selector='[data-action="regularAutoPolicy"][data-id="1001"]';
 const wait=async paused=>page.waitForFunction(({id,paused})=>{const b=document.querySelector(`[data-action="regularAutoPolicy"][data-id="${id}"]`);return b&&!b.disabled&&b.getAttribute('aria-pressed')===String(paused);},{id:'1001',paused});
 const select=async n=>{await page.evaluate(n=>switchStudentAccount('fixture-account-'+n),n);await page.waitForFunction(n=>appState.activeUsername==='fixture-account-'+n&&document.querySelector(`[data-action="regularAutoPolicy"][data-id="100${n}"]`),n);};
 const refresh=async()=>page.evaluate(async()=>{const d=await(await apiFetch('/api/classes/auto-policy')).json();appState.classes=d.classes;renderClassesList(d.classes);});
 await page.waitForSelector(selector);
 await check('regular-course-pause-is-semester-scoped-and-keeps-manual-action',async()=>{
  await page.locator(selector).click();await wait(true);
  assert.match(await page.locator('.regular-policy-caption').first().textContent(),/本学期/);
  assert.equal(await page.locator('[data-action="regularSign"][data-id="1001"]').isDisabled(),false);
  const state=await page.evaluate(async()=>(await apiFetch('/api/classes/auto-policy')).json());assert.equal(state.username,'fixture-account-1');assert.equal(state.classes[0].auto_course.paused,true);
 });
 await check('regular-course-pause-survives-page-reload',async()=>{
  await page.reload({waitUntil:'networkidle'});await wait(true);
  await page.evaluate(()=>{if(window.__acceptanceViewPoll)clearInterval(__acceptanceViewPoll.id);});
  await page.locator(selector).focus();await page.locator(selector).press('Enter');await wait(false);
 });
 await check('regular-course-setting-does-not-cross-students-with-same-subject-id',async()=>{
  await page.locator(selector).click();await wait(true);await select(2);
  assert.equal(await page.locator('[data-action="regularAutoPolicy"][data-id="1002"]').getAttribute('aria-pressed'),'false');
  await select(1);await wait(true);await page.locator(selector).click();await wait(false);
 });
 await check('regular-course-policy-repeat-click-is-one-owned-request',async()=>{
  let release;const held=new Promise(r=>release=r);const requests=[];
  const route=async r=>{if(r.request().method()!=='POST')return r.continue();requests.push(r.request().postDataJSON());await held;const response=await r.fetch();await r.fulfill({response});};
  await page.route('**/api/classes/auto-policy**',route);
  try{
   await page.locator(selector).click();await page.evaluate(()=>void toggleRegularCoursePolicy('1001'));
   await page.waitForTimeout(80);assert.equal(requests.length,1);assert.equal(requests[0].username,'fixture-account-1');assert.equal(requests[0].paused,true);
   assert.equal(await page.locator(selector).isDisabled(),true);release();await wait(true);
  }finally{release();await page.unroute('**/api/classes/auto-policy**',route);}
  await page.locator(selector).click();await wait(false);
 });
 await check('regular-course-policy-storage-failure-shows-paused-failsafe',async()=>{
  const classes=await page.evaluate(()=>appState.classes.map(c=>({...c,auto_course:{...c.auto_course,paused:true,storage_error:true}})));
  const failed=async r=>r.request().method()==='POST'?r.fulfill({status:503,json:{detail:'synthetic policy storage failure; paused in this process',username:'fixture-account-1',classes}}):r.continue();
  await page.route('**/api/classes/auto-policy**',failed);
  try{
   await page.locator(selector).click();await wait(true);assert.match(await page.locator('.regular-policy-caption').first().textContent(),/存储异常/);
   await page.locator(selector).click();await wait(true); // failed resume retains pause
  }finally{await page.unroute('**/api/classes/auto-policy**',failed);await refresh();await wait(false);}
 });
 await check('regular-course-pending-return-to-owner-releases-control-without-stale-write',async()=>{
  let release;const held=new Promise(r=>release=r);let writes=0;
  const route=async r=>{if(r.request().method()!=='POST')return r.continue();writes++;assert.equal(r.request().postDataJSON().username,'fixture-account-1');await held;const response=await r.fetch();await r.fulfill({response});};
  await page.route('**/api/classes/auto-policy**',route);
  try{
   await page.locator(selector).click();await select(2);await select(1);
   release();await wait(true);assert.equal(writes,1);await select(2);
   assert.equal(await page.locator('[data-action="regularAutoPolicy"][data-id="1002"]').getAttribute('aria-pressed'),'false');
  }finally{release();await page.unroute('**/api/classes/auto-policy**',route);await select(1);await refresh();}
  await wait(true);await page.locator(selector).click();await wait(false);
 });
 await check('regular-course-control-phone-touch-and-short-width-fit',async()=>{
  const context=await browser.newContext({storageState:await page.context().storageState(),viewport:{width:320,height:568},screen:{width:320,height:568},isMobile:true,hasTouch:true,userAgent:'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'});
  try{
   await context.route('**/*',r=>new URL(r.request().url()).host===new URL(url).host?r.continue():r.abort());
   const p=await context.newPage();await p.goto(url,{waitUntil:'networkidle'});await p.waitForSelector(selector);
   for(const viewport of [{width:320,height:568},{width:390,height:844},{width:844,height:390}]){
    await p.setViewportSize(viewport);const rect=await p.locator(selector).boundingBox();assert.ok(rect.height>=44);assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   }
   await p.setViewportSize({width:320,height:568});await p.locator(selector).tap();await p.waitForFunction(()=>document.querySelector('[data-action="regularAutoPolicy"]').getAttribute('aria-pressed')==='true'&&!document.querySelector('[data-action="regularAutoPolicy"]').disabled);
   assert.equal(await p.locator('[data-action="regularSign"]').isDisabled(),false);await p.locator(selector).tap();await p.waitForFunction(()=>document.querySelector('[data-action="regularAutoPolicy"]').getAttribute('aria-pressed')==='false'&&!document.querySelector('[data-action="regularAutoPolicy"]').disabled);
  }finally{await context.close();await refresh();}
 });
 await check('permanent-boya-series-badge-keeps-explicit-manual-selection',async()=>{
  const saved=await page.evaluate(()=>({courses:appState.boyaCourses,selected:appState.boyaSelected,tab:appState.boyaTab,category:appState.boyaCategoryFilter,only:appState.boyaAutoSignOnly,available:appState.boyaAvailableOnly}));
  try{
   await page.evaluate(()=>{const stamp=n=>new Date(Date.now()+n*60000).toISOString();Object.assign(appState,{boyaTab:'all',boyaCategoryFilter:'全部',boyaAutoSignOnly:false,boyaAvailableOnly:false,boyaCourses:[{id:9091,courseId:9091,courseName:'《“耕趣农场”劳动课》系列课程',courseKind:'劳育',category_key:'劳育',courseCurrentCount:0,courseMaxCount:10,capacity_current:0,capacity_maximum:10,capacity_available:true,autonomous_config_valid:true,automatic_selection_excluded:true,courseSelectStartDate:stamp(-10),courseSelectEndDate:stamp(60),courseStartDate:stamp(120),courseEndDate:stamp(180)}],boyaSelected:[]});renderBoyaFeed();});
   assert.match(await page.locator('#boyaCoursesFeed').textContent(),/永久不自动抢选/);assert.equal(await page.locator('[data-action="select"][data-id="9091"]').count(),1);
  }finally{await page.evaluate(s=>{Object.assign(appState,{boyaCourses:s.courses,boyaSelected:s.selected,boyaTab:s.tab,boyaCategoryFilter:s.category,boyaAutoSignOnly:s.only,boyaAvailableOnly:s.available});renderBoyaFeed();},saved);}
 });
};
