"""Per-student WeChat notification workers, independent of school task locks."""
import asyncio
from collections import deque
import copy
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import tempfile
import time

from core import vault
from core.wechat_protocol import BASE_URL, WechatError, WechatProtocol, trusted_base


class WechatNotifications:
    def __init__(self, path, account_exists, protocol=None):
        self.path = Path(path)
        self.account_exists = account_exists
        self.protocol = protocol or WechatProtocol()
        self.bindings = {}
        self.pending = {}
        self.queues = {}
        self.results = {}
        self.health = {}
        self.tasks = {}
        self.lock = asyncio.Lock()
        self.gates = {}
        self.incoming = queue.Queue(maxsize=2048)
        self.seen = {}
        self.closed = False
        self.drain_task = None
        self.storage_error = False

    def _read(self):
        if self.path.is_symlink(): raise ValueError('微信私有文件不可为链接')
        try: raw = self.path.read_text(encoding='utf-8')
        except FileNotFoundError: return {}
        if len(raw)>2097152: raise ValueError('微信私有文件过大')
        data=json.loads(vault.decrypt(raw))
        if data.get('version') != 1 or not isinstance(data.get('bindings'),dict): raise ValueError('微信私有文件损坏')
        if len(data['bindings'])>1000:raise ValueError('微信私有文件损坏')
        for username,binding in data['bindings'].items():
            if not isinstance(username,str) or not 0<len(username)<=128 or not isinstance(binding,dict):raise ValueError('微信私有文件损坏')
            for field,limit in (('token',8192),('bot',8192),('peer',8192),('context',8192),('cursor',65536)):
                value=binding.get(field)
                if not isinstance(value,str) or len(value)>=limit or (field in ('token','bot','peer') and not value):raise ValueError('微信私有文件损坏')
            trusted_base(binding.get('base'))
            if not re.fullmatch('[a-fA-F0-9]{32}',str(binding.get('generation',''))):raise ValueError('微信私有文件损坏')
            if any(type(binding.get(key)) is not bool for key in ('enabled','important_only')):raise ValueError('微信私有文件损坏')
            pause=binding.get('paused_until')
            if type(pause) not in (float,int) or not math.isfinite(pause) or pause<0:raise ValueError('微信私有文件损坏')
        return data['bindings']

    def _write(self, bindings):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        raw=vault.encrypt(json.dumps({'version':1,'bindings':bindings},ensure_ascii=False))
        fd, temp=tempfile.mkstemp(prefix='.wechat-',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.chmod(temp,0o600)
            if self.path.is_symlink():raise ValueError('微信私有文件不可为链接')
            os.replace(temp,self.path)
        finally:
            if os.path.exists(temp):os.unlink(temp)

    async def save(self, bindings):
        # Cancellation cannot release the storage lock while a thread is still
        # replacing the same file (unbind/shutdown may cancel a polling worker).
        job=asyncio.create_task(asyncio.to_thread(self._write,bindings))
        try:await asyncio.shield(job)
        except asyncio.CancelledError:
            try:await job
            finally:raise
        except Exception:
            self.storage_error=True
            raise ValueError('微信绑定保存失败，请检查私有目录；没有继续发送') from None
        self.bindings=bindings;self.storage_error=False

    async def start(self):
        self.closed=False
        if isinstance(self.protocol,WechatProtocol) and self.protocol.client.is_closed:
            self.protocol=WechatProtocol()
        try:self.bindings=await asyncio.to_thread(self._read)
        except Exception:self.storage_error=True;self.bindings={}
        for username in self.bindings:
            if self.account_exists(username):self.launch(username)
        self.drain_task=asyncio.create_task(self.drain())

    def launch(self, username):
        self.queues.setdefault(username,deque(maxlen=100))
        if username in self.tasks:return
        self.tasks[username]=[asyncio.create_task(self.poll(username)),asyncio.create_task(self.sender(username))]

    async def stop(self):
        self.closed=True
        tasks=[task for pair in self.tasks.values() for task in pair]
        if self.drain_task:tasks.append(self.drain_task)
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.tasks.clear();self.drain_task=None
        await self.protocol.close()

    def offer(self, entry):
        # Called by arbitrary school scheduler threads: never perform I/O here.
        if not entry.get('username') or self.closed:return
        binding=self.bindings.get(entry['username'])
        if not binding or not binding.get('enabled'):return
        safe={k:str(entry.get(k,''))[:2048] for k in ('username','level','category','message','time')}
        safe['generation']=binding['generation']
        try:self.incoming.put_nowait(safe)
        except queue.Full:pass

    @staticmethod
    def text(entry):
        message=entry['message'].replace(entry['username'],'[本人]')
        message=re.sub(r'https?://\S+','[链接已隐藏]',message)
        message=re.sub(r'''(?i)(password|passwd|token|cookie|authorization|密码|口令|验证码|恢复码)["']?\s*[:：=]\s*(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)''',r'\1：[已隐藏]',message)
        message=re.sub(r'(?i)\bBearer\s+\S+','Bearer [已隐藏]',message)
        message=re.sub(r'\bTD[LQ]1[.A-Za-z0-9_-]+','[TD凭据已隐藏]',message)
        message=re.sub(r'\b\d{8,}\b','[标识已隐藏]',message)
        message=''.join(c for c in message if c in '\n\t' or ord(c)>=32)[:650]
        category={'regular':'常规课堂','boya':'博雅','td':'TD'}.get(entry['category'],'应用')
        level={'error':'❌ 需要处理','warning':'⚠️ 请留意','success':'✅ 操作结果','info':'ℹ️ 运行动态'}.get(entry['level'],'ℹ️ 运行动态')
        guidance='\n请打开应用核对结果和提示；微信消息不会替你重试学校操作。' if entry['level'] in ('error','warning') else ''
        stamp=entry.get('time','')
        stamp=stamp if re.fullmatch(r'\d{2}:\d{2}:\d{2}',stamp) else '--:--:--'
        return f'{level} · {category}\n{datetime.datetime.now().strftime("%m-%d")} {stamp}\n{message}{guidance}'

    async def drain(self):
        while not self.closed:
            now=time.monotonic()
            for username, pending in list(self.queues.items()):
                while pending and now-pending[0][0]>600:
                    self.record(username,pending.popleft()[1],'expired')
            for _ in range(100):
                try:entry=self.incoming.get_nowait()
                except queue.Empty:break
                username=entry['username'];binding=self.bindings.get(username)
                if not binding or binding['generation']!=entry['generation'] or not binding.get('enabled') or not self.account_exists(username):continue
                if binding.get('important_only') and entry['level'] not in ('error','warning','success'):continue
                if entry['level']=='debug':continue
                identity=hashlib.sha256((username+entry['category']+entry['level']+entry['message']).encode()).hexdigest()
                now=time.monotonic()
                if now-self.seen.get(identity,-1e10)<60:continue
                self.seen[identity]=now
                if len(self.seen)>4096:self.seen={k:v for k,v in self.seen.items() if now-v<60}
                self.queues.setdefault(username,deque(maxlen=100)).append((now,secrets.token_hex(16),self.text(entry),binding['generation']))
            await asyncio.sleep(.25)

    async def begin(self, username):
        async with self.lock:
            if self.storage_error:raise ValueError('微信私有存储不可用，请先检查部署目录')
            if username in self.bindings:raise ValueError('请先解绑当前微信，再绑定新的微信')
            if len(self.pending)>=64: self.pending={u:p for u,p in self.pending.items() if time.monotonic()-p['created']<300}
            if len(self.pending)>=64:raise ValueError('绑定请求较多，请稍后重试')
            generation=secrets.token_hex(16)
            self.pending[username]={'id':generation,'created':time.monotonic(),'base':BASE_URL,'busy':True}
        try:
            data=await self.protocol.qrcode()
            qr,image=data.get('qrcode'),data.get('qrcode_img_content')
            if not isinstance(qr,str) or not 0<len(qr)<=4096 or not isinstance(image,str) or not 0<len(image.encode('utf-8'))<=2048:raise WechatError()
            async with self.lock:
                current=self.pending.get(username)
                if not current or current['id']!=generation or not self.account_exists(username):raise ValueError('账号或绑定请求已变化')
                current.update(qr=qr,image=image,busy=False)
            return {'binding_id':generation,'status':'wait'}
        except Exception:
            async with self.lock:
                if self.pending.get(username,{}).get('id')==generation:self.pending.pop(username,None)
            raise

    async def wait(self, username, binding_id, verify_code=None):
        async with self.lock:
            pending=self.pending.get(username)
            if not pending or pending['id']!=binding_id:raise ValueError('绑定请求不存在，请重新生成二维码')
            if time.monotonic()-pending['created']>=300:
                self.pending.pop(username,None);return {'status':'expired'}
            if pending['busy']:raise ValueError('正在核对二维码，请等待')
            pending['busy']=True;snapshot=dict(pending)
        try:
            data=await self.protocol.qr_status(snapshot['qr'],snapshot['base'],verify_code)
            async with self.lock:
                pending=self.pending.get(username)
                if not pending or pending['id']!=binding_id or not self.account_exists(username):raise ValueError('账号或绑定请求已变化')
                status=data.get('status','wait')
                if status=='scaned_but_redirect':
                    host=data.get('redirect_host','')
                    pending['base']=trusted_base(host if host.startswith('https://') else 'https://'+host)
                if status=='confirmed':
                    token,bot,peer=data.get('bot_token'),data.get('ilink_bot_id'),data.get('ilink_user_id')
                    if not all(isinstance(v,str) and 0<len(v)<8192 for v in (token,bot,peer)):raise WechatError()
                    if any(b['bot']==bot or b['peer']==peer for b in self.bindings.values()):raise ValueError('这个微信已经绑定其他学生，不能重复绑定')
                    binding={'token':token,'bot':bot,'peer':peer,'base':trusted_base(data.get('baseurl') or BASE_URL),
                        'generation':binding_id,'cursor':'','context':'','enabled':True,'important_only':False,'paused_until':0}
                    await self.save(dict(self.bindings,**{username:binding}))
                    self.pending.pop(username,None);self.launch(username)
                    return {'status':'confirmed','message':'请在微信中向机器人发送“开始接收”，再点击发送测试。'}
                if status in ('expired','verify_code_blocked'):self.pending.pop(username,None)
                return {'status':status if status in ('wait','scaned','expired','need_verifycode','verify_code_blocked','binded_redirect','scaned_but_redirect') else 'wait'}
        finally:
            async with self.lock:
                if self.pending.get(username,{}).get('id')==binding_id:self.pending[username]['busy']=False

    def qr_content(self, username, binding_id):
        p=self.pending.get(username,{})
        if p.get('id')!=binding_id or time.monotonic()-p['created']>=300:raise ValueError('二维码已过期')
        return p.get('image','')

    async def remove(self, username):
        async with self.gates.setdefault(username,asyncio.Lock()), self.lock:
            self.pending.pop(username,None)
            for task in self.tasks.pop(username,[]):task.cancel()
            self.queues.pop(username,None);self.results.pop(username,None)
            self.health.pop(username,None)
            if username in self.bindings:
                updated=dict(self.bindings);updated.pop(username)
                # Stop this process even if disk is full. Report that removal
                # was not persisted rather than silently resuming notifications.
                self.bindings=updated
                await self.save(updated)

    def status(self, username):
        binding=self.bindings.get(username,{})
        return {'bound':bool(binding),'enabled':bool(binding.get('enabled')),'important_only':bool(binding.get('important_only')),
            'ready':bool(binding.get('context')),'storage_error':self.storage_error,
            'session_expired':binding.get('paused_until',0)>time.time(),
            'connection_error':bool(self.health.get(username,{}).get('error')),
            'last_poll':self.health.get(username,{}).get('last_poll'),
            'queued':len(self.queues.get(username,[])),'recent':list(self.results.get(username,[]))}

    async def configure(self, username, enabled, important_only):
        async with self.gates.setdefault(username,asyncio.Lock()), self.lock:
            if username not in self.bindings:raise ValueError('请先绑定微信')
            updated=copy.deepcopy(self.bindings)
            updated[username].update(enabled=enabled,important_only=important_only)
            await self.save(updated)
            if not enabled:self.queues.get(username,deque()).clear()

    async def test(self, username):
        binding=self.bindings.get(username)
        if not binding or not binding.get('enabled'):raise ValueError('请先绑定并开启微信通知')
        if not binding.get('context'):raise ValueError('请先在绑定的微信中向机器人发送“开始接收”')
        identifier=secrets.token_hex(16)
        self.queues.setdefault(username,deque(maxlen=100)).append((time.monotonic(),identifier,
            '🔔 AUTO-BUAA 微信通知测试\n这是当前学生的独立通道。\n看到这条消息后，请在应用中核对测试编号：'+identifier[-6:]+
            '\n此测试没有执行任何学校签到或抢课操作。',binding['generation']))
        return {'test_id':identifier[-6:],'status':'queued'}

    def record(self, username, identifier, state):
        self.results.setdefault(username,deque(maxlen=20)).appendleft({'id':identifier[-6:],'state':state,
            'time':datetime.datetime.now().isoformat(timespec='seconds')})

    async def poll(self, username):
        delay=1
        while not self.closed and username in self.bindings and self.account_exists(username):
            binding=copy.deepcopy(self.bindings[username])
            if binding.get('paused_until',0)>time.time():await asyncio.sleep(5);continue
            try:
                data=await self.protocol.updates(binding)
                self.health[username]={'last_poll':datetime.datetime.now().isoformat(timespec='seconds'),'error':False}
                async with self.lock:
                    if self.bindings.get(username,{}).get('generation')!=binding['generation'] or not self.account_exists(username):return
                    updated=copy.deepcopy(self.bindings);target=updated[username]
                    messages=data.get('msgs',[])
                    if not isinstance(messages,list):raise WechatError()
                    for msg in messages[:100]:
                        if not isinstance(msg,dict):continue
                        # Only the QR-scanning user may provide this student's context.
                        if (msg.get('from_user_id')==binding['peer'] and msg.get('to_user_id')==binding['bot']
                            and msg.get('message_type')==1 and isinstance(msg.get('context_token'),str) and 0<len(msg['context_token'])<8192):
                            target['context']=msg['context_token']
                    cursor=data.get('get_updates_buf')
                    if isinstance(cursor,str) and 0<len(cursor)<65536:target['cursor']=cursor
                    if target!=self.bindings[username]:await self.save(updated)
                delay=1
                await asyncio.sleep(1) # Also bounds a provider returning immediate empty polls.
            except WechatError as exc:
                self.health[username]=dict(self.health.get(username,{}),error=True)
                if exc.code==-14:
                    async with self.lock:
                        if username in self.bindings:
                            updated=copy.deepcopy(self.bindings);updated[username]['paused_until']=time.time()+3600
                            updated[username]['context']=''
                            try:await self.save(updated)
                            except ValueError:pass
                await asyncio.sleep(delay);delay=min(delay*2,60)
            except (ValueError,OSError):
                self.storage_error=True;await asyncio.sleep(30)

    async def sender(self, username):
        while not self.closed and username in self.bindings and self.account_exists(username):
            pending=self.queues.get(username)
            binding=self.bindings[username]
            if not pending or not binding.get('context') or not binding.get('enabled') or self.storage_error or binding.get('paused_until',0)>time.time():
                await asyncio.sleep(.5);continue
            created,identifier,text,generation=pending.popleft()
            if time.monotonic()-created>600 or generation!=binding['generation']:
                self.record(username,identifier,'expired');continue
            # Removal/disable commits acquire this same gate, so no later send
            # may start after they return. Unknown sends are never replayed.
            async with self.gates.setdefault(username,asyncio.Lock()):
                current=self.bindings.get(username)
                if not current or not current['enabled'] or current['generation']!=generation or not self.account_exists(username):continue
                self.record(username,identifier,'sending')
                try:
                    response=await self.protocol.send(copy.deepcopy(current),text,identifier)
                    self.record(username,identifier,'accepted' if response.get('ret')==0 else 'submitted')
                except WechatError as exc:
                    self.record(username,identifier,'session_expired' if exc.code==-14 else 'unconfirmed')
                    if exc.code==-14:
                        async with self.lock:
                            updated=copy.deepcopy(self.bindings);updated[username]['context']='';updated[username]['paused_until']=time.time()+3600
                            try:await self.save(updated)
                            except ValueError:pass
            await asyncio.sleep(1)
