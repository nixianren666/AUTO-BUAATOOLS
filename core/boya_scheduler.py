"""
北航博雅自动化调度引擎 (BoyaScheduler)
支持多学生并发后台巡检、自主签到课程自动抢选、位置微扰自动签到/签退与智能熔断
"""

import asyncio
import json
import logging
import math
import random
import threading
import time
import httpx
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core.boya_client import BoyaClient, BoyaApiError, BoyaSessionExpired
from core.boya_auto_rules import permanently_excluded

logger = logging.getLogger(__name__)


from core.domain import (parse_dt, in_window, sign_config as parse_sign_config,
    autonomous, course_times as parse_course_time_range, now as china_now,
    course_id, within_semester, semester_bounds, REQUIREMENTS)

def get_current_semester_range(ref_date=None, semester_info=None):
    if not semester_info:
        raise ValueError("官方校历未同步，不能估算本学期")
    start, end = semester_bounds(semester_info)
    if not start or not end:
        raise ValueError("官方校历不完整")
    return start, end, semester_info.get("semesterName", "")

def has_autonomous_sign(course):
    return autonomous(course)

def get_course_category(course: Dict[str, Any]) -> str:
    kind = course.get("courseNewKind2")
    if isinstance(kind, dict):
        val = kind.get("kindName") or ""
    else:
        val = course.get("courseKind") or course.get("kindName") or course.get("courseType") or ""
    val = str(val).strip()
    if "安全" in val or "健康" in val:
        return "安全健康"
    if "德育" in val or "思政" in val:
        return "德育"
    if "劳育" in val or "劳动" in val:
        return "劳育"
    if "美育" in val or "艺术" in val:
        return "美育"
    if "智育" in val or "科技" in val:
        return "智育"
    if "体育" in val:
        return "体育"
    return val


def course_matches_campus(course: Dict[str, Any], campus_preference: str = "北京") -> bool:
    """校区匹配：杭州学生只抢杭州课，北京学生只抢非杭州课"""
    combined = " ".join([
        str(course.get("courseName") or ""),
        str(course.get("name") or ""),
        str(course.get("coursePosition") or ""),
        str(course.get("courseCampusList") or ""),
        str(course.get("coursePositionName") or ""),
        str(course.get("campusName") or ""),
    ])
    is_hangzhou = any(kw in combined for kw in ("杭州", "国新院", "杭州极弱磁"))
    if campus_preference == "杭州":
        return is_hangzhou
    return not is_hangzhou


def random_point_in_radius(lat: float, lng: float, radius_m: float = 10.0) -> Tuple[float, float]:
    """在签到有效圆内随机生成微扰经纬度（高斯分布在 65% 半径内）"""
    distance = radius_m * math.sqrt(random.random()) * 0.65
    theta = random.random() * 2 * math.pi
    dlat = (distance * math.sin(theta)) / 111320.0
    dlng = (distance * math.cos(theta)) / (111320.0 * max(0.2, math.cos(math.radians(lat))))
    return round(lat + dlat, 6), round(lng + dlng, 6)


def courses_time_overlap(c1, c2):
    s1, e1 = parse_course_time_range(c1)
    s2, e2 = parse_course_time_range(c2)
    # Unknown schedules cannot establish that selecting another class is safe.
    if not s1 or not e1 or not s2 or not e2 or e1 <= s1 or e2 <= s2:
        return True
    return max(s1, s2) < min(e1, e2)

def get_user_category_demands(selected_courses, sem_start=None, sem_end=None, requirements=None):
    standards = requirements or REQUIREMENTS
    counts = {category: 0 for category in standards}
    current = china_now()
    for course in selected_courses or []:
        start, end = parse_course_time_range(course)
        if not start or not end or not sem_start or not sem_end or not sem_start <= start <= end <= sem_end:
            continue
        # Upcoming reservations and pending official assessment occupy the target;
        # an explicitly failed, finished class does not occupy it forever.
        if end < current and str(course.get("pass")) == "0":
            continue
        category = get_course_category(course)
        if category in counts:
            counts[category] += 1
    return {k: {"required": v, "count": counts[k], "remaining": max(0, v-counts[k])} for k, v in standards.items()}

def calculate_candidate_priority(course: Dict[str, Any], demands: Dict[str, Dict[str, int]]) -> int:
    """
    计算课程抢选优先级权重：
    - 缺口最大的板块优先级最高 (权重: 100 + remaining * 10)；
    - 缺口已满足 (saturated, remaining == 0) 的板块优先级低 (权重: 10)；
    - 其他可选板块 (权重: 20)；
    - 支持线上定位签到的课程优先加权 (+50)；不支持自主打卡的课大幅惩罚 (-100)。
    """
    cat = get_course_category(course)
    score = 20
    if cat in demands:
        rem = demands[cat].get("remaining", 0)
        if rem > 0:
            score = 100 + rem * 10
        else:
            score = 10
    if has_autonomous_sign(course):
        score += 50
    else:
        score -= 100
    return score


def capacity_available(course):
    current, maximum = capacity_values(course)
    if isinstance(current, bool) or isinstance(maximum, bool):
        return False
    if not str(current).isdigit() or not str(maximum).isdigit():
        return False
    return 0 <= int(current) < int(maximum)

def capacity_values(course):
    current = next((course.get(key) for key in ("courseCurrentCount", "courseCurrentNum", "currentCount") if course.get(key) is not None), None)
    maximum = next((course.get(key) for key in ("courseMaxCount", "courseMaxNum", "maxCount") if course.get(key) is not None), None)
    return current, maximum

def is_auto_select_candidate(course, now, campus="北京", require_auto_sign=True):
    if permanently_excluded(course):return False
    if not course_id(course) or not course_matches_campus(course, campus):
        return False
    if get_course_category(course) not in REQUIREMENTS or not autonomous(course, require_windows=True):
        return False
    status = str(course.get("courseStatus") or course.get("status") or "")
    if any(word in status for word in ("停开", "取消", "未发布", "结课", "结束", "关闭")):
        return False
    start, end = parse_course_time_range(course)
    return bool(start and end and now < start < end and capacity_available(course) and in_window(course.get("courseSelectStartDate"), course.get("courseSelectEndDate"), now))

class BoyaScheduler:
    def __init__(self, get_accounts_func, add_log_func, ordinary_courses=None):
        self.get_accounts = get_accounts_func
        self.add_log = add_log_func
        self.ordinary_courses = ordinary_courses
        self.clock = china_now
        self.running = False
        self.interval_seconds = 60
        self._thread = None
        self._stop_event = threading.Event()
        self._lifecycle = threading.Lock()
        self._tick_lock = threading.Lock()
        self.logged_pool_summary = set()
        self.last_sync_times = {}
        self.last_pool_sync_times = {}
        self.last_inspect_log_times = {}
        self.done_records = set()
        self.chosen_history = set()
        self.fail_counters = {}
        self._workers = None
        self._warnings = {}

    def _warn_course(self, acc, cid, action, message, level="warning", notify=True):
        key=(acc.username,cid,action)
        if self._warnings.get(key)==message:
            return
        if len(self._warnings)>=512:
            self._warnings.pop(next(iter(self._warnings)))
        self._warnings[key]=message
        extra={} if notify else {"notify":False}
        self.add_log(level,message,username=acc.username,user_name=acc.name,category="boya",**extra)

    def start(self, interval_seconds=60):
        with self._lifecycle:
            if self.running:
                return
            if self._thread and self._thread.is_alive():
                raise RuntimeError("旧守护仍在安全停止，暂不能重启")
            self.interval_seconds = max(5, min(60, interval_seconds))
            self.running = True
            self._stop_event = threading.Event()
            event = self._stop_event
            self._thread = threading.Thread(target=self._run_loop, args=(event,), daemon=True, name="BoyaScheduler")
            self._thread.start()
        self.add_log("info", "博雅守护已启动；课池每60秒静默同步。", category="boya")

    def stop(self):
        with self._lifecycle:
            self.running = False
            self._stop_event.set()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self.add_log("info", "已暂停博雅后续提交；在途请求会完成并复核。", category="boya")

    def remove_account(self, username):
        for mapping in (self.last_sync_times, self.last_pool_sync_times, self.last_inspect_log_times):
            mapping.pop(username, None)
        self.logged_pool_summary.discard(username)
        self.chosen_history.difference_update(k for k in list(self.chosen_history) if k[0] == username)
        self.done_records.difference_update(k for k in list(self.done_records) if k.startswith(username + "_"))
        for key in list(self.fail_counters):
            if key[0] == username:
                self.fail_counters.pop(key, None)
        for key in list(self._warnings):
            if key[0]==username:
                self._warnings.pop(key,None)

    def _run_loop(self, event):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="BoyaAccount") as workers:
            self._workers = workers
            try:
                while self.running and not event.is_set():
                    self.tick(event)
                    event.wait(min(self.interval_seconds, 10))
            finally:
                self._workers = None

    def _renew_session(self, acc):
        from core.boya_actions import account_lock
        # Page reads, manual actions and the worker share this same gate. Keep
        # the check and renewal together so parallel refreshes reuse one token.
        with account_lock(acc):
            return self._renew_session_locked(acc)

    def _renew_session_locked(self, acc):
        if getattr(acc, "removed", False) or getattr(acc, "maintenance", False) or getattr(acc, "auth_requires_input", False):
            return False
        if acc.boya_client.is_authenticated():
            return True
        if time.monotonic() < max(getattr(acc, "boya_auth_retry_after", 0), getattr(acc, "auth_retry_after", 0)):
            return False
        acc.boya_auth_retry_after = time.monotonic() + 60
        try:
            acc.boya_client.sync_cookies_from(acc.client.client.cookies)
            token = acc.boya_client.acquire_token()
            if token:
                return True
            return False
        except BoyaApiError as exc:
            if exc.code == "captcha_required":
                acc.auth_requires_input = True
                return False
            if exc.code != "session_expired":
                return False
        except httpx.HTTPError:
            # Transport failure does not justify submitting the password next.
            return False
        except Exception:
            return False
        if not getattr(acc, "password", None):
            return False
        try:
            return bool(acc.boya_client.login_with_credentials(acc.username, acc.password))
        except BoyaApiError as exc:
            if exc.code == "captcha_required" or (exc.code == "cas_error" and any(word in exc.message for word in ("账号", "密码"))):
                acc.auth_requires_input = True
            return False
        except Exception:
            return False

    def tick(self, event=None):
        if not self._tick_lock.acquire(blocking=False):
            return
        try:
            active = [a for a in self.get_accounts() if not getattr(a, "removed", False) and (getattr(a, "boya_auto_select", False) or getattr(a, "boya_auto_sign", False))]
            if self._workers:
                futures = [self._workers.submit(self._check_account, a, event) for a in active]
                for future in futures:
                    try:
                        future.result()
                    except Exception as exc:
                        logger.warning("博雅账号任务异常: %s", type(exc).__name__)
            else:
                for acc in active:
                    self._check_account(acc, event)
        finally:
            self._tick_lock.release()

    def _check_account(self, acc, event):
        from core.boya_actions import account_lock, reconcile_official
        def active():
            return not getattr(acc, "removed", False) and not getattr(acc, "maintenance", False) and (event is None or (self.running and not event.is_set()))
        if not active():
            return
        try:
            with account_lock(acc):
                if not acc.boya_client.is_authenticated() and not self._renew_session(acc):
                    raise BoyaSessionExpired("请重新认证或输入验证码")
                stamp = time.monotonic()
                if acc.username not in self.last_sync_times or stamp-self.last_sync_times[acc.username] >= 60:
                    acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
                    reconcile_official(acc, acc.boya_selected_courses)
                    self.last_sync_times[acc.username] = time.monotonic()
                    acc.boya_health = {**getattr(acc, "boya_health", {}), "last_success": self.clock().isoformat(timespec="seconds")}
                if acc.username not in self.last_pool_sync_times or stamp-self.last_pool_sync_times[acc.username] >= 60:
                    acc.boya_all_courses = acc.boya_client.query_courses()
                    self.last_pool_sync_times[acc.username] = time.monotonic()
                    acc.boya_health = {**getattr(acc, "boya_health", {}), "last_success": self.clock().isoformat(timespec="seconds")}
                acc.boya_health = {**getattr(acc, "boya_health", {}), "stale": False, "error": None, "next_sync_in_seconds": max(0, round(60-(time.monotonic()-self.last_sync_times[acc.username])))}
            if acc.username not in self.logged_pool_summary:
                self.logged_pool_summary.add(acc.username)
                excluded = sum(not autonomous(c, require_windows=True) for c in (acc.boya_all_courses or []))
                message = f"博雅抢课守护中：全校课池共 {len(acc.boya_all_courses or [])} 门，{excluded} 门非线上打卡安全排除；持续静默同步。"
                self.add_log("info", message, username=acc.username, user_name=acc.name, category="boya")
            if active() and getattr(acc, "boya_auto_select", False):
                self._check_auto_select(acc, self.clock(), active)
            if active() and getattr(acc, "boya_auto_sign", False):
                self._check_auto_sign(acc, self.clock(), active)
        except Exception as exc:
            error = type(exc).__name__
            previous = getattr(acc, "boya_health", {}).get("error")
            acc.boya_health = {"stale": True, "error": error, "last_success": getattr(acc, "boya_health", {}).get("last_success")}
            if previous != error:
                self.add_log("warning", "博雅同步/守护暂不可用：" + error, username=acc.username, user_name=acc.name, category="boya")

    def _check_auto_select(self, acc, now, active=lambda: True):
        from core.boya_actions import perform_boya_action
        info = acc.boya_client.semester_info
        start, end = semester_bounds(info or {})
        if not start or not end:
            return
        demands = get_user_category_demands(acc.boya_selected_courses, start, end, getattr(acc, "boya_targets", None))
        candidates = [c for c in (acc.boya_all_courses or []) if is_auto_select_candidate(c, self.clock(), getattr(acc, "campus", "北京"))]
        candidates.sort(key=lambda c: calculate_candidate_priority(c, demands), reverse=True)
        for course in candidates:
            if not active() or not getattr(acc, "boya_auto_select", False):
                break
            try:
                result = perform_boya_action(acc, "select", course_id(course), automatic=True, guard=lambda: active() and acc.boya_auto_select, renew=self._renew_session, ordinary=self.ordinary_courses)
                if result.get("submitted"):
                    self._warnings.pop((acc.username,course_id(course),"select"),None)
                    self.add_log("success", "博雅选课请求已被学校接受。", username=acc.username, user_name=acc.name, category="boya")
                if result.get("pending_verification"):
                    break
            except (BoyaApiError, BoyaSessionExpired) as exc:
                if isinstance(exc,BoyaApiError) and exc.code=="target_filled":
                    self._warnings.pop((acc.username,course_id(course),"select"),None)
                    self._warn_course(acc,"category:"+get_course_category(course),"select-normal",
                        "本类别已完成或已有足够预约，已按设置停止额外抢选。",level="info",notify=False)
                elif isinstance(exc,BoyaApiError) and exc.code in ("user_declined","permanently_excluded"):
                    self._warn_course(acc,course_id(course),"select-declined",exc.message,level="info",notify=False)
                else:
                    self._warn_course(acc,course_id(course),"select","本门选课暂未执行：" + str(exc))
            except Exception as exc:
                self._warn_course(acc,course_id(course),"select","本门选课异常：" + type(exc).__name__)

    def _check_auto_sign(self, acc, now, active=lambda: True):
        from core.boya_actions import perform_boya_action, merge_selected
        from core.domain import attendance_allowed
        for raw in list(acc.boya_selected_courses or []):
            for sign_type in (1, 2):
                if not active() or not getattr(acc, "boya_auto_sign", False):
                    return
                course = merge_selected(raw, acc.boya_all_courses or [])
                if not attendance_allowed(course, sign_type, self.clock()):
                    continue
                try:
                    result = perform_boya_action(acc, "sign", course_id(course), sign_type=sign_type, automatic=True, guard=lambda: active() and acc.boya_auto_sign, renew=self._renew_session)
                    if result.get("submitted"):
                        self._warnings.pop((acc.username,course_id(course),"sign"+str(sign_type)),None)
                        self.add_log("success", "博雅考勤请求已被学校接受，最终考核以官方结果为准。", username=acc.username, user_name=acc.name, category="boya")
                    if result.get("pending_verification"):
                        return
                except Exception as exc:
                    self._warn_course(acc,course_id(course),"sign"+str(sign_type),"本门考勤暂未完成：" + type(exc).__name__)
