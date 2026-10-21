"""Offline, account/installation-bound TD authorization. No network or private signing key."""
import base64
import calendar
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from core import vault
from core.td_license_public import PUBLIC_KEYS

PRODUCT = 'AUTO-BUAATOOLS/TD'
TZ = timezone(timedelta(hours=8))
RENEWAL_WINDOW = 24 * 60 * 60


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()


def pack(prefix, value):
    return prefix+'.'+base64.urlsafe_b64encode(canonical(value)).decode().rstrip('=')


def unbase(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',value):
        raise ValueError('激活数据格式无效')
    return base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True)


def unpack(value, prefix):
    if not isinstance(value,str) or len(value)>4096 or not value.startswith(prefix+'.'):
        raise ValueError('激活数据格式无效')
    raw=unbase(value.split('.',1)[1]);obj=json.loads(raw)
    if not isinstance(obj,dict) or canonical(obj)!=raw:
        raise ValueError('激活数据编码无效')
    return obj


def validate_request(request, keys=PUBLIC_KEYS):
    p=unpack(request,'TDR1')
    if set(p)!={'v','product','kid','binding','nonce'} or type(p['v']) is not int or p['v']!=1 or p['product']!=PRODUCT:
        raise ValueError('申请码不属于当前TD产品')
    if not isinstance(p['kid'],str) or p['kid'] not in keys or any(not isinstance(p[k],str) or not re.fullmatch(r'[0-9a-f]{64}',p[k]) for k in ('binding','nonce')):
        raise ValueError('申请码版本或绑定信息无效')
    return p


def verify_code(code, keys=PUBLIC_KEYS):
    if not isinstance(code,str) or len(code)>4096 or code.count('.')!=2:
        raise ValueError('请输入完整离线激活码')
    prefix,payload,signature=code.split('.')
    if prefix!='TDL1':raise ValueError('激活码版本无效')
    raw=unbase(payload);p=json.loads(raw)
    if not isinstance(p,dict) or canonical(p)!=raw or set(p)!={'v','product','kid','binding','nonce','id','issued','months'}:
        raise ValueError('激活码内容无效')
    if type(p['v']) is not int or p['v']!=1 or p['product']!=PRODUCT or type(p['months']) is not int or p['months']!=1:
        raise ValueError('激活码不属于当前TD产品')
    if not isinstance(p['kid'],str) or p['kid'] not in keys or type(p['issued']) is not int or not 0<p['issued']<4102444800:
        raise ValueError('激活码签发信息无效')
    if any(not isinstance(p[k],str) or not re.fullmatch(r'[0-9a-f]{64}',p[k]) for k in ('binding','nonce')) or not isinstance(p['id'],str) or not re.fullmatch(r'[0-9a-f]{32}',p['id']):
        raise ValueError('激活码绑定信息无效')
    try:Ed25519PublicKey.from_public_bytes(bytes.fromhex(keys[p['kid']])).verify(unbase(signature),b'TD-LICENSE/v1\0'+raw)
    except Exception as exc:raise ValueError('激活码签名无效，未修改现有授权') from exc
    return p


def month_after(stamp):
    d=datetime.fromtimestamp(stamp,TZ);year=d.year+(d.month==12);month=d.month%12+1
    return d.replace(year=year,month=month,day=min(d.day,calendar.monthrange(year,month)[1])).timestamp()


def machine_anchor():
    if sys.platform=='win32':
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Cryptography',0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
            value=winreg.QueryValueEx(key,'MachineGuid')[0]
    elif sys.platform=='darwin':
        text=subprocess.check_output(['/usr/sbin/ioreg','-rd1','-c','IOPlatformExpertDevice'],timeout=3,text=True)
        match=re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"',text)
        if not match:raise OSError('本机标识暂不可读')
        value=match.group(1)
    else:
        path=next((p for p in (Path('/etc/machine-id'),Path('/var/lib/dbus/machine-id')) if p.is_file()),None)
        if path is None:raise OSError('本机标识暂不可读')
        value=path.read_text().strip()
    if not isinstance(value,str) or len(value)<8:raise OSError('本机标识无效')
    return hashlib.sha256((sys.platform+':'+value).encode()).hexdigest()


class TDLicense:
    def __init__(self,path,clock=time.time,anchor=machine_anchor,keys=PUBLIC_KEYS,protect=vault.encrypt,unprotect=vault.decrypt,monotonic=time.monotonic):
        self.path=Path(path);self.clock=clock;self.anchor=anchor;self.keys=keys;self.protect=protect;self.unprotect=unprotect
        self.lock=threading.RLock()
        self.monotonic=monotonic;self.started_clock=self.clock();self.started_monotonic=self.monotonic()
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(self.path,timeout=10,check_same_thread=False)
        try:
            self.db.execute('CREATE TABLE IF NOT EXISTS authorization (id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)');self.db.commit()
        except BaseException:
            self.db.close();raise
        try:os.chmod(self.path,0o600)
        except OSError:pass

    def close(self):
        with self.lock:self.db.close()

    @contextmanager
    def state(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                row=self.db.execute('SELECT data FROM authorization WHERE id=1').fetchone()
                now=int(self.clock());machine=self.anchor()
                if not 0<now<4102444800:raise ValueError('请核对系统日期')
                observed=max(now,int(self.started_clock+self.monotonic()-self.started_monotonic))
                if now<observed-300:raise ValueError('系统时间停止或回退，请核对系统时间')
                if row:
                    value=json.loads(self.unprotect(row[0]))
                    if value.get('v')!=1 or value.get('machine')!=machine or not isinstance(value.get('accounts'),dict) or not isinstance(value.get('used'),list):
                        raise ValueError('授权存储与本机不匹配，请联系签发者重新核对')
                    if type(value.get('seen')) is not int or now<value['seen']-300:
                        raise ValueError('系统时间早于授权记录，请核对系统时间；TD已停止')
                else:value={'v':1,'machine':machine,'seed':secrets.token_hex(32),'seen':now,'accounts':{},'used':[]}
                before=canonical(value)
                if observed-value['seen']>=60:value['seen']=observed
                yield value,now
                if not row or canonical(value)!=before:
                    data=self.protect(canonical(value).decode())
                    self.db.execute('INSERT OR REPLACE INTO authorization VALUES(1,?)',(data,))
                self.db.commit()
            except BaseException as exc:
                self.db.rollback()
                if isinstance(exc,Exception) and not isinstance(exc,ValueError):raise ValueError('私有授权存储不可验证，未重置原数据') from exc
                raise

    def binding(self,s,user):
        return hashlib.sha256(('td-license-v1:'+s['machine']+':'+s['seed']+':'+user).encode()).hexdigest()

    def stored_expiry(self,s,binding,record):
        license=verify_code(record['code'],self.keys)
        started=record.get('started');period_start=record.get('period_start',started)
        if (license['binding']!=binding or license['id'] not in s['used'] or type(started) is not int
            or type(period_start) is not int or not started<=period_start<=started+RENEWAL_WINDOW
            or record.get('expires')!=month_after(period_start) or started<license['issued']-300):
            raise ValueError('授权记录无效，请联系签发者核对')
        return record['expires']

    def status(self,user):
        try:
            with self.state() as (s,now):
                binding=self.binding(s,user);p=s['accounts'].get(binding,{})
                if not p.get('code'):return {'active':False,'reason':'当前学号在本机尚未激活TD','expires_at':None,'expires_epoch':0,'renewable':True,'renew_after_epoch':0,'renew_after':None}
                expiry=self.stored_expiry(s,binding,p);active=p['started']-300<=now<expiry
                renew_after=expiry-RENEWAL_WINDOW
                return {'active':active,'reason':'' if active else 'TD离线授权已到期，请重新申请激活码','expires_at':datetime.fromtimestamp(expiry,TZ).isoformat(),'expires_epoch':expiry,'renewable':now>=renew_after,'renew_after_epoch':renew_after,'renew_after':datetime.fromtimestamp(renew_after,TZ).isoformat()}
        except Exception:
            return {'active':False,'reason':'TD授权不可验证：请核对系统时间、本机用户与私有授权存储','expires_at':None,'expires_epoch':0,'renewable':False,'renew_after_epoch':0,'renew_after':None}

    def request(self,user):
        if not re.fullmatch(r'[0-9]{5,16}',user):raise ValueError('请先选择有效学号；测试身份不可用于正式签发')
        with self.state() as (s,now):
            binding=self.binding(s,user);p=s['accounts'].setdefault(binding,{})
            if p.get('code') and now<self.stored_expiry(s,binding,p)-RENEWAL_WINDOW:
                raise ValueError('仅在到期前24小时或到期后可申请新码续期')
            if not p.get('pending'):p['pending']=secrets.token_hex(32)
            return pack('TDR1',{'v':1,'product':PRODUCT,'kid':next(iter(self.keys)),'binding':binding,'nonce':p['pending']})

    def activate(self,user,code):
        p=verify_code(code,self.keys)
        with self.state() as (s,now):
            binding=self.binding(s,user);record=s['accounts'].get(binding,{})
            if p['id'] in s['used']:raise ValueError('此激活码已核销，不能再次使用或延长到期时间')
            if p['binding']!=binding or p['nonce']!=record.get('pending'):raise ValueError('激活码与当前学号、本机申请码不匹配')
            if now<p['issued']-300:raise ValueError('系统时间早于激活码签发时间，请核对系统时间')
            period_start=now
            if record.get('code'):
                expiry=self.stored_expiry(s,binding,record)
                if now<expiry-RENEWAL_WINDOW:raise ValueError('仅在到期前24小时或到期后可使用新码续期')
                period_start=max(now,int(expiry))
            if len(s['used'])>=10000:raise ValueError('本机授权记录已达维护上限，请联系签发者')
            s['accounts'][binding]={'code':code,'started':now,'period_start':period_start,'expires':month_after(period_start)};s['used'].append(p['id']);s['seen']=max(s['seen'],now)
        return self.status(user)
