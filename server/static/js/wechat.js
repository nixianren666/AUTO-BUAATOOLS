/* Account captured on opening; viewing another student never changes a binding. */
(() => {
  'use strict';
  let username='', generation=0, timer=null, busy=false, controller=null, canTest=false, pendingBinding='', dirty=false;
  const tests=new Map(),receipts=new Set();
  const el=id=>document.getElementById(id);
  const current=g=>g===generation && !el('wechatModal').classList.contains('hidden');
  const message=text=>{el('wechatStatus').textContent=text;};
  const request=async(path,body,g=generation)=>{
    const response=await apiFetch('/api/wechat/'+path+(body?'':'?username='+encodeURIComponent(username)),body?{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,username}),signal:controller.signal
    }:{signal:controller.signal});
    const data=await response.json();
    if (!current(g)) throw new Error('通道视图已关闭');
    return data;
  };
  const statuses={sending:'正在发送',accepted:'微信接口已接受，待本人确认收信',submitted:'已提交微信，待本人确认收信',rejected:'微信拒绝通知，请查看通道提示',unconfirmed:'发送结果未确认，未自动重发',session_expired:'微信登录已失效，请重新绑定',expired:'通知已过期，未补发'};
  function steps(data) {
    const blocked=!!(data.send_error||data.worker_error||data.session_expired||data.storage_error);
    const complete=[!!data.bound,!!data.bound&&!!data.ready,!!data.ready&&!blocked&&receipts.has(username)];
    const ids=['wechatStepScan','wechatStepMessage','wechatStepReceipt'];
    ids.forEach((id,i)=>{const node=el(id);node.classList.toggle('is-complete',complete[i]);node.classList.toggle('is-current',!complete[i]&&(i===0||complete[i-1]));node.querySelector('.wechat-step-mark').textContent=complete[i]?'✓':String(i+1);node.setAttribute('aria-label','第'+(i+1)+'步，'+(complete[i]?'已完成':'待完成'));});
    el('wechatReceived').checked=complete[2];
    el('wechatReceived').disabled=!data.ready||blocked||!(data.recent||[]).some(r=>r.id===tests.get(username)&&['accepted','submitted'].includes(r.state));
  }
  async function refresh(g=generation) {
    const data=await request('status',null,g);
    if (data.username!==username) throw new Error('学生通道不匹配');
    el('wechatBindArea').hidden=data.bound;el('wechatBoundArea').hidden=!data.bound;
    if (!busy&&!dirty) {el('wechatEnabled').checked=data.enabled;el('wechatImportant').checked=data.important_only;el('wechatCourseReminders').checked=!!data.course_reminders;}
    if(!data.bound){tests.delete(username);receipts.delete(username);}
    steps(data);
    el('wechatCourseStatus').textContent=!data.course_reminders?'课前提醒已关闭。':!data.enabled?'通知已暂停，暂不发送课前提醒。':!data.ready?'完成第2步后，才能读取课表并发送提醒。':data.course_sync==='ok'?'课表已同步；有课时在课前15分钟窗口内提醒。':data.course_sync==='unavailable'?'课表暂未同步，本轮不发送提醒；请核对账号认证和网络。':'正在等待读取课表，未读取到课程前不会发送提醒。';
    const sendIssue=data.send_error_kind==='business'?'微信拒绝了最近一次通知'+(Number.isInteger(data.send_error_code)?'（错误码 '+data.send_error_code+'）':'')+'。请到微信向机器人发送“开始接收”，再发送测试并核对实收；也可能受微信限流或其他策略影响，不会自动重发旧通知。':'最近一次发送未能确认，不能视为已就绪。请检查网络，发送测试并核对微信实收；旧通知不会自动重放。';
    message(data.storage_error?'私有存储不可用，请检查部署目录。':data.session_expired?'微信登录状态失效，请解绑后重新扫码。':!data.bound?'尚未绑定微信。':!data.enabled?'此学生的微信通知已暂停。':data.send_error?sendIssue:data.worker_error?'微信后台任务正在恢复；其他学生与学校任务独立运行。':data.connection_error?'微信接收通道暂时连接失败；学校后台任务独立运行。':!data.ready?'已绑定：请先在微信中向机器人发送“开始接收”。':'微信接收连接正常；通知是否送达请以本人微信实收为准。');
    const seen=new Set();
    el('wechatRecent').textContent=(data.recent||[]).filter(r=>!seen.has(r.id)&&seen.add(r.id)).slice(0,5).map(r=>r.time.replace('T',' ')+' · '+r.id+' · '+(statuses[r.state]||'待核对')).join('\n');
    canTest=!!data.enabled&&!!data.ready&&!data.session_expired&&!data.storage_error;
    el('wechatTest').disabled=!canTest;
  }
  const close=()=>{generation++;clearTimeout(timer);controller?.abort();setUISurface('wechatModal',false);el('wechatQr').removeAttribute('src');el('wechatVerifyCode').value='';pendingBinding='';};
  async function pollBinding(id,g,code) {
    while (current(g)) {
      const data=await request('bind/status',{binding_id:id,...(code?{verify_code:code}:{})},g);code='';
      const descriptions={wait:'等待微信扫码…',scaned:'微信已扫码，请在手机确认。',expired:'二维码已过期，请重新生成。',need_verifycode:'微信要求额外验证，请在微信官方流程完成后重新扫码。',verify_code_blocked:'微信验证受限，请稍后重新扫码。',binded_redirect:'此微信已有绑定，请先核对原通道，避免重复绑定。',scaned_but_redirect:'正在核对微信通道…'};
      if (data.status==='confirmed') {el('wechatQrArea').hidden=true;el('wechatVerifyForm').hidden=true;el('wechatQr').removeAttribute('src');pendingBinding='';busy=false;await refresh(g);return;}
      if(data.status==='need_verifycode'){pendingBinding=id;el('wechatVerifyForm').hidden=false;message('请输入手机微信显示的配对数字。');el('wechatVerifyCode').focus();return;}
      message(descriptions[data.status]||'等待微信确认…');
      if (['expired','need_verifycode','verify_code_blocked','binded_redirect'].includes(data.status)) return;
      await new Promise(resolve=>setTimeout(resolve,1500));
    }
  }
  async function action(fn) {
    if (busy) return;
    busy=true;const g=generation;
    for(const id of ['wechatBind','wechatSave','wechatTest','wechatUnbind'])el(id).disabled=true;
    try {await fn(g);} catch(error) {if(current(g))message(error.message);}
    finally {if(current(g)){busy=false;el('wechatBind').disabled=!el('wechatConsent').checked;el('wechatSave').disabled=el('wechatUnbind').disabled=false;el('wechatTest').disabled=!canTest;}}
  }
  function watch(g) {
    timer=setTimeout(async()=>{if(!current(g))return;try{if(!busy&&!pendingBinding)await refresh(g);}catch(error){if(current(g))message(error.message);}if(current(g))watch(g);},4000);
  }
  window.BUAAWechat={openCurrent:()=>{
    const user=appState.activeUsername||appState.accounts[0]?.username;
    if(user)void window.BUAAWechat.open(user);else{openAccountCardsModal();showToast('请先添加学生，再绑定微信助手。','info');}
  },open:async user=>{
    if (!appState.accounts.some(a=>a.username===user)) return;
    generation++;clearTimeout(timer);controller?.abort();controller=new AbortController();busy=false;canTest=false;dirty=false;username=user;
    el('wechatSave').disabled=el('wechatUnbind').disabled=false;el('wechatTest').disabled=true;
    closeAccountCardsModal();
    if (!setUISurface('wechatModal',true))return;
    el('wechatStudent').textContent='当前学生：'+(appState.accounts.find(a=>a.username===user)?.name||user);
    el('wechatAccountSelect').replaceChildren(...appState.accounts.map(a=>{const option=document.createElement('option');option.value=a.username;option.textContent=a.name||a.username;return option;}));el('wechatAccountSelect').value=user;
    steps({});el('wechatBoundArea').hidden=true;el('wechatBindArea').hidden=true;
    pendingBinding='';el('wechatVerifyForm').hidden=true;el('wechatVerifyCode').value='';
    el('wechatConsent').checked=false;el('wechatBind').disabled=true;el('wechatQrArea').hidden=true;el('wechatQr').removeAttribute('src');
    const g=generation;
    try{await refresh(g);watch(g);}catch(error){if(current(g))message(error.message);}
  },close};
  document.addEventListener('DOMContentLoaded',()=>{
    el('wechatClose').onclick=close;
    el('wechatAccountSelect').onchange=event=>void window.BUAAWechat.open(event.target.value);
    el('wechatCopyStart').onclick=async()=>{try{await navigator.clipboard.writeText('开始接收');message('已复制“开始接收”。请粘贴到微信里刚绑定的机器人聊天并发送。');}catch(error){message('请在微信里刚绑定的机器人聊天中手动输入并发送：开始接收');}};
    for(const id of ['wechatEnabled','wechatImportant','wechatCourseReminders'])el(id).onchange=()=>{dirty=true;};
    el('wechatReceived').onchange=()=>{const done=el('wechatReceived').checked&&!el('wechatReceived').disabled;if(done)receipts.add(username);else receipts.delete(username);const step=el('wechatStepReceipt');step.classList.toggle('is-complete',done);step.classList.toggle('is-current',!done);step.querySelector('.wechat-step-mark').textContent=done?'✓':'3';step.setAttribute('aria-label','第3步，'+(done?'已完成':'待完成'));if(done)message('你已确认实际收信，此学生的微信助手已连接。');};
    el('wechatVerifyForm').onsubmit=event=>{event.preventDefault();if(!pendingBinding||busy)return;const code=el('wechatVerifyCode').value;el('wechatVerifyCode').value='';el('wechatVerifyForm').hidden=true;void action(g=>pollBinding(pendingBinding,g,code));};
    el('wechatConsent').onchange=()=>{el('wechatBind').disabled=busy||!el('wechatConsent').checked;};
    el('wechatBind').onclick=()=>action(async g=>{
      pendingBinding='';el('wechatVerifyForm').hidden=true;el('wechatVerifyCode').value='';
      message('正在生成此学生的绑定二维码…');const data=await request('bind',{},g);
      el('wechatQr').src='/api/wechat/qrcode?username='+encodeURIComponent(username)+'&binding_id='+encodeURIComponent(data.binding_id);
      el('wechatQrArea').hidden=false;await pollBinding(data.binding_id,g);
    });
    el('wechatSave').onclick=()=>action(async g=>{await request('settings',{enabled:el('wechatEnabled').checked,important_only:el('wechatImportant').checked,course_reminders:el('wechatCourseReminders').checked},g);dirty=false;busy=false;await refresh(g);});
    el('wechatTest').onclick=()=>action(async g=>{const data=await request('test',{},g);tests.set(username,data.test_id);receipts.delete(username);el('wechatReceived').checked=false;el('wechatReceived').disabled=true;message('测试已排队，编号 '+data.test_id+'。请在微信实际确认是否收到，再勾选第3步。');});
    el('wechatUnbind').onclick=()=>action(async g=>{
      if(!confirm('解绑此学生的微信并清空待发通知？其他学生保持不变。'))return;
      await request('unbind',{},g);tests.delete(username);receipts.delete(username);dirty=false;busy=false;await refresh(g);
    });
    el('wechatModal').addEventListener('click',e=>{if(e.target===el('wechatModal'))close();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&current(generation)){e.preventDefault();close();}});
    document.addEventListener('buaa:surfacechange',e=>{if(e.detail?.id==='wechatModal'&&!e.detail.visible){clearTimeout(timer);controller?.abort();}});
  });
})();
