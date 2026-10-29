"""Bounded multi-account regular attendance; the client owns final write validation."""
import asyncio
import datetime
import logging
import random
from collections import defaultdict
from core.domain import now as china_now, regular_start, regular_window, CHINA
from core.regular_policy import MAX_POSTS, minimum_retry_delay
from core.iclass import IclassSessionExpired

logger = logging.getLogger("buaa_signin_scheduler")

class SigninScheduler:
    def __init__(self, get_active_accounts, on_event_log=None, reconnect_account=None):
        self.get_active_accounts = get_active_accounts
        self.on_event_log = on_event_log or (lambda *args: None)
        self.reconnect_account = reconnect_account
        self.enabled = False
        self._task = None
        self._generation = 0
        self.interval_seconds = 20
        self.clock = china_now
        self.signed_courses = set()
        self.retry_counts = defaultdict(int)
        self.planned_targets = {}
        self.failed_permanently = set()
        self.pending_notified = set()
        self.window_closed_notified = set()
        self._tick_lock = asyncio.Lock()
        self._account_limit = asyncio.Semaphore(4)

    def log(self, message, level="info", username=None, user_name=None):
        self.on_event_log(level, message, username, user_name)
        logger.log(logging.ERROR if level == "error" else logging.INFO, "%s", message)

    def start(self, interval_seconds=20):
        if self.enabled:
            return
        self.enabled = True
        self._generation += 1
        self.interval_seconds = max(10, min(60, interval_seconds))
        generation = self._generation
        self._task = asyncio.create_task(self._run_loop(generation))
        self.log("常规签到守护已启动：课前随机优先，失败后下课前限次补尝试。")

    def stop(self):
        self.enabled = False
        self._generation += 1
        if self._task:
            self._task.cancel()
        self.log("常规签到守护已暂停。")

    async def _run_loop(self, generation):
        while self.enabled and generation == self._generation:
            try:
                await self._check_and_sign_all(generation)
                await asyncio.sleep(self.interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log("巡检异常：" + type(exc).__name__, "error")
                await asyncio.sleep(self.interval_seconds)

    async def tick(self):
        await self._check_and_sign_all()

    def remove_account(self, username):
        for mapping in (self.retry_counts, self.planned_targets):
            for key in list(mapping):
                if key[0] == username:
                    mapping.pop(key, None)
        for values in (self.signed_courses, self.failed_permanently, self.pending_notified, self.window_closed_notified):
            values.difference_update(k for k in list(values) if k[0] == username)

    async def _check_and_sign_all(self, generation=None):
        async with self._tick_lock:
            today = self.clock().date().isoformat()
            for mapping in (self.retry_counts, self.planned_targets):
                for key in list(mapping):
                    if len(key) != 3 or key[2] != today:
                        mapping.pop(key, None)
            for values in (self.signed_courses, self.failed_permanently, self.pending_notified, self.window_closed_notified):
                values.difference_update(k for k in list(values) if len(k) != 3 or k[2] != today)
            await asyncio.gather(*(self._check_account(acc, generation) for acc in self.get_active_accounts()), return_exceptions=False)

    async def _check_account(self, item, generation):
        async with self._account_limit:
            username = item.get("username", "")
            account = item.get("account")
            client = item.get("client")
            epoch = getattr(account, "auth_epoch", 0)
            def allowed():
                return (generation is None or (self.enabled and generation == self._generation)) and not getattr(account, "removed", False) and not getattr(account, "maintenance", False) and getattr(account, "auth_epoch", 0) == epoch and getattr(account, "auto_checkin", True)
            if not client or not allowed():
                return
            try:
                if not client.is_authenticated():
                    if not account or not self.reconnect_account or not await self.reconnect_account(account):
                        return
                    client = item["client"] = account.client
                    epoch = getattr(account, "auth_epoch", 0)
                try:
                    classes = await client.get_today_classes()
                except IclassSessionExpired:
                    if not account or not self.reconnect_account or not await self.reconnect_account(account):
                        raise
                    client = item["client"] = account.client
                    epoch = getattr(account, "auth_epoch", 0)
                    classes = await client.get_today_classes()
                if account:
                    account.last_classes = classes
                    account.last_refresh_time = self.clock().isoformat(timespec="seconds")
                    account.regular_health = {"stale": False, "last_success": account.last_refresh_time, "error": None}
                for course in classes:
                    if not allowed():
                        break
                    try:
                        await self._check_course(item, course, allowed)
                    except Exception as exc:
                        self.log("本门课程处理失败：" + type(exc).__name__, "warning", username, item.get("name"))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if account:
                    account.regular_health = {"stale": True, "last_success": getattr(account, "last_refresh_time", None), "error": type(exc).__name__}
                self.log("常规课表未同步，保留上次数据：" + type(exc).__name__, "warning", username, item.get("name"))

    async def _check_course(self, item, course, allowed):
        current = self.clock()
        cid = str(course.get("courseSchedId") or course.get("id") or "")
        if not cid.isdigit() or int(cid) <= 0:
            return
        key = (item["username"], cid, current.date().isoformat())
        from core.regular_course_policy import allowed as course_auto_allowed
        account_allowed=allowed
        allowed=lambda:account_allowed() and course_auto_allowed(item.get('account'),course,self.clock(),item['username'])
        if not allowed():
            self.planned_targets.pop(key,None)
            return
        if str(course.get("signStatus")) == "1":
            self.signed_courses.add(key)
            return
        if str(course.get("signStatus")) != "0" or key in self.signed_courses or key in self.failed_permanently:
            return
        start, deadline = regular_window(course, current)
        if not start:
            return
        if current > deadline:
            if key not in self.window_closed_notified:
                self.window_closed_notified.add(key)
                self.log("当前课表的签到窗口已结束或下课时间未核实，不提交；继续同步官方课表。", "warning", item["username"], item.get("name"))
            return
        self.window_closed_notified.discard(key)
        if current < start - datetime.timedelta(minutes=10):
            return
        record_reader = getattr(item["client"], "signin_record", None)
        record = record_reader(cid) if callable(record_reader) else None
        if record:
            state, attempts, updated = record
            previous_attempts = self.retry_counts[key]
            self.retry_counts[key] = attempts
            if state == "success":
                self.signed_courses.add(key)
                return
            if state in ("pending", "uncertain"):
                if key not in self.pending_notified:
                    self.pending_notified.add(key)
                    self.log("先前签到结果待官方确认，仅同步课表，不重发请求。", "warning", item["username"], item.get("name"))
                return
            if attempts >= MAX_POSTS:
                self.failed_permanently.add(key)
                return
            earliest = datetime.datetime.fromtimestamp(updated + minimum_retry_delay(attempts, self.clock() < start), CHINA).replace(tzinfo=None)
            # A manual failure replaces the unexecuted random first target.
            self.planned_targets[key] = earliest if attempts > previous_attempts else max(self.planned_targets.get(key, current), earliest)
        if key not in self.planned_targets:
            remaining = (start-current).total_seconds()
            offset = random.uniform(0, max(0, remaining-self.interval_seconds-5))
            self.planned_targets[key] = current + datetime.timedelta(seconds=offset)
        if self.clock() < self.planned_targets[key] or not allowed() or self.clock() > deadline:
            return
        before = getattr(item["client"], "actual_sign_posts", None)
        try:
            success, message = await item["client"].perform_signin(cid, guard=allowed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            after_record = record_reader(cid) if callable(record_reader) else None
            if after_record and after_record[0] in ("pending", "uncertain"):
                self.pending_notified.add(key)
                self.log("签到请求结果不确定，仅同步官方课表，不盲目补发。", "warning", item["username"], item.get("name"))
            else:
                self.planned_targets[key] = self.clock() + datetime.timedelta(seconds=max(30, minimum_retry_delay(self.retry_counts[key], self.clock() < start)))
                self.log("签到预检未完成，将在窗口内退避检查：" + type(exc).__name__, "warning", item["username"], item.get("name"))
            return
        if success:
            self.signed_courses.add(key)
            self.log("常规签到请求已接受：" + message, "success", item["username"], item.get("name"))
            try:
                refreshed = await item["client"].get_today_classes()
                account = item.get("account")
                if account:
                    account.last_classes = refreshed
                    account.last_refresh_time = self.clock().isoformat(timespec="seconds")
            except Exception:
                account = item.get("account")
                if account:
                    account.regular_health = {"stale": True, "pending_verification": True}
                self.log("请求已接受，官方状态暂未同步；不会重发。", "warning", item["username"], item.get("name"))
        else:
            after = getattr(item["client"], "actual_sign_posts", None)
            latest = record_reader(cid) if callable(record_reader) else None
            if latest:
                self.retry_counts[key] = latest[1]
            elif not isinstance(before, int) or not isinstance(after, int) or after > before:
                self.retry_counts[key] += 1
            self.log("常规签到未完成：" + message, "warning", item["username"], item.get("name"))
            if self.retry_counts[key] >= MAX_POSTS:
                self.failed_permanently.add(key)
            else:
                self.planned_targets[key] = self.clock() + datetime.timedelta(seconds=max(30, minimum_retry_delay(self.retry_counts[key], self.clock() < start)))
                if not getattr(item["client"], "session_id", None) and self.reconnect_account and item.get("account"):
                    await self.reconnect_account(item["account"])

    @staticmethod
    def _parse_course_time(begin_str, current):
        return regular_start(begin_str, current)
