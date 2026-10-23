/* Synthetic browser response timing, without school requests. */
const assert=require('node:assert/strict');
exports.verifyBoyaCache=async(page,check)=>{
  await check('boya-switch-cache-visible-before-slow-status-and-independent-parts',async()=>{
    let release;
    const gate=new Promise(resolve=>release=resolve);
    const pattern='**/api/boya/status*';
    const pending=new Set();
    const handler=route=>{
      const job=(async()=>{const response=await route.fetch();await gate;try{await route.fulfill({response});}catch(error){if(!/already handled|closed|cancelled/.test(error.message))throw error;}})();
      pending.add(job);return job.finally(()=>pending.delete(job));
    };
    await page.route(pattern,handler);
    try {
      await page.locator('#navBtnAccounts').click();
      await page.locator('[data-action="switchAccount"][data-id="fixture-account-2"]').click();
      try{await page.waitForFunction(()=>appState.activeUsername==='fixture-account-2'&&appState.boyaCourses.length===4&&appState.boyaSelected.length===2,{},{timeout:5000});}
      catch(error){throw new Error(error.message+' '+JSON.stringify(await page.evaluate(()=>({user:appState.activeUsername,pool:appState.boyaCourses.length,selected:appState.boyaSelected.length,reads:[...boyaReads.keys()],toast:document.querySelector('#toastContainer')?.textContent}))));}
      assert.equal(await page.locator('#countBoyaAll').textContent(),'4');
      assert.equal(await page.locator('#countBoyaSelected').textContent(),'2');
      assert.equal(await page.evaluate(()=>boyaReads.size>0),true);
    }finally{release();await Promise.all([...pending]);await page.unroute(pattern,handler);}
    await page.waitForFunction(()=>boyaReads.size===0);
  });
  await check('boya-old-account-response-never-replaces-current-cache',async()=>{
    let release,arrived;
    const gate=new Promise(resolve=>release=resolve), started=new Promise(resolve=>arrived=resolve);
    const pattern='**/api/boya/courses*';
    const handler=async route=>{
      if(new URL(route.request().url()).searchParams.get('username')!=='fixture-account-2')return route.continue();
      arrived();await gate;
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({username:'fixture-account-2',status:'success',courses:[{courseName:'LATE OTHER STUDENT',id:9999}]})});
    };
    await page.route(pattern,handler);
    try{
      await page.evaluate(()=>{void fetchBoyaData();});await started;
      await page.locator('#navBtnAccounts').click();
      await page.locator('[data-action="switchAccount"][data-id="fixture-account-1"]').click();
      await page.waitForFunction(()=>appState.activeUsername==='fixture-account-1'&&appState.boyaCourses.length===4);
      release();await page.waitForFunction(()=>boyaReads.size===0);
      assert.equal(await page.evaluate(()=>appState.boyaCourses.some(c=>c.courseName==='LATE OTHER STUDENT')),false);
    }finally{release();await page.unroute(pattern,handler);}
  });
  await check('boya-one-failed-read-retains-its-cache-and-completes-other-parts',async()=>{
    const pattern='**/api/boya/statistics*';
    const before=await page.evaluate(()=>JSON.stringify(appState.boyaStatistics));
    await page.route(pattern,r=>r.fulfill({status:503,contentType:'application/json',body:'{}'}));
    try{
      await page.evaluate(()=>fetchBoyaData());
      assert.equal(await page.evaluate(()=>JSON.stringify(appState.boyaStatistics)),before);
      assert.equal(await page.locator('#countBoyaAll').textContent(),'4');
      assert.match(await page.locator('#boyaHealthText').textContent(),/部分数据/);
    }finally{await page.unroute(pattern);}
    await page.evaluate(()=>fetchBoyaData());
  });
};
