/* Account captured on opening; viewing another student never changes a binding. */
(() => {
  'use strict';
  let username='', generation=0, timer=null, busy=false, controller=null, canTest=false, pendingBinding='';
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
  const statuses={sending:'正在发送',accepted:'微信接口已接受，待本人确认收信',submitted:'已提交微信，待本人确认收信',unconfirmed:'发送结果未确认，未自动重发',session_expired:'微信会话已失效，请重新绑定',expired:'通知已过期，未补发'};
  async function refresh(g=generation) {
    const data=await request('status',null,g);
    if (data.username!==username) throw new Error('学生通道不匹配');
    el('wechatBindArea').hidden=data.bound;el('wechatBoundArea').hidden=!data.bound;
    if (!busy) {el('wechatEnabled').checked=data.enabled;el('wechatImportant').checked=data.important_only;}
    message(data.storage_error?'私有存储不可用，请检查部署目录。':data.session_expired?'微信登录状态失效，请解绑后重新扫码。':!data.bound?'尚未绑定微信。':!data.enabled?'此学生的微信通知已暂停。':data.connection_error?'微信通道暂时连接失败；学校后台任务独立运行。':!data.ready?'已绑定：请先在微信中向机器人发送“开始接收”。':'此学生的通知通道已就绪，等待运行日志。');
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
  window.BUAAWechat={open:async user=>{
    if (!appState.accounts.some(a=>a.username===user)) return;
    generation++;clearTimeout(timer);controller?.abort();controller=new AbortController();busy=false;canTest=false;username=user;
    el('wechatSave').disabled=el('wechatUnbind').disabled=false;el('wechatTest').disabled=true;
    closeAccountCardsModal();
    if (!setUISurface('wechatModal',true))return;
    el('wechatStudent').textContent='当前学生：'+(appState.accounts.find(a=>a.username===user)?.name||user);
    pendingBinding='';el('wechatVerifyForm').hidden=true;el('wechatVerifyCode').value='';
    el('wechatConsent').checked=false;el('wechatBind').disabled=true;el('wechatQrArea').hidden=true;el('wechatQr').removeAttribute('src');
    const g=generation;
    try{await refresh(g);watch(g);}catch(error){if(current(g))message(error.message);}
  },close};
  document.addEventListener('DOMContentLoaded',()=>{
    el('wechatClose').onclick=close;
    el('wechatVerifyForm').onsubmit=event=>{event.preventDefault();if(!pendingBinding||busy)return;const code=el('wechatVerifyCode').value;el('wechatVerifyCode').value='';el('wechatVerifyForm').hidden=true;void action(g=>pollBinding(pendingBinding,g,code));};
    el('wechatConsent').onchange=()=>{el('wechatBind').disabled=busy||!el('wechatConsent').checked;};
    el('wechatBind').onclick=()=>action(async g=>{
      pendingBinding='';el('wechatVerifyForm').hidden=true;el('wechatVerifyCode').value='';
      message('正在生成此学生的绑定二维码…');const data=await request('bind',{},g);
      el('wechatQr').src='/api/wechat/qrcode?username='+encodeURIComponent(username)+'&binding_id='+encodeURIComponent(data.binding_id);
      el('wechatQrArea').hidden=false;await pollBinding(data.binding_id,g);
    });
    el('wechatSave').onclick=()=>action(async g=>{await request('settings',{enabled:el('wechatEnabled').checked,important_only:el('wechatImportant').checked},g);busy=false;await refresh(g);});
    el('wechatTest').onclick=()=>action(async g=>{const data=await request('test',{},g);message('测试已排队，编号 '+data.test_id+'。请在微信实际确认是否收到。');});
    el('wechatUnbind').onclick=()=>action(async g=>{
      if(!confirm('解绑此学生的微信并清空待发通知？其他学生保持不变。'))return;
      await request('unbind',{},g);busy=false;await refresh(g);
    });
    el('wechatModal').addEventListener('click',e=>{if(e.target===el('wechatModal'))close();});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&current(generation)){e.preventDefault();close();}});
    document.addEventListener('buaa:surfacechange',e=>{if(e.detail?.id==='wechatModal'&&!e.detail.visible){clearTimeout(timer);controller?.abort();}});
  });
})();
