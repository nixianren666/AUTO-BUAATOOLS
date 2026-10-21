/* TD uses the existing account/session system. Local status reads never punch. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let data = null, owner = '', generation = 0, requestId = 0, controller = null;
  let timer = null, gallerySignature = '', modalOwner = '', busy = false, manualPhase = 'entry';
  let entrance = false, accessPending = false, accessState = null, accessId = 0, accessController = null, expiryTimer = null;
  const selected = new Set();
  const visible = () => appState.currentMainView === 'td' && !document.hidden && window.BUAARenderLifecycle?.visible !== false;
  const current = (user, gen) => user === appState.activeUsername && user === owner && gen === generation;
  const text = (id, value) => { if ($(id)) $(id).textContent = value; };
  const url = (path, user) => '/api/td/' + path + (path.includes('?') ? '&' : '?') + new URLSearchParams({username: user});
  const licensed = state => state?.active === true && Number(state.expires_epoch) * 1000 > Date.now();
  function entranceControls() {
    document.querySelectorAll('[data-td-close="tdLicenseModal"]').forEach(el => { el.hidden = entrance; el.classList.toggle('hidden', entrance); });
    $('tdLicenseBack').hidden = !entrance; $('tdLicenseBack').classList.toggle('hidden', !entrance);
    text('tdLicenseTitle', entrance ? 'TD · 激活后进入' : 'TD · 离线激活与续期');
    text('tdLicenseAccessState', accessPending ? '正在核验当前学生的本机授权…' : accessState?.reason || (licensed(accessState) ? '当前学生的 TD 已激活' : '当前学生尚未激活，请先完成离线激活。'));
    const mayRenew = accessState?.renewable === true || !licensed(accessState);
    if (licensed(accessState)) text('tdLicenseAccessState', accessState.renewable === true ? '当前学生已激活，已进入续期窗口；请使用新的激活码，原到期时间后的剩余权益将保留。' : '当前学生已激活；仅在到期前24小时或到期后可使用新码续期。');
    $('tdLicenseRequestBtn').disabled = busy || accessPending || !mayRenew;
    $('tdLicenseActivateBtn').disabled = busy || accessPending || !mayRenew;
    $('navBtnTD').setAttribute('aria-busy', String(accessPending));
  }
  function leave() {
    entrance = false; accessPending = false; accessId++; accessController?.abort();
    clearTimeout(expiryTimer); entranceControls(); setUISurface('tdLicenseModal', false);
  }
  function watchExpiry() {
    clearTimeout(expiryTimer);
    if (appState.currentMainView !== 'td' || !accessState) return;
    const remaining = Number(accessState.expires_epoch) * 1000 - Date.now();
    expiryTimer = setTimeout(() => { if (appState.currentMainView === 'td') enter(); }, Math.max(1, Math.min(remaining + 50, 2147483647)));
  }
  function admit() {
    if (!licensed(accessState)) return;
    entrance = false; entranceControls(); setUISurface('tdLicenseModal', false);
    showMainView('td'); watchExpiry();
  }
  function showEntranceCard() {
    accessPending = false;
    if (appState.currentMainView === 'td') showMainView('regular');
    entranceControls();
    if (!setUISurface('tdLicenseModal', true)) { entrance = false; entranceControls(); }
  }
  async function enter() {
    if (accessPending) return;
    if (!$('disclaimerModal').classList.contains('hidden')) return;
    if (!appState.activeUsername) { showToast('请先添加并选择学生账号，再激活 TD', 'info'); openAccountCardsModal(); return; }
    if (owner !== appState.activeUsername) changedAccount();
    controller?.abort(); requestId++; clearTimeout(timer); clearTimeout(expiryTimer);
    // Keep the previous workspace visible; never render the locked TD screen.
    if (appState.currentMainView === 'td' && !licensed(accessState)) showMainView('regular');
    entrance = true; accessPending = true; accessState = null; modalOwner = owner;
    $('tdLicenseRequest').value = ''; $('tdLicenseCode').value = ''; text('tdLicenseError', '');
    entranceControls();
    const user = owner, gen = generation, id = ++accessId;
    accessController?.abort(); accessController = new AbortController();
    const local = accessController, timeout = setTimeout(() => local.abort(), 12000);
    try {
      const result = await request('license/status', user, 'GET', undefined, local.signal);
      if (!current(user, gen) || id !== accessId || !entrance) return;
      accessState = result.license;
      if (licensed(accessState)) admit();
      else showEntranceCard();
    } catch (error) {
      if (current(user, gen) && id === accessId && entrance) {
        text('tdLicenseError', '授权核验未完成，TD 页面保持锁定。' + (error.name === 'AbortError' ? '请检查本地服务后重试。' : error.message));
        showEntranceCard();
      }
    } finally {
      clearTimeout(timeout);
      if (current(user, gen) && id === accessId) { accessPending = false; entranceControls(); }
    }
  }
  window.BUAATDAccess = {
    enter, leave,
    blocksSurface: (id, opening) => {
      if (entrance && accessPending) {
        if (opening && id !== 'tdLicenseModal') leave();
        return false;
      }
      return entrance && (id === 'tdLicenseModal' ? !opening : opening && id !== 'disclaimerModal');
    }
  };
  async function request(path, user, method = 'GET', body, signal) {
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), 30000);
    const options = {method, signal: signal || timeout.signal};
    if (body !== undefined) {
      options.headers = {'Content-Type': 'application/json'};
      options.body = JSON.stringify(body);
    }
    try { return await (await apiFetch(url(path, user), options)).json(); }
    finally { clearTimeout(timer); }
  }
  function schedule() {
    clearTimeout(timer);
    if (visible() && owner) timer = setTimeout(refresh, 15000);
  }
  function changedAccount() {
    if (owner !== appState.activeUsername) {
      const returnToTD = appState.currentMainView === 'td' || entrance;
      leave(); accessState = null;
      if (appState.currentMainView === 'td') showMainView('regular');
      owner = appState.activeUsername; generation++; requestId++;
      controller?.abort(); data = null; gallerySignature = ''; selected.clear(); busy = false;
      ['tdSettingsModal', 'tdCountModal', 'tdGroupModal', 'tdManualModal', 'tdLicenseModal'].forEach(id => setUISurface(id, false));
      $('tdGallery').replaceChildren();
      text('tdUploadStatus', ''); $('tdLicenseRequest').value='';$('tdLicenseCode').value='';text('tdLicenseError','');render();
      if (returnToTD && owner) { enter(); return; }
    }
    if (visible()) refresh(); else schedule();
  }
  async function refresh() {
    clearTimeout(timer);
    if (!visible() || !owner || busy) { schedule(); return; }
    controller?.abort(); controller = new AbortController();
    const user = owner, gen = generation, id = ++requestId;
    const localController = controller;
    const timeout = setTimeout(() => localController.abort(), 12000);
    try {
      const result = await request('status', user, 'GET', undefined, controller.signal);
      if (!current(user, gen) || id !== requestId) return;
      if (!licensed(result.license)) { accessState = result.license; data = null; render(); enter(); return; }
      data = result; accessState = result.license; render(); watchExpiry();
    } catch (error) {
      if (current(user, gen) && id === requestId && error.name !== 'AbortError') text('tdTaskText', '本地状态读取失败，保留上次显示；' + error.message);
    } finally { clearTimeout(timeout); schedule(); }
  }
  function progress(id, fill, count, total) {
    const known = Number.isInteger(count), percent = known ? Math.min(100, Math.max(0, count / total * 100)) : 0;
    $(fill).style.width = percent + '%';
    $(id).setAttribute('aria-valuemin', '0'); $(id).setAttribute('aria-valuemax', total);
    if (known) $(id).setAttribute('aria-valuenow', count); else $(id).removeAttribute('aria-valuenow');
    $(id).setAttribute('aria-valuetext', known ? count + ' / ' + total : '待核对');
  }
  function render() {
    const authorized = !!data?.license?.active, enabled = !!data?.settings.enabled && authorized, hasUser = !!owner;
    text('tdLicenseState', authorized ? `TD 已激活 · 至 ${data.license.expires_at.replace('T',' ').slice(0,16)}（北京时间）` : data?.license?.reason || 'TD 离线授权 · 未激活');
    $('tdLicenseBtn').disabled=!hasUser||busy||!data;
    entranceControls();
    text('tdIdentity', hasUser ? `当前学生：${appState.activeUser?.name || owner} · 与学生账号中心一致` : '请先在学生账号中心添加账号，无需单独登录 TD');
    text('tdDaemonStatus', !hasUser ? '尚未添加学生账号' : enabled ? (data.rules_valid ? 'TD 自动守护已开启' : 'TD 规则待核对，未执行') : 'TD 自动守护已暂停');
    $('tdDaemonDot').className = 'origin-status-dot' + (enabled ? ' green' : '');
    $('tdAutoToggle').checked = enabled; $('tdAutoToggle').disabled = !hasUser || !data || busy || !authorized || (!enabled&&(!data.rules_valid||!data.groups?.length));
    for (const id of ['tdSettingsBtn','tdCountBtn','tdRefreshBtn','tdSettingsSave','tdCountSave','tdGroupSave','tdManualSave']) $(id).disabled = !hasUser || busy || (!data && id !== 'tdRefreshBtn');
    $('tdDropzone').setAttribute('aria-disabled', String(!hasUser || busy));
    $('tdManualBtn').disabled = busy || !data?.manual?.allowed;
    text('tdManualBtn', data?.manual?.phase === 'exit' ? '手动配对出口' : '手动入口');
    $('tdManualBtn').title = data?.manual?.reason || '本人到场后手动提交当前步骤，与自动守护共用预算';
    const p = data?.settings, count = data?.progress.count;
    $('tdQuickCampusSelect').value = p?.campus || '学院路'; $('tdQuickCampusSelect').disabled = !data || busy; window.BUAAUiControls?.syncSelect($('tdQuickCampusSelect'));
    text('tdActivity', p?.confirmed ? `${p.start} — ${p.end} · ${data.activity_current ? '活动日期内' : '当前不在活动日期内'} · ${data.within_window ? '当前可执行时段' : '等待允许时段'}` : '先按本学期官方通知核对活动日期，再开启守护');
    if(data&&!data.rules_valid)text('tdActivity','规则待核对：'+data.rules_error);
    text('tdTermCount', Number.isInteger(count) ? String(count) : '—');
    text('tdTermTarget', ` / ${p?.target || 32} 次`);
    text('tdCountSource', !Number.isInteger(count) ? (data?.progress.count_source === 'out_of_scope' ? '本学期记录待核对 · 历史记录已保留' : '待核对 · 未读取到次数不等于零') : `${data.progress.count_source === 'server' ? '服务器返回，最终审核以学校为准' : '手动核对，仅本地展示'} · ${data.progress.count_at?.replace('T',' ').slice(0,19) || ''}`);
    const completed = data?.today.completed || 0;
    text('tdTodayCount', completed); text('tdTodayTarget', ` / ${p?.daily_limit || 3} 轮`);
    text('tdBudget', `已认领 ${data?.today.attempted || 0} 轮（含失败/不确定）；配对流程完成不等于学校最终有效次数`);
    progress('tdTermBar','tdTermFill',count,p?.target || 32); progress('tdTodayBar','tdTodayFill',completed,p?.daily_limit || 3);
    const state = data?.task.state;
    const labels = {idle:'等待下一轮',sending_entry:'入口请求处理中，禁止重复提交',sending_exit:'出口请求处理中，禁止重复提交',waiting_exit:'入口已接收，等待配对出口',uncertain:'结果待核验，已停止重发',rejected:'请求未接受，请核对官方记录',resolved:'已人工解除本地暂停，未补记成功'};
    const due = state === 'waiting_exit' && data.task.due ? ` · 预计 ${new Date(data.task.due * 1000).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})} 出口` : '';
    text('tdTaskText', data ? (data.task.note || labels[state] || '尚未开始') + due : hasUser ? '正在读取当前学生的本地状态…' : '添加账号后即可管理本人图库和进度');
    $('tdTaskDot').className = 'origin-status-dot' + (['uncertain','rejected','sending_entry','sending_exit'].includes(state) ? ' purple' : state === 'waiting_exit' ? ' cyan' : '');
    $('tdResolveBtn').classList.toggle('hidden', !['uncertain','rejected','sending_entry','sending_exit','waiting_exit'].includes(state));
    $('tdResolveBtn').disabled = busy;
    renderGallery();
  }
  function selection() {
    const available = [...$('tdGallery').querySelectorAll('input:not(:disabled)')];
    text('tdSelectionCount', selected.size ? `已选 ${selected.size} 组` : '未选择');
    $('tdDeleteBtn').disabled = !selected.size || busy;
    $('tdSelectAll').disabled = !available.length || busy;
    $('tdSelectAll').checked = !!available.length && selected.size === available.length;
    $('tdSelectAll').indeterminate = selected.size > 0 && selected.size < available.length;
  }
  function renderGallery() {
    const groups=data?.groups || [], images=data?.images || [];
    const signature=owner+':'+groups.map(g=>[g.id,g.entry_image,g.exit_image,g.name,g.in_use].join(':')).join('|');
    text('tdImageCount',`${groups.length} / 50 组 · 当前学生专属`);
    const referenced=new Set(groups.flatMap(g=>[g.entry_image,g.exit_image]));
    const legacy=images.filter(i=>!referenced.has(i.id));
    text('tdLegacyHint',legacy.length ? `${legacy.length} 张已有散图未配组，不参与自动任务；可用下方入口整理。` : '每轮固定使用一组的入口与出口照片，不跨组混选。');
    $('tdLegacyGroupBtn').classList.toggle('hidden',!legacy.length);
    if(signature!==gallerySignature) {
      gallerySignature=signature;
      const allowed=new Set(groups.filter(g=>!g.in_use).map(g=>g.id));
      [...selected].forEach(id=>{if(!allowed.has(id))selected.delete(id);});
      const fragment=document.createDocumentFragment();
      groups.forEach((group,index)=>{
        const card=document.createElement('label');card.className='td-photo';
        const input=document.createElement('input');input.type='checkbox';input.value=group.id;input.checked=selected.has(group.id);input.disabled=group.in_use;input.setAttribute('aria-label',`选择照片组 ${index+1}${group.in_use?'，使用中':''}`);
        input.addEventListener('change',()=>{if(input.checked)selected.add(group.id);else selected.delete(group.id);selection();});
        const pair=document.createElement('div');pair.className='td-pair-preview';
        for(const [role,id] of [['入口',group.entry_image],['出口',group.exit_image]]) {
          const frame=document.createElement('div');const img=document.createElement('img');img.src=url('images/'+encodeURIComponent(id),owner);img.alt=`${group.name} · ${role}照片`;img.loading='lazy';img.decoding='async';const caption=document.createElement('small');caption.textContent=role;frame.append(img,caption);pair.append(frame);
        }
        const caption=document.createElement('span');const label=document.createElement('span');label.textContent=group.name;const state=document.createElement('span');state.textContent=group.in_use?'配对 / 待核验占用':'已确认同穿搭';caption.append(label,state);
        card.append(pair,input,caption);fragment.append(card);
      });
      if(!groups.length){const empty=document.createElement('p');empty.className='td-caption';empty.textContent=owner?'还没有照片组，请按一组两张添加或整理已有散图':'请先在学生账号中心添加账号';fragment.append(empty);}
      $('tdGallery').replaceChildren(fragment);
      document.dispatchEvent(new CustomEvent('buaa:tdgallery'));
    }
    selection();
  }
  async function mutate(button, work) {
    if (busy || !owner) return;
    const user = owner, gen = generation;
    busy = true; controller?.abort(); requestId++; render(); button.disabled = true;
    try { await work(user, gen); }
    catch (error) { if (current(user, gen)) showToast(error.message, 'error'); }
    finally { if (current(user, gen)) { busy = false; render(); await refresh(); } }
  }
  function openSettings(campus) {
    if (!data) return;
    modalOwner = owner;
    const p = data.settings;
    $('tdCampusSelect').value = typeof campus === 'string' ? campus : p.campus; window.BUAAUiControls?.syncSelect($('tdCampusSelect'));
    $('tdSemesterStart').value = data.calendar?.[0] || p.semester_start; $('tdSemesterEnd').value = data.calendar?.[1] || p.semester_end; $('tdStart').value = p.start; $('tdEnd').value = p.end; text('tdCalendarSource',data.calendar ? '学期边界来自已同步官方校历；活动日期仍须按TD官方通知核对。' : '官方校历尚未同步，请手动核对学期边界；这不表示学校已验证活动日期。'); updateDateBounds();
    $('tdTarget').value = p.target; $('tdDailyLimit').value = p.daily_limit;
    $('tdWeekdays').querySelectorAll('input').forEach(input => { input.checked = (p.weekdays || []).includes(Number(input.value)); });
    $('tdClosedDates').value = (p.closed_dates || []).join('\n');
    $('tdConfirmed').checked = false; text('tdSettingsError',''); setUISurface('tdSettingsModal',true);
  }
  function updateDateBounds() {
    const start=$('tdSemesterStart').value,end=$('tdSemesterEnd').value;
    $('tdSemesterEnd').min=start;
    for(const id of ['tdStart','tdEnd']){$(id).min=start;$(id).max=end;}
    if($('tdStart').value && $('tdStart').value>start)$('tdEnd').min=$('tdStart').value;
  }
  const previews={};
  function clearPreviews(){for(const role of ['Entry','Exit']){if(previews[role])URL.revokeObjectURL(previews[role]);delete previews[role];$('td'+role+'Preview').removeAttribute('src');$('td'+role+'Preview').classList.add('hidden');}}
  function groupPreview(role){
    const existing=$('tdGroupUseLibrary').checked,img=$('td'+role+'Preview');
    if(previews[role])URL.revokeObjectURL(previews[role]);delete previews[role];
    let src='';if(existing){const id=$('td'+role+'Existing').value;if(id)src=url('images/'+encodeURIComponent(id),owner);}else{const file=$('td'+role+'File').files[0];if(file){src=URL.createObjectURL(file);previews[role]=src;}}
    if(src)img.src=src;else img.removeAttribute('src');img.classList.toggle('hidden',!src);
    $('td'+role+'Picker').classList.toggle('hidden',existing);
    text('td'+role+'Filename', $('td'+role+'File').files[0]?.name || 'JPEG / PNG / WebP · 每张不超过 8MB');
    const select=$('td'+role+'Existing');select.closest('.ui-select-shell')?.classList.toggle('hidden',!existing);
    if(!select.closest('.ui-select-shell'))select.classList.toggle('hidden',!existing);
    window.BUAAUiControls?.syncSelect(select);
  }
  function openGroup(files,existing=false){
    if(!owner||busy)return;
    modalOwner=owner;clearPreviews();$('tdGroupForm').reset();text('tdGroupError','');$('tdGroupUseLibrary').checked=existing;
    for(const [index,role] of ['Entry','Exit'].entries()){
      const select=$('td'+role+'Existing');select.replaceChildren();
      (data?.images||[]).forEach((image,i)=>{const option=document.createElement('option');option.value=image.id;option.textContent='已有照片 '+(i+1);select.append(option);});
      select.selectedIndex=Math.min(index,Math.max(0,select.options.length-1));
      if(files?.[index]){const transfer=new DataTransfer();transfer.items.add(files[index]);$('td'+role+'File').files=transfer.files;}
      groupPreview(role);
    }
    setUISurface('tdGroupModal',true);
  }
  async function saveGroup(event){
    event.preventDefault();if(modalOwner!==owner||busy)return;
    const existing=$('tdGroupUseLibrary').checked,name=$('tdGroupName').value.trim(),confirmed=$('tdGroupConfirmed').checked;
    const entry=$('tdEntryFile').files[0],exit=$('tdExitFile').files[0],entryId=$('tdEntryExisting').value,exitId=$('tdExitExisting').value;
    if(!confirmed||(!existing&&(!entry||!exit))||(existing&&(!entryId||!exitId))){text('tdGroupError','请提供入口和出口两张照片，并确认同穿搭、同妆容');return;}
    if(!existing&&[entry,exit].some(file=>!['image/jpeg','image/png','image/webp'].includes(file.type)||!file.size||file.size>8*1024*1024)){text('tdGroupError','每张需为JPEG/PNG/WebP且不超过8MB');return;}
    text('tdGroupError','');
    await mutate($('tdGroupSave'),async(user,gen)=>{
      try{
        if(existing)await request('groups/from-library',user,'POST',{entry_image:entryId,exit_image:exitId,name,confirmed});
        else{
          const meta=new TextEncoder().encode(JSON.stringify({name,confirmed,entry_size:entry.size,exit_size:exit.size}));
          const header=new Uint8Array(4);new DataView(header.buffer).setUint32(0,meta.length,false);
          await apiFetch(url('groups',user),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:new Blob([header,meta,entry,exit])});
        }
        if(current(user,gen)){setUISurface('tdGroupModal',false);text('tdUploadStatus','已保存一组入口 / 出口照片，可继续添加下一组');gallerySignature='';}
      }catch(error){if(current(user,gen))text('tdGroupError',error.message);}
    });
  }
  document.addEventListener('DOMContentLoaded', () => {
    $('tdLicenseBtn').addEventListener('click',()=>{
      if(!owner||busy||!data)return;accessState=data.license;modalOwner=owner;$('tdLicenseCode').value='';$('tdLicenseRequest').value='';text('tdLicenseError','');entranceControls();setUISurface('tdLicenseModal',true);
    });
    $('tdLicenseBack').addEventListener('click',()=>switchMainView('regular'));
    $('tdLicenseRequestBtn').addEventListener('click',()=>mutate($('tdLicenseRequestBtn'),async(user,gen)=>{
      try{const result=await request('license/request',user,'POST',{});if(current(user,gen))$('tdLicenseRequest').value=result.request;}
      catch(error){if(current(user,gen))text('tdLicenseError',error.message);}
    }));
    $('tdLicenseCopyBtn').addEventListener('click',async()=>{
      const field=$('tdLicenseRequest');if(!field.value)return;
      try{await navigator.clipboard.writeText(field.value);text('tdLicenseError','已复制申请码，请通过你认可的渠道交给维护者');}
      catch{field.focus();field.select();text('tdLicenseError','请按 Ctrl+C 复制已选中的申请码');}
    });
    $('tdLicenseForm').addEventListener('submit',async e=>{
      e.preventDefault();if(modalOwner!==owner||busy)return;const code=$('tdLicenseCode').value.trim();text('tdLicenseError','');
      await mutate($('tdLicenseActivateBtn'),async(user,gen)=>{
        try{const result=await request('license/activate',user,'POST',{code});if(current(user,gen)){if(!licensed(result.license))throw new Error('授权尚未生效，请核对系统时间及激活结果');accessState=result.license;if(data)data.license=result.license;$('tdLicenseCode').value='';$('tdLicenseRequest').value='';if(entrance)admit();else setUISurface('tdLicenseModal',false);showToast('TD离线授权已激活','success');}}
        catch(error){if(current(user,gen))text('tdLicenseError',error.message);}
      });
    });
    ['一','二','三','四','五','六','日'].forEach((name,index)=>{
      const label=document.createElement('label'),input=document.createElement('input');
      input.type='checkbox';input.value=String(index);label.append(input,document.createTextNode('周'+name));$('tdWeekdays').append(label);
    });
    for(const role of ['Entry','Exit'])$('td'+role+'Picker').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('td'+role+'File').click();}});
    $('tdManualBtn').addEventListener('click',()=>{
      if(busy||!data?.manual?.allowed)return;
      modalOwner=owner;manualPhase=data.manual.phase;
      text('tdManualTitle',manualPhase==='exit'?'TD · 手动配对出口':'TD · 手动入口');
      text('tdManualDesc',manualPhase==='exit'?'将使用本轮已固定的出口照片与设备完成配对，不另选照片组。':'将认领一轮今日预算，并固定本轮入口 / 出口照片组。提交后请按提示完成配对出口。');
      $('tdManualConfirmed').checked=false;text('tdManualError','');setUISurface('tdManualModal',true);
    });
    $('tdManualForm').addEventListener('submit',async e=>{
      e.preventDefault();if(modalOwner!==owner||busy)return;
      const payload={phase:manualPhase,confirmed:$('tdManualConfirmed').checked};text('tdManualError','');
      await mutate($('tdManualSave'),async(user,gen)=>{try{await request('manual',user,'POST',payload);if(current(user,gen))setUISurface('tdManualModal',false);}catch(error){if(current(user,gen))text('tdManualError',error.message);}});
    });
    $('tdSettingsBtn').addEventListener('click',()=>openSettings());
    $('tdQuickCampusSelect').addEventListener('change',()=>{const campus=$('tdQuickCampusSelect').value;$('tdQuickCampusSelect').value=data?.settings.campus||'学院路';window.BUAAUiControls?.syncSelect($('tdQuickCampusSelect'));openSettings(campus);});
    for(const id of ['tdSemesterStart','tdSemesterEnd','tdStart'])$(id).addEventListener('input',updateDateBounds);
    $('tdGroupForm').addEventListener('submit',saveGroup);
    $('tdLegacyGroupBtn').addEventListener('click',()=>openGroup(null,true));
    $('tdGroupUseLibrary').addEventListener('change',()=>{groupPreview('Entry');groupPreview('Exit');});
    for(const role of ['Entry','Exit'])for(const suffix of ['File','Existing'])$('td'+role+suffix).addEventListener('change',()=>groupPreview(role));
    document.addEventListener('buaa:surfacechange',e=>{if(e.detail?.id==='tdGroupModal'&&!e.detail.visible)clearPreviews();});
    $('tdRefreshBtn').addEventListener('click',refresh);
    $('tdAutoToggle').addEventListener('change', e => { const enabled=e.target.checked; mutate(e.target, (user) => request('toggle',user,'POST',{enabled})); });
    $('tdCountBtn').addEventListener('click', () => { modalOwner=owner; $('tdVerifiedCount').value=data?.progress.count ?? ''; text('tdCountError',''); setUISurface('tdCountModal',true); });
    $('tdResolveBtn').addEventListener('click', e => { if (confirm('请先在官方记录核实结果，并等待配对结束。解除仅消除本地暂停，不补记成功、不返还请求预算。确认已核对？')) mutate(e.target,user => request('resolve',user,'POST',{verified:true})); });
    for (const [form, button, errorId, endpoint, body] of [
      ['tdSettingsForm','tdSettingsSave','tdSettingsError','settings', () => ({campus:$('tdCampusSelect').value,start:$('tdStart').value,end:$('tdEnd').value,semester_start:$('tdSemesterStart').value,semester_end:$('tdSemesterEnd').value,target:Number($('tdTarget').value),daily_limit:Number($('tdDailyLimit').value),confirmed:$('tdConfirmed').checked,weekdays:[...$('tdWeekdays').querySelectorAll('input:checked')].map(input=>Number(input.value)),closed_dates:$('tdClosedDates').value.trim().split(/[\s,，]+/).filter(Boolean)})],
      ['tdCountForm','tdCountSave','tdCountError','count',() => ({count:Number($('tdVerifiedCount').value)})]
    ]) $(form).addEventListener('submit', async e => {
      e.preventDefault(); if (modalOwner !== owner) return;
      const payload=body(); text(errorId,'');
      await mutate($(button),async (user,gen) => { try { await request(endpoint,user,'POST',payload); if (current(user,gen) && modalOwner===user) setUISurface(endpoint==='settings'?'tdSettingsModal':'tdCountModal',false); } catch(error) { if(current(user,gen)) text(errorId,error.message); } });
    });
    document.querySelectorAll('[data-td-close]').forEach(button => button.addEventListener('click', () => setUISurface(button.dataset.tdClose,false)));
    ['tdSettingsModal','tdCountModal','tdGroupModal','tdManualModal','tdLicenseModal'].forEach(id => $(id).addEventListener('click',e => { if(e.target === $(id)) setUISurface(id,false); }));
    document.addEventListener('keydown',e => { if (e.key === 'Escape') ['tdSettingsModal','tdCountModal','tdGroupModal','tdManualModal','tdLicenseModal'].forEach(id => setUISurface(id,false)); });
    $('tdSelectAll').addEventListener('change', e => { $('tdGallery').querySelectorAll('input:not(:disabled)').forEach(input => { input.checked=e.target.checked; if(input.checked)selected.add(input.value);else selected.delete(input.value); }); selection(); });
    $('tdDeleteBtn').addEventListener('click',e => { const ids=[...selected]; if (ids.length && confirm(`删除当前学生所选的 ${ids.length} 组本地入口 / 出口照片？此操作不可撤销。`)) mutate(e.target,async (user,gen) => { const result=await request('groups',user,'DELETE',{ids}); if (current(user,gen)) {selected.clear();gallerySignature='';if(result.cleanup_pending)showToast('已从图库移除；部分私有临时文件被系统占用，尚未完成磁盘清理','warning');} }); });
    const zone=$('tdDropzone');
    function choose() { if(owner && !busy) openGroup(); }
    zone.addEventListener('click',choose); zone.addEventListener('keydown',e => {if(['Enter',' '].includes(e.key)){e.preventDefault();choose();}});
    zone.addEventListener('dragover',e => {e.preventDefault();if(owner&&!busy)zone.classList.add('td-dragover');});
    zone.addEventListener('dragleave',() => zone.classList.remove('td-dragover'));
    zone.addEventListener('drop',e => {e.preventDefault();zone.classList.remove('td-dragover');if(owner&&!busy){const files=[...e.dataTransfer.files];if(files.length!==2)showToast('每次请拖入一组两张照片，再核对入口和出口','info');else openGroup(files);}});

    changedAccount();
  });
  document.addEventListener('buaa:accountview',changedAccount);
  document.addEventListener('buaa:mainview',() => { if(visible())refresh();else{controller?.abort();schedule();} });
  document.addEventListener('visibilitychange',() => {if(visible())refresh();else{controller?.abort();schedule();}});
  addEventListener('buaa:renderstate',() => {if(visible())refresh();else{controller?.abort();schedule();}});
})();
