const assert=require('node:assert/strict');
exports.verifyNotice=async function(browser,url,check){
 const context=await browser.newContext({viewport:{width:1440,height:960}});await context.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());const p=await context.newPage();
 try{
  await p.goto(url,{waitUntil:'domcontentloaded'});
  await check('startup-study-warning-red-static-responsive-above-original-emblem',async()=>{
   await p.waitForSelector('#startupStudyNotice',{state:'visible'});
   assert.match(await p.locator('#startupStudyNotice').textContent(),/学号及操作记录可能被留存，滥用记录可能用于调查处理/);
   assert.doesNotMatch(await p.locator('#startupStudyNotice').textContent(),/本机|相关系统/);
   for(const [width,height] of [[1440,960],[960,620],[760,480]]){
    await p.setViewportSize({width,height});const rect=await p.locator('#startupStudyNotice').boundingBox(),emblem=await p.locator('#startupEmblemFlight').boundingBox();
    assert.ok(rect.y>=0&&rect.x>=0&&rect.x+rect.width<=width+1);assert.ok(rect.y+rect.height<emblem.y);
    const style=await p.locator('#startupStudyNotice').evaluate(e=>{const s=getComputedStyle(e);return {color:s.color,opacity:s.opacity,animation:s.animationName,font:parseFloat(s.fontSize),wordmark:document.getElementById('startupSchoolName').getBoundingClientRect().height};});
    assert.equal(style.color,'rgb(255, 57, 57)');assert.equal(style.opacity,'1');assert.equal(style.animation,'none');assert.ok(style.font<=style.wordmark);
   }
  });
  await check('startup-warning-blurs-and-fades-in-sync-with-wordmark-during-flight',async()=>{
   await p.evaluate(()=>{window.noticeSamples=[];const sample=()=>{const s=document.getElementById('startupStage'),n=document.getElementById('startupStudyNotice'),w=document.getElementById('startupSchoolName');if(!s||!n||!w)return;if(s.dataset.phase==='flying')window.noticeSamples.push({opacity:+n.style.opacity,blur:parseFloat(n.style.filter.replace('blur(','')),wordOpacity:+w.style.opacity,wordFilter:w.style.filter,filter:n.style.filter});requestAnimationFrame(sample);};requestAnimationFrame(sample);});
   await p.waitForFunction(()=>document.getElementById('startupStage')?.dataset.phase==='flying',{timeout:12000});
   await p.waitForFunction(()=>!document.getElementById('startupStage'),{timeout:10000});assert.equal(await p.locator('#startupStudyNotice').count(),0);
   const samples=await p.evaluate(()=>noticeSamples);assert.ok(samples.length>=5);assert.ok(samples.some(s=>s.opacity>.8));assert.ok(samples.some(s=>s.opacity>.15&&s.opacity<.75&&s.blur>0));assert.ok(samples.some(s=>s.opacity<.05&&s.blur>18));
   for(let i=0;i<samples.length;i++){const s=samples[i];assert.equal(s.opacity,s.wordOpacity);assert.equal(s.filter,s.wordFilter);if(i){assert.ok(s.opacity<=samples[i-1].opacity);assert.ok(s.blur>=samples[i-1].blur);}}
   assert.equal(await p.evaluate(()=>document.documentElement.dataset.startupResult),'complete');
  });
 }finally{await context.close();}
 for(const resource of ['font','logo'])await check('startup-emblem-reaches-sidebar-while-optional-'+resource+'-remains-pending',async()=>{
  const c=await browser.newContext({viewport:{width:1280,height:840}});let release,heldResource=false;const held=new Promise(r=>{release=r;});
  await c.route('**/*',async r=>{const u=new URL(r.request().url());if((resource==='font'&&u.hostname==='fonts.googleapis.com')||(resource==='logo'&&u.pathname==='/static/images/app_logo.png')){heldResource=true;await held;return r.abort();}if(!['127.0.0.1','localhost'].includes(u.hostname))return r.abort();return r.continue();});
  await c.addInitScript(()=>{window.startupTrace=[];const sample=()=>{const s=document.getElementById('startupStage'),e=document.getElementById('startupEmblemFlight'),i=document.querySelector('.origin-logo-mark');if(s&&e&&i){const a=e.getBoundingClientRect(),b=i.getBoundingClientRect();startupTrace.push({phase:s.dataset.phase,x:a.x+a.width/2,y:a.y+a.height/2,w:a.width,tx:b.x+b.width/2,ty:b.y+b.height/2,tw:Math.min(b.width,b.height)});}if(!s&&startupTrace.length)return;requestAnimationFrame(sample);};requestAnimationFrame(sample);});
  try{const p=await c.newPage();await p.goto(url,{waitUntil:'domcontentloaded'});await p.waitForFunction(()=>!document.getElementById('startupStage'),{timeout:12000});assert.ok(heldResource);assert.equal(await p.evaluate(()=>document.readyState),'interactive');assert.equal(await p.evaluate(()=>document.documentElement.dataset.startupResult),'complete');const trace=await p.evaluate(()=>startupTrace),phases=[...new Set(trace.map(s=>s.phase))];assert.ok(phases.indexOf('drawing')<phases.indexOf('flying'));assert.ok(phases.indexOf('flying')<phases.indexOf('burst'));const flying=trace.filter(s=>s.phase==='flying');assert.ok(flying.length>=5);assert.ok(flying[0].w>150);const end=trace.find(s=>s.phase==='burst');assert.ok(Math.abs(end.x-end.tx)<2&&Math.abs(end.y-end.ty)<2&&Math.abs(end.w-end.tw)<2,'Emblem must actually shrink and land at the sidebar icon');assert.equal(await p.locator('#startupStudyNotice').count(),0);assert.equal(await p.evaluate(()=>document.querySelector('.origin-app-layout').inert),false);}finally{release();await c.close();}
 });
 await check('startup-warning-hidden-ready-restores-without-stale-overlay',async()=>{
  const c=await browser.newContext();await c.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
  try{const p=await c.newPage();await p.goto(url,{waitUntil:'load'});await p.waitForFunction(()=>document.getElementById('startupStage')?.dataset.ready==='true');await p.evaluate(()=>{window.BUAARenderLifecycle={visible:false};dispatchEvent(new Event('buaa:renderstate'));window.noticeHiddenOpacity=document.getElementById('startupStudyNotice').style.opacity;});await p.waitForTimeout(150);assert.equal(await p.locator('#startupStudyNotice').evaluate(e=>e.style.opacity),await p.evaluate(()=>noticeHiddenOpacity));await p.evaluate(()=>{window.BUAARenderLifecycle.visible=true;dispatchEvent(new Event('buaa:renderstate'));});assert.equal(await p.locator('#startupStage').count(),0);assert.equal(await p.evaluate(()=>document.querySelector('.origin-app-layout').inert),false);}finally{await c.close();}
 });
 await check('startup-warning-reduced-motion-cleans-up-without-blocking-interface',async()=>{
  const c=await browser.newContext({reducedMotion:'reduce'});await c.route('**/*',r=>['127.0.0.1','localhost'].includes(new URL(r.request().url()).hostname)?r.continue():r.abort());
  try{const p=await c.newPage();await p.goto(url,{waitUntil:'load'});await p.waitForFunction(()=>!document.getElementById('startupStage'));assert.equal(await p.evaluate(()=>document.documentElement.dataset.startupResult),'reduced-motion');assert.equal(await p.evaluate(()=>document.querySelector('.origin-app-layout').inert),false);}finally{await c.close();}
 });
};
