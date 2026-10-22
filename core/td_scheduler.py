"""Account-bound TD state machine; every write is claimed before network I/O."""
import asyncio
from datetime import datetime, timedelta, timezone
import random
import re
import threading
import time
import uuid

from core.td_client import TDClient, TDRejected, DEVICES
from core.td_store import owner_key
from core.td_policy import validate_settings, open_on_date
from core.td_license import TDLicense

TZ = timezone(timedelta(hours=8))
WINDOWS = ((450, 600), (690, 840), (930, 1200))
PROCESS_ID = uuid.uuid4().hex


def local_now():
    return datetime.now(TZ)


def window_end(now):
    minute = now.hour * 60 + now.minute
    for start, end in WINDOWS:
        if start <= minute < end:
            return now.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0).timestamp()
    return None


class TDEngine:
    def __init__(self, store, get_account, log, client=None, clock=local_now, licensing=None, schedule_delay=None):
        self.store, self.get_account, self.log = store, get_account, log
        self.client, self.clock = client or TDClient(), clock
        self.locks, self.lock = {}, threading.Lock()
        self.stopping = False
        self.schedule_delay = schedule_delay or (lambda maximum: random.SystemRandom().uniform(0, maximum))
        self.licensing = licensing if licensing is not None else TDLicense(store.root/'authorization.sqlite',clock=lambda:self.clock().timestamp())

    def account_lock(self, username):
        with self.lock:
            return self.locks.setdefault(username, threading.RLock())

    def close(self):
        self.stopping = True
        with self.lock:
            locks = list(self.locks.values())
        for lock in locks:
            lock.acquire()
        try:
            with self.store.lock:
                self.store.db.close()
        finally:
            for lock in reversed(locks):
                lock.release()
            self.licensing.close()

    def valid(self, username, profile, stamp=None, manual=False):
        account = self.get_account(username)
        now = self.clock()
        try:
            validate_settings(profile, self.calendar(username))
        except ValueError:
            return False
        return (self.licensing.status(username)['active'] and not self.stopping and account is not None and not account.removed and (manual or profile["enabled"]) and profile["confirmed"]
                and re.fullmatch(r"[0-9]{5,16}", username) is not None
                and open_on_date(profile, now)
                and window_end(now) is not None and (stamp is None or 0 <= now.timestamp() - stamp < 420))

    def calendar(self, username):
        account = self.get_account(username)
        info = getattr(getattr(account, 'boya_client', None), 'semester_info', None)
        if isinstance(info, dict):
            from core.domain import semester_bounds
            start, end = semester_bounds(info)
            if start and end:
                return start.date().isoformat(), end.date().isoformat()
        return None

    def configure(self, username, settings):
        validate_settings(settings, self.calendar(username))
        self.store.configure(username, settings)

    def batch_margin(self, profile, job, stamp):
        remaining = max(0, min(profile['daily_limit'], 3) - job['attempted'])
        if job['state'] == 'waiting_exit':
            return max(0, job.get('due', stamp)-stamp) + (480*remaining+190 if remaining else 30)
        return max(0,job.get('due',stamp)-stamp) + 430 + 480*max(0, remaining-1)

    def batch_availability(self, username, profile, job, outstanding):
        now=self.clock();stamp=now.timestamp();reason=''
        pending=job['state']=='waiting_exit'
        authorization=self.licensing.status(username)
        if job.get('batch_active'):reason='当日队列正在执行，不能重复启动'
        elif profile['enabled']:reason='自动守护已开启，请先暂停后再手动启动'
        elif not self.valid(username,profile,manual=True):reason='授权、活动日期或开放时段不允许启动'
        elif any(day!=now.date().isoformat() or j['state']!='waiting_exit' for day,j in outstanding):reason='有待核验请求，禁止重复提交'
        elif pending and not 0<=stamp-job.get('entry_at',0)<420:reason='原配对已超时，请核对官方记录'
        elif not pending and (type(job.get('attempted')) is not int or not 0<=job['attempted']<min(profile['daily_limit'],3)):reason='已达今日请求上限'
        elif not pending and profile['count'] is not None and profile['count']>=profile['target']:reason='当前记录已达设定目标'
        elif not self.store.groups(owner_key(username)):reason='请先添加本人入口/出口照片组'
        elif min(window_end(now),authorization['expires_epoch'])-stamp < self.batch_margin(profile,job,stamp):reason='当前时段或授权剩余时间不足以安全完成剩余队列'
        return {'allowed':not reason,'reason':reason,'active':job.get('batch_active') is True,
                'mode':job.get('batch_mode'),'window_end':job.get('batch_window_end'),
                'start_before':min(window_end(now) or stamp,authorization.get('expires_epoch') or stamp)-self.batch_margin(profile,job,stamp),
                'remaining':max(0,min(profile['daily_limit'],3)-job['completed'])}

    def start_batch(self, username, confirmed):
        if confirmed is not True:raise ValueError('请确认本人参与并授权启动当日完整队列')
        with self.account_lock(username), self.store.transaction():
            owner=owner_key(username);now=self.clock();day=now.date().isoformat()
            p=self.store.profile(owner);j=self.store.job(owner,day)
            availability=self.batch_availability(username,p,j,self.store.outstanding(owner))
            if not availability['allowed']:raise ValueError(availability['reason'])
            j.update(batch_active=True,batch_mode='manual',batch_finished=False,batch_window_end=window_end(now),
                     note='手动当日队列已启动；入口与出口将按间隔依次执行')
            self.store.save_job(owner,day,j)
        self.log('info','TD手动当日队列已启动，与自动守护共用预算，等待期间不阻塞页面',username=username,category='td')
        return {'queued':True}

    def status(self, username):
        owner, now = owner_key(username), self.clock()
        calendar = self.calendar(username)
        with self.store.lock:
            profile = self.store.profile(owner)
            job = self.store.job(owner, now.date().isoformat())
            outstanding = self.store.outstanding(owner)
            images = self.store.images(owner)
            groups = self.store.groups(owner)
        # Pending state survived a process exit or is currently in flight. Both
        # are non-repeatable, and a view refresh never changes this state.
        blocked = next((j for _, j in outstanding if j["state"] != "waiting_exit"), None)
        old_pair = next((j for day, j in outstanding if day != now.date().isoformat()), None)
        shown = blocked or old_pair or job
        shown = dict(shown)
        if shown.get('state') in ('sending_entry','sending_exit') and shown.get('sender_process') != PROCESS_ID:
            shown.update(state='uncertain',note='程序重启前的请求未确认，已停止重发，请核对学校记录')
        protected = {j.get(key) for _, j in outstanding for key in ("entry_image", "exit_image")}
        for image in images:
            image["in_use"] = image["id"] in protected
        busy_groups = {j.get('group_id') for _,j in outstanding}
        for group in groups: group['in_use'] = group['id'] in busy_groups
        try:
            validate_settings(profile,calendar)
            rules_valid, rules_error = True, None
        except ValueError as exc:
            rules_valid, rules_error = False, str(exc)
        progress = {k: profile[k] for k in ("count", "count_source", "count_at")}
        term = (profile['semester_start'], profile['semester_end'])
        if (progress['count'] is not None and
            (not term[0] <= now.date().isoformat() <= term[1] or
             (calendar is not None and term != tuple(calendar)))):
            # Keep the original record intact; it is not this term's progress.
            progress = dict(count=None, count_source='out_of_scope', count_at=None)
        return {"license": self.licensing.status(username), "settings": {k: profile[k] for k in ("enabled", "campus", "start", "end", "semester_start", "semester_end", "target", "daily_limit", "confirmed", "weekdays", "closed_dates")},
                "progress": progress,
                "today": {k: job.get(k, 0) for k in ("attempted", "completed")},
                "task": {k: shown.get(k) for k in ("state", "due", "entry_at", "note")},
                "images": images, "groups": groups, "rules_valid":rules_valid,"rules_error":rules_error, "calendar": calendar, "within_window": window_end(now) is not None and open_on_date(profile,now),
                "manual":self.manual_availability(username,profile,job,outstanding),
                "batch":self.batch_availability(username,profile,job,outstanding),
                "activity_current": bool(profile["start"] and profile["start"] <= now.date().isoformat() <= profile["end"]),
                "server_time": now.isoformat(), "transport": "campus_tcp_no_tls"}

    def toggle(self, username, enabled):
        with self.account_lock(username), self.store.transaction():
            owner = owner_key(username)
            p = self.store.profile(owner)
            if enabled:
                if self.store.batches(owner):
                    raise ValueError('已有当日队列，请先暂停后续队列再切换守护')
                authorization=self.licensing.status(username)
                if not authorization['active']:raise ValueError(authorization['reason'])
                now = self.clock()
                validate_settings(p, self.calendar(username))
                if not p["confirmed"] or not p["start"] <= now.date().isoformat() <= p["end"]:
                    raise ValueError("先核对并保存本学期活动日期，且当前需在活动日期内")
                if not re.fullmatch(r"[0-9]{5,16}", username):
                    raise ValueError("当前账号学号格式不支持 TD")
                account = self.get_account(username)
                if account is None or account.removed:
                    raise ValueError("学生账号已移除")
                if not self.store.groups(owner):
                    raise ValueError("请先为当前学生添加一组入口/出口照片并确认穿搭一致")
                if any(j["state"] != "waiting_exit" or day != now.date().isoformat() or not 0 <= now.timestamp() - j.get("entry_at", 0) < 420
                       for day, j in self.store.outstanding(owner)):
                    raise ValueError("有未确认或过期配对，请先核对官方记录并解除暂停")
                current=self.store.job(owner,now.date().isoformat())
                current['batch_finished']=False
                self.store.save_job(owner,now.date().isoformat(),current)
            p["enabled"] = enabled
            if not enabled:
                for day, record in self.store.batches(owner):
                    record.update(batch_active=False, batch_finished=True, note='当日队列已暂停，原配对与预算保留；不会继续发送')
                    self.store.save_job(owner,day,record)
            self.store.save_profile(owner, p)
        self.log("info", "TD守护已开启；将在允许时间内执行" if enabled else "TD守护已暂停，不会继续发送请求", username=username, category="td")

    def remove_account(self, username):
        # Removed flag is already set before this hook, so transport preflight
        # cannot authorize another request while we wait for an in-flight one.
        self.toggle(username, False)

    def resolve(self, username, verified):
        if verified is not True:
            raise ValueError("请先核对官方记录")
        with self.account_lock(username), self.store.transaction():
            owner, now = owner_key(username), self.clock().timestamp()
            for day, j in self.store.outstanding(owner):
                if now - j.get("entry_at", now) <= 430:
                    raise ValueError("该配对可能仍在处理，请等待至少七分钟并核对官方记录")
            p = self.store.profile(owner); p["enabled"] = False; self.store.save_profile(owner, p)
            for day,j in self.store.batches(owner):
                j.update(batch_active=False,batch_finished=True)
                self.store.save_job(owner,day,j)
            for day, j in self.store.outstanding(owner):
                j.update(state="resolved", note="用户已核对官方记录；本地未补记成功")
                self.store.save_job(owner, day, j)
        self.log("info", "TD待核验暂停已解除，原请求预算保留，未补记成功；需手动重新开启", username=username, category="td")

    def record_count(self, username, count):
        with self.store.transaction():
            owner = owner_key(username); p = self.store.profile(owner)
            validate_settings(p,self.calendar(username))
            if not p["confirmed"] or not p["start"] <= self.clock().date().isoformat() <= p["end"]:
                raise ValueError("请先设置当前活动日期")
            p.update(count=count, count_source="manual", count_at=self.clock().isoformat())
            self.store.save_profile(owner, p)

    def manual_availability(self, username, profile, job, outstanding):
        phase='exit' if job['state']=='waiting_exit' else 'entry'
        reason=''
        now=self.clock();stamp=now.timestamp()
        authorization=self.licensing.status(username)
        if not authorization['active']: reason=authorization['reason']
        elif profile['enabled']: reason='请先暂停自动守护，再手动提交，避免两种操作并行'
        elif job.get('batch_active'): reason='当日队列执行中，禁止单独提交入口或出口'
        elif not self.valid(username,profile,manual=True): reason='规则未确认、日期/开放星期/停开日或每日时段不允许提交'
        elif any(day!=now.date().isoformat() or j['state']!='waiting_exit' for day,j in outstanding): reason='有待核验记录，禁止重复提交'
        elif job.get('due',0)>stamp: reason='配对或轮次间隔未到，请稍后再操作'
        elif phase=='exit' and not 0<=stamp-job.get('entry_at',0)<420: reason='入口配对已超时，请核对官方记录'
        elif phase=='entry':
            if type(job.get('attempted')) is not int or not 0<=job['attempted']<min(profile['daily_limit'],3): reason='已达本软件今日请求上限'
            elif profile['count'] is not None and profile['count']>=profile['target']: reason='当前记录已达设定目标'
            elif window_end(now)-stamp<430: reason='距离当前开放时段结束不足安全配对时间'
            elif authorization['expires_epoch']-stamp<430: reason='授权剩余时间不足安全配对时间，请勿发起新入口'
            elif not self.store.groups(owner_key(username)): reason='请先添加本人入口/出口照片组'
        return {'phase':phase,'allowed':not reason,'reason':reason}

    def manual(self, username, phase, confirmed):
        if confirmed is not True: raise ValueError('请确认本人已到对应位置并实际参与锻炼')
        with self.account_lock(username):
            with self.store.lock:
                owner=owner_key(username);p=self.store.profile(owner)
                j=self.store.job(owner,self.clock().date().isoformat())
                status=self.manual_availability(username,p,j,self.store.outstanding(owner))
            if phase!=status['phase']: raise ValueError('配对状态已变化，请刷新后重新核对入口/出口')
            if not status['allowed']: raise ValueError(status['reason'])
            self._tick(username,manual_phase=phase)
            with self.store.lock:
                result=self.store.job(owner,self.clock().date().isoformat())
            if result['state']!=('waiting_exit' if phase=='entry' else 'idle'):
                raise ValueError('本次请求未确认，请核对状态；禁止盲目重复提交')
        return {'phase':phase,'state':result['state']}

    def tick(self, username):
        lock = self.account_lock(username)
        if not lock.acquire(blocking=False):
            return
        try:
            self._tick(username)
        finally:
            lock.release()

    def _tick(self, username, manual_phase=None):
        owner, now = owner_key(username), self.clock()
        day, stamp = now.date().isoformat(), now.timestamp()
        with self.store.transaction():
            p = self.store.profile(owner)
            j = self.store.job(owner, day)
            for record_day, record in self.store.outstanding(owner):
                if record['state'] in ('sending_entry','sending_exit') and record.get('sender_process') != PROCESS_ID:
                    record.update(state='uncertain',batch_active=False,batch_finished=True,
                                  note='程序重启前的请求未确认，禁止重发，请核对学校记录')
                    self.store.save_job(owner,record_day,record)
                    p['enabled']=False
                    self.store.save_profile(owner,p)
            j = self.store.job(owner,day)
            for batch_day, record in self.store.batches(owner):
                if batch_day != day:
                    record.update(batch_active=False,batch_finished=True)
                    self.store.save_job(owner,batch_day,record)
            expired = [(d, record) for d, record in self.store.outstanding(owner)
                       if record['state'] == 'waiting_exit' and
                       (d != day or not 0 <= stamp - record.get('entry_at', 0) < 420)]
            if expired:
                for d, record in expired:
                    record.update(state='uncertain', note='配对窗口已结束，未继续发送出口，请核对官方记录')
                    record.update(batch_active=False,batch_finished=True)
                    self.store.save_job(owner, d, record)
                p['enabled'] = False
                self.store.save_profile(owner, p)
                return
            if j.get('batch_active') and stamp >= j.get('batch_window_end', 0):
                j.update(batch_active=False,batch_finished=True,note='本批次开放时段已结束，未继续发送；请核对现有进度')
                self.store.save_job(owner,day,j)
                return
            batch = j.get('batch_active') is True
            if not p['enabled'] and not batch and manual_phase is None:return
            authorization=self.licensing.status(username)
            if not authorization['active']:
                if batch:
                    j.update(batch_active=False,batch_finished=True,note='授权已失效，当日队列暂停，未继续发送')
                    self.store.save_job(owner,day,j)
                if p['enabled']:
                    p['enabled']=False;self.store.save_profile(owner,p)
                    self.log('warning','TD离线授权不可用，守护已暂停；未发送请求，配对和预算保留',username=username,category='td')
                return
            if not self.valid(username, p, manual=manual_phase is not None or batch):
                if batch:
                    j.update(batch_active=False,batch_finished=True,note='规则、账号或开放时段不再有效，当日队列暂停')
                    self.store.save_job(owner,day,j)
                return
            outstanding = self.store.outstanding(owner)
            if any(d != day or j["state"] != "waiting_exit" for d, j in outstanding):
                return  # Restarted or uncertain network write must not replay.
            j = self.store.job(owner, day)
            if p['enabled'] and manual_phase is None and not batch:
                if j.get('batch_finished'):return
                if j['state'] not in ('idle','resolved','waiting_exit'):return
                remaining=min(p['daily_limit'],3)-j['attempted']
                if remaining<=0 and j['state']!='waiting_exit':return
                if j['state']!='waiting_exit' and p['count'] is not None and p['count']>=p['target']:return
                available=min(window_end(now),authorization['expires_epoch'])-stamp-self.batch_margin(p,j,stamp)
                if available<0:return
                initial = self.schedule_delay(available) if j['state']!='waiting_exit' and j['attempted']==0 else 0
                j.update(batch_active=True,batch_mode='auto',batch_finished=False,batch_window_end=window_end(now),
                         due=max(j.get('due',0),stamp+initial),note='自动当日队列已排定，等待首次入口')
                self.store.save_job(owner,day,j);batch=True
            if j.get("due", 0) > stamp:
                return
            phase = "exit" if j["state"] == "waiting_exit" else "entry"
            if manual_phase is not None and manual_phase!=phase: return
            if phase == "exit":
                if not 0 <= stamp - j["entry_at"] < 420:
                    j.update(state="uncertain", note="进出门配对已超时，未发送出口请求")
                    p["enabled"] = False
                    self.store.save_job(owner, day, j); self.store.save_profile(owner, p)
                    return
            else:
                if type(j.get('attempted')) is not int or not 0 <= j['attempted'] < min(p["daily_limit"],3):
                    if batch:
                        j.update(batch_active=False,batch_finished=True,note='当日队列已结束，今日请求额度已用完')
                        self.store.save_job(owner,day,j)
                    return
                if p["count"] is not None and p["count"] >= p["target"]:
                    if batch:
                        j.update(batch_active=False,batch_finished=True,note='当前记录已达目标，当日队列结束；最终以学校审核为准')
                        self.store.save_job(owner,day,j)
                    return
                # Leave a full seven minutes before the current window closes.
                if window_end(now) - stamp < 430 or authorization['expires_epoch']-stamp<430:
                    return
                groups = self.store.groups(owner)
                if not groups:
                    p["enabled"] = False; self.store.save_profile(owner, p); return
                group = random.SystemRandom().choice([g for g in groups if g['id'] != p['last_group']] or groups)
                entry, exit_image = group['entry_image'], group['exit_image']
                devices = DEVICES[p["campus"]]
                j.update(attempted=j["attempted"] + 1, entry_at=stamp, entry_image=entry, group_id=group['id'],
                         exit_image=exit_image, entry_device=random.SystemRandom().choice(devices[:3]),
                         exit_device=random.SystemRandom().choice(devices[3:]), period=[p["start"], p["end"],p['semester_start'],p['semester_end']])
            j.update(state="sending_" + phase, sender_process=PROCESS_ID, note="正在请求，不能重复提交")
            self.store.save_job(owner, day, j)
        def guard():
            with self.store.lock:
                fresh = self.store.profile(owner)
                current_job=self.store.job(owner,day)
            return (self.valid(username, fresh, j["entry_at"], manual=manual_phase is not None or batch)
                    and (not batch or (current_job.get('batch_active') is True and self.clock().timestamp()<current_job.get('batch_window_end',0)))
                    and (fresh["start"], fresh["end"],fresh['semester_start'],fresh['semester_end']) == tuple(j["period"]))
        try:
            # Read before the first write, and use the same timestamp for the
            # paired check/photo message. Each phase's media ID is persistent.
            photo = self.store.read_image(username, j[phase + "_image"])
            if not guard():
                raise ValueError()
            count = self.client.check(username, j[phase + "_device"], stamp, guard)
            self.client.photo(j[phase + "_device"], stamp, photo, guard)
            with self.store.transaction():
                p = self.store.profile(owner)
                # An explicit server counter is observational, not final grade.
                if count is not None:
                    p.update(count=count, count_source="server", count_at=self.clock().isoformat())
                p["last_photo"] = j[phase + "_image"]
                if phase == "entry":
                    j.update(state="waiting_exit", due=stamp + random.SystemRandom().uniform(180, 240),
                             note="入口与照片已接收，等待出口；最终认定以学校为准")
                else:
                    p['last_group'] = j['group_id']
                    j.update(state="idle", completed=j["completed"] + 1,
                             due=self.clock().timestamp() + random.SystemRandom().uniform(180, 240),
                             note="进出门与照片请求均已接收，最终认定以学校为准")
                    if batch and (j['attempted']>=min(p['daily_limit'],3) or p['count'] is not None and p['count']>=p['target']):
                        j.update(batch_active=False,batch_finished=True,note='当日队列已完成；请求接收不等于学校最终有效次数')
                self.store.save_job(owner, day, j); self.store.save_profile(owner, p)
            self.log("info", "TD入口及照片已接收，等待配对出口" if phase == "entry" else "TD本轮进出门及照片已接收；请以官方记录为准", username=username, category="td")
        except Exception as exc:
            try:
                with self.store.transaction():
                    j.update(state="rejected" if isinstance(exc, TDRejected) else "uncertain",
                             batch_active=False,batch_finished=True,
                             note="学校未接受或结果未确认，已暂停且不重发，请核对官方记录")
                    p = self.store.profile(owner); p["enabled"] = False
                    self.store.save_job(owner, day, j); self.store.save_profile(owner, p)
            finally:
                self.log("warning", "TD请求未确认或失败，已停止重发；请核对官方记录", username=username, category="td")

    async def run(self, accounts):
        semaphore = asyncio.Semaphore(4)
        async def one(username):
            async with semaphore:
                try:
                    await asyncio.to_thread(self.tick, username)
                except Exception:
                    self.log("error", "TD本地存储或任务异常，未继续提交；请检查存储空间", username=username, category="td")
        while True:
            await asyncio.gather(*(one(username) for username in list(accounts)))
            await asyncio.sleep(5)
