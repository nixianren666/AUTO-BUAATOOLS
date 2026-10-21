/* Local, keyboard-accessible date presentation. No network or rule changes. */
(() => {
  'use strict';
  const widgets=new Map();let active=null;
  const iso=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  function parse(s){if(!/^\d{4}-\d{2}-\d{2}$/.test(s||''))return null;const d=new Date(s+'T12:00:00');return !isNaN(d)&&iso(d)===s?d:null;}
  const shift=(d,n)=>new Date(d.getFullYear(),d.getMonth(),d.getDate()+n,12);
  function close(restore=false){if(!active)return;const w=active;active=null;w.panel.remove();w.button.setAttribute('aria-expanded','false');if(restore&&!w.button.closest('.hidden,[inert]'))w.button.focus({preventScroll:true});}
  function available(w,d){const s=iso(d);return (!w.input.min||s>=w.input.min)&&(!w.input.max||s<=w.input.max);}
  function select(w,d){w.input.value=d?iso(d):'';w.input.dispatchEvent(new Event('input',{bubbles:true}));w.input.dispatchEvent(new Event('change',{bubbles:true}));close(true);}
  function make(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e;}
  function button(label,action){const e=make('button','origin-btn origin-btn-ghost',label);e.type='button';e.addEventListener('click',action);return e;}
  function render(w,focus=false){
    const panel=w.panel;panel.replaceChildren();const year=w.month.getFullYear(),month=w.month.getMonth();
    const header=make('div','td-calendar-head');
    const prev=button('‹',()=>{w.month=new Date(year,month-1,1,12);render(w,true);});prev.setAttribute('aria-label','上个月');
    const next=button('›',()=>{w.month=new Date(year,month+1,1,12);render(w,true);});next.setAttribute('aria-label','下个月');
    prev.disabled=!!w.input.min&&iso(new Date(year,month,0,12))<w.input.min;
    next.disabled=!!w.input.max&&iso(new Date(year,month+1,1,12))>w.input.max;
    const title=make('strong','',`${year} 年 ${month+1} 月`);title.setAttribute('aria-live','polite');header.append(prev,title,next);panel.append(header);
    const grid=make('div','td-calendar-grid');grid.setAttribute('role','grid');grid.setAttribute('aria-label',title.textContent);
    for(const name of ['一','二','三','四','五','六','日']){const e=make('span','td-calendar-week',name);e.setAttribute('aria-hidden','true');grid.append(e);}
    const start=new Date(year,month,1,12),offset=(start.getDay()+6)%7;
    for(let n=0;n<42;n++){
      const date=shift(start,n-offset),value=iso(date),cell=button(String(date.getDate()),()=>select(w,date));
      cell.className='td-calendar-day';cell.dataset.date=value;cell.setAttribute('aria-label',value);cell.setAttribute('role','gridcell');cell.setAttribute('aria-selected',String(w.input.value===value));
      cell.disabled=!available(w,date);cell.tabIndex=-1;
      if(date.getMonth()!==month)cell.classList.add('td-calendar-other');
      if(iso(new Date())===value)cell.setAttribute('aria-current','date');grid.append(cell);
    }
    panel.append(grid);const foot=make('div','td-calendar-footer');const today=button('今天',()=>select(w,new Date()));today.disabled=!available(w,new Date());foot.append(button('清除',()=>select(w,null)),today);panel.append(foot);
    const target=grid.querySelector(`[data-date="${w.cursor}"]:not(:disabled)`)||grid.querySelector(`:not(.td-calendar-other).td-calendar-day:not(:disabled)`)||grid.querySelector('.td-calendar-day:not(:disabled)');
    if(target){target.tabIndex=0;w.cursor=target.dataset.date;if(focus)target.focus({preventScroll:true});}else if(focus)title.tabIndex=0,title.focus();
    const r=w.button.getBoundingClientRect();w.anchor={top:r.top,left:r.left};panel.style.width=Math.min(300,innerWidth-24)+'px';const h=panel.getBoundingClientRect().height;
    panel.style.left=Math.max(12,Math.min(r.right-300,innerWidth-panel.offsetWidth-12))+'px';panel.style.top=Math.max(12,Math.min(r.bottom+8,innerHeight-h-12))+'px';
  }
  function open(w){
    if(w.input.disabled)return;if(active===w){close(true);return;}window.BUAAUiControls?.closeSelect();close();
    for(let p=w.button.parentElement;p;p=p.parentElement)for(const a of p.getAnimations?.()||[])try{a.finish();}catch{}
    const date=parse(w.input.value)||parse(w.input.min)||new Date();w.month=new Date(date.getFullYear(),date.getMonth(),1,12);w.cursor=iso(date);
    w.panel=make('div','td-calendar');w.panel.setAttribute('role','dialog');w.panel.setAttribute('aria-label',w.caption+'日历');w.panel.id=w.input.id+'Calendar';
    document.getElementById('tdSettingsModal').append(w.panel);active=w;w.button.setAttribute('aria-expanded','true');render(w,true);
    if(typeof w.panel.animate==='function'&&!matchMedia('(prefers-reduced-motion: reduce)').matches)w.panel.animate([{opacity:0,transform:'translateY(4px)'},{opacity:1,transform:'none'}],{duration:180,easing:'ease-out'});
  }
  document.addEventListener('DOMContentLoaded',()=>{
    for(const id of ['tdSemesterStart','tdSemesterEnd','tdStart','tdEnd']){
      const input=document.getElementById(id);if(!input)continue;
      input.type='text';input.placeholder='YYYY-MM-DD';input.pattern='[0-9]{4}-[0-9]{2}-[0-9]{2}';input.inputMode='numeric';input.maxLength=10;
      const shell=make('div','td-date-shell'),caption=document.querySelector(`label[for="${id}"]`).textContent;
      const trigger=button('▦',()=>open(w));trigger.className='td-date-trigger';trigger.setAttribute('aria-label','选择'+caption);trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-controls',id+'Calendar');
      const w={input,button:trigger,caption};widgets.set(id,w);input.before(shell);shell.append(input,trigger);
      input.addEventListener('keydown',e=>{if(e.key==='ArrowDown'&&e.altKey){e.preventDefault();open(w);}});
    }
  });
  document.addEventListener('keydown',e=>{
    if(!active)return;const w=active;
    if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close(true);return;}
    if(!e.target.matches('.td-calendar-day'))return;
    const date=parse(e.target.dataset.date);let next;
    const deltas={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};
    if(e.key in deltas)next=shift(date,deltas[e.key]);
    else if(e.key==='Home')next=shift(date,-(date.getDay()+6)%7);
    else if(e.key==='End')next=shift(date,6-(date.getDay()+6)%7);
    else if(['PageUp','PageDown'].includes(e.key))next=new Date(date.getFullYear(),date.getMonth()+(e.key==='PageUp'?-1:1),Math.min(date.getDate(),28),12);
    if(next){e.preventDefault();if(!available(w,next))return;w.cursor=iso(next);w.month=new Date(next.getFullYear(),next.getMonth(),1,12);render(w,true);}
  },true);
  document.addEventListener('pointerdown',e=>{if(active&&!active.panel.contains(e.target)&&!active.button.contains(e.target))close();},true);
  document.addEventListener('buaa:surfacechange',()=>close());
  document.addEventListener('visibilitychange',()=>{if(document.hidden)close();});
  addEventListener('buaa:renderstate',()=>{if(window.BUAARenderLifecycle?.visible===false)close();});
  addEventListener('resize',()=>close());
  document.addEventListener('scroll',e=>{
    if(!active||active.panel.contains(e.target))return;
    const r=active.button.getBoundingClientRect(),anchor=active.anchor;
    // Ignore a queued pre-open scroll event; close only when the anchor moved.
    if(anchor&&(Math.abs(r.top-anchor.top)>1||Math.abs(r.left-anchor.left)>1))close();
  },true);
})();
