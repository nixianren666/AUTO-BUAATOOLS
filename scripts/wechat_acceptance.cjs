/* Notification UI against a synthetic Tencent boundary; no real binding/push. */
const assert=require('node:assert/strict');
exports.verifyWechat=async(page,check)=>{
  const states={},writes=[],pending=new Set();let confirmed=false,needsDigits=false,settingsDelay=0;
  const pattern='**/api/wechat/**';
  const handler=async route=>{
    const request=route.request(),url=new URL(request.url()),body=request.postDataJSON?.()||{};
    const user=body.username||url.searchParams.get('username');
    if(request.method()!=='GET')writes.push({path:url.pathname,user,code:body.verify_code});
    const state=states[user]||={bound:false,ready:false,enabled:true,important_only:false,recent:[]};
    let result={status:'ok'};
    if(url.pathname.endsWith('/status')&&!url.pathname.includes('/bind/'))result={...state,username:user};
    else if(url.pathname.endsWith('/bind'))result={status:'wait',binding_id:'a'.repeat(32)};
    else if(url.pathname.endsWith('/bind/status')){result={status:needsDigits&&!body.verify_code?'need_verifycode':confirmed?'confirmed':'wait'};if(result.status==='confirmed')state.bound=true;}
    else if(url.pathname.endsWith('/settings')){Object.assign(state,{enabled:body.enabled,important_only:body.important_only,course_reminders:body.course_reminders});if(settingsDelay){const wait=new Promise(resolve=>setTimeout(resolve,settingsDelay));pending.add(wait);await wait;pending.delete(wait);}}
    else if(url.pathname.endsWith('/test')){state.recent=[{id:'abc123',state:'accepted',time:'10:00'}];result={status:'queued',test_id:'abc123'};}
    else if(url.pathname.endsWith('/unbind'))state.bound=state.ready=false;
    else if(url.pathname.endsWith('/qrcode'))return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a/ksAAAAASUVORK5CYII=','base64')});
    try{await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(result)});}catch(error){if(!/already handled|closed|cancelled/i.test(error.message))throw error;}
  };
  await page.route(pattern,handler);
  try {
    await check('wechat-binding-consent-and-local-qr-in-existing-glass-modal',async()=>{
      await page.locator('#navBtnAccounts').click();
      await page.locator('[data-action="wechat"][data-id="fixture-account-1"]').click();
      await page.locator('#wechatModal').waitFor({state:'visible'});
      assert.equal(await page.locator('#accountCardsModal').isVisible(),false);
      assert.equal(await page.locator('#wechatBind').isDisabled(),true);
      await page.locator('#wechatConsent').check();await page.locator('#wechatBind').click();
      await page.locator('#wechatQrArea').waitFor({state:'visible'});
      assert.equal(new URL(await page.locator('#wechatQr').getAttribute('src'),page.url()).origin,new URL(page.url()).origin);
      confirmed=true;await page.locator('#wechatBoundArea').waitFor({state:'visible'});
      assert.equal(await page.locator('#wechatTest').isDisabled(),true);
      assert.match(await page.locator('#wechatStatus').textContent(),/开始接收/);
      assert.equal(await page.locator('#wechatStepScan').evaluate(e=>e.classList.contains('is-complete')),true);
      assert.equal(await page.locator('#wechatStepMessage').evaluate(e=>e.classList.contains('is-complete')),false);
      assert.equal(await page.locator('#wechatReceived').isDisabled(),true);
    });
    await check('wechat-test-is-bound-to-captured-student-and-never-claims-delivery',async()=>{
      states['fixture-account-1'].ready=true;
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-1'));
      await page.locator('#wechatTest').waitFor({state:'visible'});
      await page.evaluate(()=>{appState.activeUsername='fixture-account-2';});
      await page.locator('#wechatTest').click();
      await page.waitForFunction(()=>document.getElementById('wechatStatus').textContent.includes('abc123'));
      assert.equal(writes.at(-1).user,'fixture-account-1');
      assert.match(await page.locator('#wechatStatus').textContent(),/实际确认/);
      assert.equal(await page.locator('#wechatStepMessage').evaluate(e=>e.classList.contains('is-complete')),true);
      assert.equal(await page.locator('#wechatStepReceipt').evaluate(e=>e.classList.contains('is-complete')),false);
      await page.waitForFunction(()=>!document.getElementById('wechatReceived').disabled);
      await page.locator('#wechatReceived').check();
      assert.equal(await page.locator('#wechatStepReceipt').evaluate(e=>e.classList.contains('is-complete')),true);
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-2'));
      await page.waitForFunction(()=>document.getElementById('wechatStatus').textContent.includes('尚未绑定'));
      assert.equal(await page.locator('#wechatBoundArea').isVisible(),false);
      assert.equal(await page.locator('#wechatRecent').textContent(),'');
      assert.equal(await page.locator('#wechatReceived').isChecked(),false);
    });
    await check('wechat-pairing-digits-are-manual-owner-input-and-not-retained',async()=>{
      confirmed=false;needsDigits=true;
      await page.locator('#wechatConsent').check();await page.locator('#wechatBind').click();
      await page.locator('#wechatVerifyForm').waitFor({state:'visible'});
      await page.waitForTimeout(4200);
      assert.match(await page.locator('#wechatStatus').textContent(),/手机微信显示/);
      assert.equal(writes.filter(w=>w.code).length,0);
      await page.locator('#wechatVerifyCode').fill('123456');confirmed=true;
      await page.locator('#wechatVerifyForm button').click();
      await page.locator('#wechatBoundArea').waitFor({state:'visible'});
      assert.equal(writes.filter(w=>w.code).length,1);assert.equal(writes.find(w=>w.code).user,'fixture-account-2');
      assert.equal(await page.locator('#wechatVerifyCode').inputValue(),'');
      assert.equal(await page.locator('#wechatVerifyForm').isVisible(),false);needsDigits=false;
    });
    await check('wechat-close-during-save-can-reopen-with-usable-controls',async()=>{
      states['fixture-account-2'].ready=true;settingsDelay=600;
      await page.locator('#wechatSave').click();await page.waitForTimeout(80);
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-1'));
      await page.waitForFunction(()=>!document.getElementById('wechatTest').disabled);
      assert.equal(await page.locator('#wechatSave').isDisabled(),false);
      assert.equal(await page.locator('#wechatUnbind').isDisabled(),false);settingsDelay=0;
    });
    await check('wechat-sidebar-opens-current-student-with-independent-account-selector',async()=>{
      await page.locator('#wechatClose').click();await page.evaluate(()=>{appState.activeUsername='fixture-account-1';});
      await page.locator('#navBtnWechat').click();await page.locator('#wechatBoundArea').waitFor({state:'visible'});
      assert.equal(await page.locator('#wechatAccountSelect').inputValue(),'fixture-account-1');
      await page.locator('#wechatAccountSelect').selectOption('fixture-account-2');
      await page.waitForFunction(()=>document.getElementById('wechatStudent').textContent.includes(appState.accounts.find(a=>a.username==='fixture-account-2').name));
      assert.equal(await page.evaluate(()=>appState.activeUsername),'fixture-account-1');
      await page.waitForFunction(()=>!document.getElementById('wechatTest').disabled);
    });
    await check('wechat-reminder-preference-is-explicit-and-unsaved-input-survives-refresh',async()=>{
      await page.locator('#wechatCourseReminders').check();await page.waitForTimeout(4300);
      assert.equal(await page.locator('#wechatCourseReminders').isChecked(),true);
      await page.locator('#wechatSave').click();
      await page.waitForFunction(()=>!document.getElementById('wechatSave').disabled);
      assert.equal(states['fixture-account-2'].course_reminders,true);
      assert.equal(writes.at(-1).user,'fixture-account-2');
    });
    await check('wechat-completed-stages-have-green-text-checkmarks-and-current-instruction',async()=>{
      const stages=await page.locator('#wechatStepScan,#wechatStepMessage').evaluateAll(nodes=>nodes.map(n=>({complete:n.classList.contains('is-complete'),mark:n.querySelector('.wechat-step-mark').textContent,color:getComputedStyle(n).color})));
      for(const stage of stages){assert.equal(stage.complete,true);assert.equal(stage.mark,'✓');assert.equal(stage.color,'rgb(74, 222, 128)');}
      assert.match(await page.locator('#wechatStepMessage').textContent(),/扫码后还差这一步/);
    });
    await check('wechat-send-rejection-stays-visible-through-successful-status-polls',async()=>{
      const state=states['fixture-account-1'];Object.assign(state,{send_error:true,send_error_code:-2,send_error_kind:'business',connection_error:false});
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-1'));
      await page.waitForFunction(()=>document.getElementById('wechatStatus').textContent.includes('错误码 -2'));
      await page.waitForTimeout(4300);assert.match(await page.locator('#wechatStatus').textContent(),/错误码 -2/);
      assert.equal(await page.locator('#wechatStepReceipt').evaluate(e=>e.classList.contains('is-complete')),false);
      assert.equal(await page.locator('#wechatReceived').isDisabled(),true);
      assert.equal(await page.locator('#wechatTest').isDisabled(),false);state.send_error=false;
    });
    await check('wechat-worker-fault-is-not-ready-and-other-student-is-independent',async()=>{
      states['fixture-account-1'].worker_error=true;
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-1'));
      await page.waitForFunction(()=>document.getElementById('wechatStatus').textContent.includes('正在恢复'));
      await page.locator('#wechatAccountSelect').selectOption('fixture-account-2');
      await page.waitForFunction(()=>document.getElementById('wechatStatus').textContent.includes('接收连接正常'));
      assert.doesNotMatch(await page.locator('#wechatStatus').textContent(),/正在恢复/);states['fixture-account-1'].worker_error=false;
    });
    await check('wechat-course-read-success-does-not-hide-rejected-reminder-and-send-backoff',async()=>{
      Object.assign(states['fixture-account-1'],{course_reminders:true,course_sync:'ok',send_error:true,send_error_kind:'business',send_error_code:-2,send_retry_in_seconds:120,
        reminder_recent:[{course_start:'2026-10-30T14:00:00+08:00',state:'rejected',error_code:-2,time:'2026-10-30T13:45:00'}]});
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-1'));
      await page.waitForFunction(()=>document.getElementById('wechatReminderRecent').textContent.includes('错误码 -2'));
      assert.match(await page.locator('#wechatCourseStatus').textContent(),/微信通知未成功确认/);
      assert.match(await page.locator('#wechatStatus').textContent(),/120 秒/);
      assert.match(await page.locator('#wechatReminderRecent').textContent(),/微信拒绝通知/);
    });
    await check('wechat-reminder-history-distinguishes-legacy-interruption-and-provider-acceptance',async()=>{
      Object.assign(states['fixture-account-1'],{send_error:false,send_retry_in_seconds:0,reminder_recent:[
        {course_start:'2026-10-30T14:00:00+08:00',state:'registered_only'},
        {course_start:'2026-10-30T09:50:00+08:00',state:'not_replayed'},
        {course_start:'2026-10-30T08:00:00+08:00',state:'accepted'}]});
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-1'));
      await page.waitForFunction(()=>document.getElementById('wechatReminderRecent').textContent.includes('旧版仅登记'));
      const text=await page.locator('#wechatReminderRecent').textContent();
      assert.match(text,/进程中断，未自动重发/);assert.match(text,/待本人确认收信/);assert.doesNotMatch(text,/已送达/);
    });
    await check('wechat-reminder-results-never-leak-to-another-student-view',async()=>{
      await page.locator('#wechatAccountSelect').selectOption('fixture-account-2');
      await page.waitForFunction(()=>document.getElementById('wechatReminderRecent').textContent==='');
      assert.doesNotMatch(await page.locator('#wechatStatus').textContent(),/120 秒/);
    });
    await check('wechat-reminder-capacity-and-worker-recovery-are-actionable-not-ready-claims',async()=>{
      Object.assign(states['fixture-account-2'],{course_reminders:true,course_sync:'capacity'});
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-2'));
      await page.waitForFunction(()=>document.getElementById('wechatCourseStatus').textContent.includes('已达上限'));
      states['fixture-account-2'].reminder_worker_error=true;
      await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-2'));
      await page.waitForFunction(()=>document.getElementById('wechatCourseStatus').textContent.includes('后台正在恢复'));
      Object.assign(states['fixture-account-2'],{reminder_worker_error:false,course_sync:'ok'});
    });
    await check('wechat-new-modal-keeps-phone-fields-and-controls-inside-viewport',async()=>{
      const original=page.viewportSize();
      try{for(const viewport of [{width:320,height:568},{width:390,height:844},{width:844,height:390}]){
        await page.setViewportSize(viewport);
        const boxes=await page.locator('#wechatModal').evaluate(modal=>{
          const panel=modal.firstElementChild,r=panel.getBoundingClientRect();
          return {left:r.left,right:r.right,scroll:document.documentElement.scrollWidth,width:innerWidth};
        });
        assert.ok(boxes.left>=-1&&boxes.right<=viewport.width+1,JSON.stringify(boxes));
        assert.ok(boxes.scroll<=boxes.width+1,JSON.stringify(boxes));
        const header=await page.locator('#wechatModal .modal-header').boundingBox();assert.ok(header.y>=0&&header.y+header.height<=viewport.height);
        await page.locator('#wechatClose').click();await page.evaluate(()=>BUAAWechat.open('fixture-account-1'));
        await page.locator('#wechatSave').waitFor({state:'visible'});
      }}finally{await page.setViewportSize(original);}
    });
  }finally{
    await page.evaluate(()=>{BUAAWechat.close();appState.activeUsername='fixture-account-1';});
    await Promise.allSettled([...pending]);
    await page.unroute(pattern,handler);
  }
};
