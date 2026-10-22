/* Synthetic TD UI integration, using real local media/settings APIs. */
const assert = require('node:assert/strict');
exports.verifyTD = async function(page, check) {
  const expectedUser = await page.evaluate(() => appState.activeUsername);
  await require('./td_gate_acceptance.cjs').verifyTDGate(page, check);
  const license = {active:true,expires_at:'2099-12-31T23:59:59+08:00',expires_epoch:4102444799,reason:''};
  const entranceLicense = r => r.fulfill({json:{license}});
  const presentationLicense = async r => {const response=await r.fetch();const state=await response.json();await r.fulfill({response,json:{...state,license}});};
  await page.route('**/api/td/license/status?**',entranceLicense);
  await page.route('**/api/td/status?**',presentationLicense);
  const startDate = new Date(Date.now() - 30*86400000).toISOString().slice(0,10);
  const endDate = new Date(Date.now() + 30*86400000).toISOString().slice(0,10);
  const network = [];
  const listener = request => { if (new URL(request.url()).pathname.startsWith('/api/td/')) network.push({url:request.url(),method:request.method(),body:request.postData()}); };
  page.on('request',listener);
  await check('td-navigation-account-and-unknown-progress',async () => {
    await page.locator('#navBtnTD').click();
    await page.waitForFunction(() => !document.getElementById('tdSettingsBtn').disabled);
    assert.match(await page.locator('#tdIdentity').textContent(),/模拟账号/);
    assert.equal(await page.locator('#tdTermCount').textContent(),'—');
    assert.equal(await page.locator('#viewRegular').evaluate(el=>el.classList.contains('hidden')),true);
    assert.equal(await page.locator('#viewBoya').evaluate(el=>el.classList.contains('hidden')),true);
    assert.equal(await page.locator('#tdAutoToggle').isChecked(),false);
  });
  await check('td-settings-use-glass-controls-and-explicit-term',async () => {
    await page.locator('#tdSettingsBtn').click();
    assert.equal(await page.locator('#tdSettingsModal').evaluate(el=>el.classList.contains('hidden')),false);
    assert.equal(await page.locator('#tdCampusSelect').evaluate(el=>el.classList.contains('ui-select-native')),true);
    if(!await page.locator('#tdSemesterStart').inputValue())await page.locator('#tdSemesterStart').fill(startDate);
    if(!await page.locator('#tdSemesterEnd').inputValue())await page.locator('#tdSemesterEnd').fill(endDate);
    await page.locator('#tdStart').fill(startDate);await page.locator('#tdEnd').fill(endDate);
    await page.locator('#tdWeekdays input').evaluateAll(inputs=>inputs.forEach(input=>input.checked=true));
    await page.locator('#tdConfirmed').check();await page.locator('#tdSettingsSave').click();
    await page.waitForFunction(()=>document.getElementById('tdSettingsModal').classList.contains('hidden'));
    await page.waitForFunction(start=>document.getElementById('tdActivity').textContent.includes(start),startDate);
    assert.equal(await page.locator('#tdAutoToggle').isChecked(),false);
  });
  await check('td-glass-calendar-bounds-keyboard-and-single-layer',async()=>{
    await page.locator('#tdSettingsBtn').click();
    assert.equal(await page.locator('#tdStart').getAttribute('type'),'text');
    await page.locator('#tdStart').evaluate(el=>{el.min=el.value;});
    await page.locator('#tdStart + .td-date-trigger').click();
    assert.equal(await page.locator('.td-calendar').count(),1);
    await page.locator('#tdSettingsModal .modal-body').evaluate(el=>el.dispatchEvent(new Event('scroll')));
    assert.equal(await page.locator('.td-calendar').count(),1,'Queued scroll without anchor movement must not dismiss the calendar');
    assert.match(await page.locator('.td-calendar').evaluate(e=>getComputedStyle(e).backdropFilter),/blur/);
    assert.ok(await page.locator('.td-calendar-day:disabled').count()>0);
    const before=await page.locator('.td-calendar-day:focus').getAttribute('data-date');
    await page.keyboard.press('ArrowRight');
    assert.notEqual(await page.locator('.td-calendar-day:focus').getAttribute('data-date'),before);
    await page.keyboard.press('Escape');assert.equal(await page.locator('.td-calendar').count(),0);
    assert.equal(await page.locator('#tdSettingsModal').evaluate(e=>e.classList.contains('hidden')),false);
    await page.locator('#tdStart + .td-date-trigger').click();
    await page.locator('#tdEnd + .td-date-trigger').click();assert.equal(await page.locator('.td-calendar').count(),1);
    const position=await page.locator('.td-calendar').boundingBox();assert.ok(position.y>=0&&position.y+position.height<=page.viewportSize().height+1);
    await page.keyboard.press('Escape');await page.keyboard.press('Escape');
  });
  await check('td-photo-chooser-layered-keyboard-and-library-mode',async()=>{
    await page.locator('#tdDropzone').click();
    assert.equal(await page.locator('#tdEntryFile').isVisible(),false);
    assert.equal(await page.locator('#tdEntryPicker').isVisible(),true);
    assert.match(await page.locator('#tdEntryPicker').evaluate(e=>getComputedStyle(e).backdropFilter),/blur/);
    const chooser=page.waitForEvent('filechooser');await page.locator('#tdEntryPicker').focus();await page.keyboard.press('Enter');
    await (await chooser).setFiles([]);
    await page.locator('#tdGroupUseLibrary').check();assert.equal(await page.locator('#tdEntryPicker').isVisible(),false);
    await page.locator('#tdGroupUseLibrary').uncheck();assert.equal(await page.locator('#tdEntryPicker').isVisible(),true);
    await page.keyboard.press('Escape');
  });
  await check('td-count-is-manual-and-no-network-write-on-refresh',async () => {
    await page.locator('#tdCountBtn').click();await page.locator('#tdVerifiedCount').fill('12');await page.locator('#tdCountSave').click();
    await page.waitForFunction(()=>document.getElementById('tdTermCount').textContent==='12');
    assert.match(await page.locator('#tdCountSource').textContent(),/手动核对/);
    const before=network.filter(r=>r.method!=='GET').length;
    await page.locator('#tdRefreshBtn').click();await page.waitForTimeout(150);
    assert.equal(network.filter(r=>r.method!=='GET').length,before);
  });
  await check('td-out-of-term-progress-is-unknown-not-zero-and-keeps-history-copy',async()=>{
    const outOfScope=async r=>{
      const response=await r.fetch();const state=await response.json();
      await r.fulfill({response,json:{...state,license,progress:{count:null,count_source:'out_of_scope',count_at:null}}});
    };
    await page.route('**/api/td/status?**',outOfScope);
    try{
      await page.locator('#tdRefreshBtn').click();
      await page.waitForFunction(()=>document.getElementById('tdCountSource').textContent.includes('历史记录已保留'));
      assert.equal(await page.locator('#tdTermCount').textContent(),'—');
      assert.equal(await page.locator('#tdTermBar').getAttribute('aria-valuenow'),null);
    }finally{await page.unroute('**/api/td/status?**',outOfScope);}
    await page.locator('#tdRefreshBtn').click();
    await page.waitForFunction(()=>document.getElementById('tdTermCount').textContent==='12');
  });
  await check('td-group-import-paired-roles-and-gallery',async () => {
    for(let round=0;round<2;round++){
      await page.locator('#tdDropzone').click();
      await page.evaluate(async round=>{
        for(const [i,role] of ['Entry','Exit'].entries()){
          const canvas=document.createElement('canvas');canvas.width=120;canvas.height=90;
          canvas.getContext('2d').fillStyle=['#123478','#571257','#235467'][round+i];canvas.getContext('2d').fillRect(0,0,120,90);
          const blob=await new Promise(r=>canvas.toBlob(r,'image/jpeg'));const dt=new DataTransfer();dt.items.add(new File([blob],'synthetic.jpg',{type:'image/jpeg'}));
          const input=document.getElementById('td'+role+'File');input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));
        }
      },round);
      await page.locator('#tdGroupName').fill('Synthetic pair '+(round+1));await page.locator('#tdGroupConfirmed').check();await page.locator('#tdGroupSave').click();
      await page.waitForFunction(()=>document.getElementById('tdGroupModal').classList.contains('hidden'));
      await page.waitForFunction(count=>document.querySelectorAll('#tdGallery .td-photo').length===count,round+1);
    }
    await page.waitForFunction(()=>[...document.querySelectorAll('#tdGallery img')].every(i=>i.complete&&i.naturalWidth));
    assert.equal(await page.locator('#tdGallery img').count(),4);
    assert.equal(await page.locator('#tdGallery .td-pair-preview').count(),2);
  });
  await check('td-existing-photo-select-stays-inside-glass-slot',async()=>{
    await page.locator('#tdDropzone').click();await page.locator('#tdGroupUseLibrary').check();
    await page.waitForFunction(()=>[...document.querySelectorAll('#tdGroupModal .td-group-slot img')].every(i=>i.complete&&i.naturalWidth));
    const slots=await page.locator('#tdGroupModal .td-group-slot').evaluateAll(slots=>slots.map(slot=>{
      const shell=slot.querySelector('.ui-select-shell'),trigger=shell.querySelector('.ui-select-trigger');
      const s=slot.getBoundingClientRect(),w=shell.getBoundingClientRect(),t=trigger.getBoundingClientRect();
      return {height:w.height,inside:t.bottom<=s.bottom-14&&t.left>=s.left+14&&t.right<=s.right-14};
    }));
    assert.equal(slots.length,2);for(const slot of slots){assert.ok(slot.height>=38);assert.equal(slot.inside,true);}
    await page.keyboard.press('Escape');
  });
  await check('td-layered-glass-and-interruptible-library-motion',async()=>{
    assert.equal(await page.locator('#viewTD .td-progress-block.boya-progress-wrapper').count(),2);
    const filter=await page.locator('#viewTD .td-progress-block').first().evaluate(e=>getComputedStyle(e).backdropFilter);
    assert.match(filter,/blur/);
    const summary=page.locator('#tdLibrary summary');await summary.click();
    await page.waitForFunction(()=>!document.getElementById('tdLibrary').open);
    await summary.click();await page.waitForFunction(()=>document.getElementById('tdLibrary').open&&!document.getElementById('tdLibraryBody').inert);
    await page.waitForTimeout(350);
    assert.equal(await page.locator('#tdLibraryBody').evaluate(e=>e.classList.contains('ui-accordion-moving')),false);
  });
  await check('td-library-rapid-reversal-reduced-hidden-and-refresh',async()=>{
    const sample=await page.evaluate(async()=>{
      const details=document.getElementById('tdLibrary'),summary=details.querySelector('summary');
      const sleep=n=>new Promise(r=>setTimeout(r,n)), heights=[];
      summary.click();await sleep(70);const before=details.getBoundingClientRect().height;
      summary.click();heights.push(before,details.getBoundingClientRect().height);
      for(let i=0;i<8;i++){await sleep(30);summary.click();}
      document.dispatchEvent(new CustomEvent('buaa:tdgallery'));await sleep(380);
      return {heights,open:details.open,inert:document.getElementById('tdLibraryBody').inert,moving:details.classList.contains('ui-accordion-moving')};
    });
    assert.ok(Math.abs(sample.heights[0]-sample.heights[1])<4,'Reversal must start at the current rendered frame');
    assert.equal(sample.open,!sample.inert);assert.equal(sample.moving,false);
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.locator('#tdLibrary summary').click();
    assert.equal(await page.locator('#tdLibrary').evaluate(e=>e.open),!sample.open);
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.waitForFunction(()=>!document.getElementById('tdLibrary').classList.contains('ui-accordion-moving'));
    await page.evaluate(()=>{const d=document.getElementById('tdLibrary');if(!d.open)d.querySelector('summary').click();});
    await page.waitForFunction(()=>document.getElementById('tdLibrary').open&&!document.getElementById('tdLibrary').classList.contains('ui-accordion-moving'));
    await page.evaluate(()=>{document.getElementById('tdLibrary').querySelector('summary').click();window.dispatchEvent(new CustomEvent('buaa:renderstate',{detail:{visible:false}}));});
    await page.waitForFunction(()=>!document.getElementById('tdLibrary').classList.contains('ui-accordion-moving'));
    await page.evaluate(()=>{window.dispatchEvent(new CustomEvent('buaa:renderstate',{detail:{visible:true}}));const d=document.getElementById('tdLibrary');if(!d.open)d.querySelector('summary').click();});
    await page.waitForFunction(()=>document.getElementById('tdLibrary').open&&!document.getElementById('tdLibrary').classList.contains('ui-accordion-moving'));
    assert.equal(await page.locator('#tdLibraryBody').evaluate(e=>e.inert),false);
  });
  await check('td-manual-batch-confirmation-error-and-modal-exclusivity',async()=>{
    const state=await page.evaluate(async user=>(await apiFetch('/api/td/status?username='+encodeURIComponent(user))).json(),expectedUser);
    let writes=[];
    const mockStatus=async r=>r.fulfill({json:{...state,batch:{allowed:true,active:false,start_before:Date.now()/1000+600,reason:''}}});
    const mockManual=async r=>{writes.push(r.request().postDataJSON());await r.fulfill({status:409,json:{detail:'synthetic no campus write'}});};
    await page.route('**/api/td/status?**',mockStatus);await page.route('**/api/td/batch?**',mockManual);
    await page.locator('#tdRefreshBtn').click();await page.waitForFunction(()=>!document.getElementById('tdManualBtn').disabled);
    await page.locator('#tdManualBtn').click();await page.locator('#tdManualSave').click();assert.equal(writes.length,0);
    await page.locator('#tdManualConfirmed').check();await page.locator('#tdManualSave').click();
    await page.waitForFunction(()=>document.getElementById('tdManualError').textContent.includes('synthetic'));
    assert.deepEqual(writes,[{confirmed:true}]);
    await page.evaluate(()=>setUISurface('tdSettingsModal',true));assert.equal(await page.locator('#tdManualModal').evaluate(e=>e.classList.contains('hidden')),true);
    await page.keyboard.press('Escape');await page.locator('#tdRefreshBtn').click();assert.match(await page.locator('#tdManualBtn').textContent(),/手动 TD/);
    await page.locator('#tdManualBtn').click();assert.equal(await page.locator('#tdManualConfirmed').isChecked(),false);
    assert.match(await page.locator('#tdManualDesc').textContent(),/已固定/);await page.keyboard.press('Escape');
    await page.unroute('**/api/td/status?**',mockStatus);await page.unroute('**/api/td/batch?**',mockManual);await page.locator('#tdRefreshBtn').click();
  });
  await check('td-live-batch-phases-countdown-and-no-browser-school-writes',async()=>{
    const original=await page.evaluate(async user=>(await apiFetch('/api/td/status?username='+encodeURIComponent(user))).json(),expectedUser);
    let phase='sending_entry',attempted=1,reads=0;const due=Date.now()/1000+120;
    const status=async r=>{reads++;await r.fulfill({json:{...original,server_time:new Date().toISOString(),today:{attempted,completed:attempted-1},task:{state:phase,due},batch:{active:true,mode:'manual',allowed:false,reason:'queue active'}}});};
    await page.route('**/api/td/status?**',status);
    const networkBefore=network.filter(q=>q.method==='POST').length;
    for(const [next,label] of [['sending_entry',/正在入口/],['waiting_exit',/已入.*剩余 \d+ 秒/],['sending_exit',/正在出口/],['idle',/已出.*剩余 \d+ 秒/]]){
      phase=next;await page.locator('#tdRefreshBtn').click();await page.waitForFunction(expected=>new RegExp(expected).test(document.getElementById('tdTaskText').textContent),label.source);
      assert.equal(await page.locator('#tdManualBtn').isDisabled(),true);assert.equal(await page.locator('#tdBatchStopBtn').isVisible(),true);
    }
    const before=await page.locator('#tdTaskText').textContent();
    await page.waitForFunction(previous=>document.getElementById('tdTaskText').textContent!==previous,before,{timeout:4000});
    assert.equal(network.filter(q=>q.method==='POST').length,networkBefore);assert.ok(reads>=4);
    await page.unroute('**/api/td/status?**',status);await page.locator('#tdRefreshBtn').click();
  });
  await check('td-batch-window-closed-and-initial-auto-countdown',async()=>{
    const original=await page.evaluate(async user=>(await apiFetch('/api/td/status?username='+encodeURIComponent(user))).json(),expectedUser);
    let active=false;
    const status=async r=>r.fulfill({json:{...original,server_time:new Date().toISOString(),today:{attempted:0,completed:0},task:{state:'idle',due:Date.now()/1000+90},batch:{active,mode:'auto',allowed:!active,start_before:Date.now()/1000-1,reason:'outside window'}}});
    await page.route('**/api/td/status?**',status);await page.locator('#tdRefreshBtn').click();await page.waitForFunction(()=>document.getElementById('tdManualBtn').disabled);
    active=true;await page.locator('#tdRefreshBtn').click();await page.waitForFunction(()=>document.getElementById('tdTaskText').textContent.includes('等待首次入口'));
    assert.equal(await page.locator('#tdManualBtn').isDisabled(),true);
    await page.unroute('**/api/td/status?**',status);await page.locator('#tdRefreshBtn').click();
  });
  await check('td-batch-double-submit-is-one-request-and-shows-active-state',async()=>{
    const original=await page.evaluate(async user=>(await apiFetch('/api/td/status?username='+encodeURIComponent(user))).json(),expectedUser);
    let active=false,writes=0,release;const pending=new Promise(resolve=>release=resolve);
    const status=async r=>r.fulfill({json:{...original,server_time:new Date().toISOString(),task:{state:'waiting_exit',due:Date.now()/1000+100},batch:{active,mode:'manual',allowed:!active,start_before:Date.now()/1000+600,reason:''}}});
    const start=async r=>{writes++;await pending;active=true;await r.fulfill({json:{status:'ok',queued:true}});};
    await page.route('**/api/td/status?**',status);await page.route('**/api/td/batch?**',start);
    try{
      await page.locator('#tdRefreshBtn').click();await page.waitForFunction(()=>!document.getElementById('tdManualBtn').disabled);
      await page.locator('#tdManualBtn').click();await page.locator('#tdManualConfirmed').check();
      await page.locator('#tdManualSave').click();
      await page.locator('#tdManualForm').dispatchEvent('submit');
      assert.equal(await page.locator('#tdManualBtn').isDisabled(),true);assert.equal(await page.locator('#tdManualSave').isDisabled(),true);
      release();await page.waitForFunction(()=>document.getElementById('tdDaemonStatus').textContent.includes('手动当日队列'));
      assert.equal(writes,1);assert.equal(await page.locator('#tdManualBtn').isDisabled(),true);
      await page.setViewportSize({width:960,height:620});assert.equal(await page.evaluate(()=>document.body.scrollWidth<=innerWidth+2),true);
      await page.setViewportSize({width:1280,height:840});
    }finally{release();await page.unroute('**/api/td/status?**',status);await page.unroute('**/api/td/batch?**',start);await page.locator('#tdRefreshBtn').click();}
  });
  await check('td-selection-and-keyboard-modal-exclusivity',async () => {
    await page.locator('#tdSelectAll').check();assert.equal(await page.locator('#tdDeleteBtn').isDisabled(),false);
    assert.match(await page.locator('#tdSelectionCount').textContent(),/2/);
    await page.locator('#tdSettingsBtn').click();await page.keyboard.press('Escape');
    assert.equal(await page.locator('#tdSettingsModal').evaluate(el=>el.classList.contains('hidden')),true);
    await page.locator('#tdCountBtn').click();
    await page.evaluate(()=>openAccountCardsModal());
    assert.equal(await page.locator('#tdCountModal').evaluate(el=>el.classList.contains('hidden')),true);
    await page.keyboard.press('Escape');
  });
  await check('td-toggle-captures-intent-and-restores-after-rejection',async () => {
    let intent=null;
    const state=await page.evaluate(async user=>(await apiFetch('/api/td/status?username='+encodeURIComponent(user))).json(),expectedUser);
    const licensed=async handler=>handler.fulfill({json:{...state,license:{active:true,expires_at:'2099-12-31T23:59:59+08:00',expires_epoch:4102444799,reason:''}}});
    await page.route('**/api/td/status?**',licensed);await page.locator('#tdRefreshBtn').click();await page.waitForFunction(()=>!document.getElementById('tdAutoToggle').disabled);
    const route=async handler => {
      intent=handler.request().postDataJSON().enabled;
      await handler.fulfill({status:409,json:{detail:'synthetic TD refusal'}});
    };
    await page.route('**/api/td/toggle?**',route);
    await page.locator('#tdAutoToggle + .origin-slider').click();
    await page.waitForFunction(()=>!document.getElementById('tdAutoToggle').disabled);
    assert.equal(intent,true);assert.equal(await page.locator('#tdAutoToggle').isChecked(),false);
    await page.unroute('**/api/td/toggle?**',route);
    await page.unroute('**/api/td/status?**',licensed);await page.locator('#tdRefreshBtn').click();
  });
  await check('td-activated-license-card-close-and-free-notice',async()=>{
    await page.locator('#tdLicenseBtn').click();
    assert.equal(await page.locator('#tdLicenseRequestBtn').isDisabled(),true);
    assert.match(await page.locator('#tdLicenseModal .td-license-notice').textContent(),/开源免费、非营利/);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#tdLicenseModal').evaluate(e=>e.classList.contains('hidden')),true);
  });
  await check('td-empty-and-full-size-responsive-no-overflow',async () => {
    for(const [width,height] of [[960,620],[1600,1000],[1280,840]]) {
      await page.setViewportSize({width,height});
      assert.equal(await page.evaluate(()=>document.body.scrollWidth<=innerWidth+2),true);
      assert.equal(await page.locator('#viewTD').evaluate(el=>el.scrollWidth<=el.clientWidth+2),true);
    }
  });
  await check('td-cross-account-gallery-and-late-response-isolation',async () => {
    const oldState=await page.evaluate(async user => (await apiFetch('/api/td/status?username='+encodeURIComponent(user))).json(),expectedUser);
    let release,held=false;
    const lateStatus=async route=>{
      if(new URL(route.request().url()).searchParams.get('username')===expectedUser&&!held){
        held=true;await new Promise(resolve=>{release=resolve;});
        try{await route.fulfill({json:oldState});}catch{/* The account switch correctly aborts the old request. */}
      }else await route.continue();
    };
    await page.route('**/api/td/status?**',lateStatus);
    await page.locator('#tdRefreshBtn').click();
    for(let i=0;!release&&i<100;i++)await page.waitForTimeout(10);
    assert.ok(release,'Hold an actual old-account TD response before switching');
    await page.locator('#navBtnAccounts').click();
    const other=expectedUser==='fixture-account-1'?'fixture-account-2':'fixture-account-1';
    await page.locator(`[data-action="switchAccount"][data-id="${other}"]`).click();
    await page.waitForFunction(user=>appState.activeUsername===user,other);
    await page.waitForFunction(()=>document.querySelectorAll('#tdGallery .td-photo').length===0);
    release();await page.waitForTimeout(100);
    assert.equal(await page.locator('#tdTermCount').textContent(),'—');
    assert.equal(await page.locator('#tdGallery .td-photo').count(),0);
    await page.unroute('**/api/td/status?**',lateStatus);
    await page.locator('#navBtnAccounts').click();await page.locator(`[data-action="switchAccount"][data-id="${expectedUser}"]`).click();
    await page.waitForFunction(()=>document.querySelectorAll('#tdGallery .td-photo').length===2);
    assert.equal(await page.locator('#tdTermCount').textContent(),'12');
  });
  await check('td-log-filter-and-account-scoped-requests',async () => {
    await page.locator('#navBtnLogs').click();await page.locator('#logCatTD').click();
    assert.equal(await page.evaluate(()=>appState.currentLogCategory),'td');
    assert.match(await page.locator('#logTerminalTitle').textContent(),/自动 TD/);
    assert.equal(network.every(r=>new URL(r.url).searchParams.has('username')),true);
    assert.equal(network.some(r=>r.body&&/password|session_id|cookie|cardno/.test(r.body)),false);
    await page.locator('#logCatAll').click();
  });
  await page.unroute('**/api/td/license/status?**',entranceLicense);
  await page.unroute('**/api/td/status?**',presentationLicense);
  page.off('request',listener);
};
