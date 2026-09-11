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
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core.boya_client import BoyaClient, BoyaApiError, BoyaSessionExpired

logger = logging.getLogger(__name__)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def in_window(start: Optional[str], end: Optional[str], now: datetime) -> bool:
    parsed_start = parse_dt(start)
    parsed_end = parse_dt(end)
    return bool(parsed_start and parsed_end and parsed_start <= now <= parsed_end)


def parse_sign_config(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    text = raw.replace('\"', '"')
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


def has_autonomous_sign(course: Dict[str, Any]) -> bool:
    cfg = parse_sign_config(course.get("courseSignConfig"))
    points = cfg.get("signPointList")
    return isinstance(points, list) and len(points) > 0


def get_course_category(course: Dict[str, Any]) -> str:
    kind = course.get("courseNewKind2")
    if isinstance(kind, dict):
        return kind.get("kindName") or ""
    return course.get("courseKind") or course.get("kindName") or ""


def course_matches_campus(course: Dict[str, Any], campus_preference: str = "北京") -> bool:
    """校区匹配：杭州学生只抢杭州课，北京学生只抢非杭州课"""
    combined = " ".join([
        str(course.get("courseName") or ""),
        str(course.get("name") or ""),
        str(course.get("coursePosition") or ""),
        str(course.get("courseCampusList") or ""),
    ])
    is_hangzhou = "杭州" in combined
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


def is_auto_select_candidate(course: Dict[str, Any], now: datetime, campus: str = "北京") -> bool:
    if not course_matches_campus(course, campus):
        return False
    if get_course_category(course) == "其他方面":
        return False
    if not has_autonomous_sign(course):
        return False
    # 检查选课时间
    if not in_window(course.get("courseSelectStartDate"), course.get("courseSelectEndDate"), now):
        return False
    # 检查容量
    cur = course.get("courseCurrentCount")
    max_c = course.get("courseMaxCount")
    if cur is not None and max_c is not None:
        try:
            if int(cur) >= int(max_c):
                return False
        except Exception:
            pass
    return True


class BoyaScheduler:
    def __init__(self, get_accounts_func: Callable[[], List[Any]], add_log_func: Callable[..., None]) -> None:
        self.get_accounts = get_accounts_func
        self.add_log = add_log_func
        self.running = False
        self.interval_seconds = 60
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        # 记录 3 次失败熔断字典：(username, course_id) -> fail_count
        self.fail_counters: Dict[Tuple[str, int], int] = {}
        # 已完成操作防重记录：(username, action, course_id, date_str) -> bool
        self.done_records: Set[str] = set()

    def start(self, interval_seconds: int = 60) -> None:
        if self.running:
            return
        self.interval_seconds = interval_seconds
        self.running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="BoyaSchedulerThread")
        self._thread.start()
        self.add_log("info", f"博雅自动化守护任务已启动，巡检周期: {self.interval_seconds} 秒", category="boya")

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.add_log("info", "博雅自动化守护任务已停止", category="boya")

    def _run_loop(self) -> None:
        while self.running and not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.error(f"BoyaScheduler tick error: {e}", exc_info=True)
            self._stop_event.wait(self.interval_seconds)

    def tick(self) -> None:
        now = datetime.now()
        accounts = self.get_accounts()

        for acc in accounts:
            if not getattr(acc, "boya_auto_select", False) and not getattr(acc, "boya_auto_sign", False):
                continue
            username = acc.username
            user_name = acc.name
            boya_client: BoyaClient = getattr(acc, "boya_client", None)
            if not boya_client or not boya_client.is_authenticated():
                continue

            # 1. 自动抢选课流程
            if getattr(acc, "boya_auto_select", False):
                self._check_auto_select(acc, now)

            # 2. 自动签到/签退流程
            if getattr(acc, "boya_auto_sign", False):
                self._check_auto_sign(acc, now)

    def _check_auto_select(self, acc: Any, now: datetime) -> None:
        username = acc.username
        user_name = acc.name
        campus = getattr(acc, "campus", "北京")
        cached_courses: List[Dict[str, Any]] = getattr(acc, "boya_all_courses", [])
        selected_ids: Set[int] = {c.get("id") or c.get("courseId") for c in getattr(acc, "boya_selected_courses", [])}

        for course in cached_courses:
            cid = course.get("id")
            if not cid or cid in selected_ids:
                continue

            # 检查熔断
            fail_key = (username, cid)
            if self.fail_counters.get(fail_key, 0) >= 3:
                continue

            # 检查候选条件
            if is_auto_select_candidate(course, now, campus=campus):
                cname = course.get("courseName") or course.get("name") or str(cid)
                self.add_log(
                    "info",
                    f"发现符合策略的博雅课程 [{cname} (ID: {cid})]，正在触发自动抢课...",
                    username=username,
                    user_name=user_name,
                    category="boya",
                )
                try:
                    res = acc.boya_client.select_course(cid)
                    self.add_log(
                        "success",
                        f"🎉 成功抢中博雅课程 [{cname}]！已加入课表",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )
                    # 选课成功后，刷新已选列表
                    try:
                        acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
                    except Exception:
                        pass
                except BoyaApiError as e:
                    self.fail_counters[fail_key] = self.fail_counters.get(fail_key, 0) + 1
                    attempts = self.fail_counters[fail_key]
                    self.add_log(
                        "warning",
                        f"抢课 [{cname}] 响应提示: {e.message} (累计失败: {attempts}/3 次)",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )
                except Exception as e:
                    self.add_log(
                        "error",
                        f"抢课 [{cname}] 发生异常: {e}",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )

    def _check_auto_sign(self, acc: Any, now: datetime) -> None:
        username = acc.username
        user_name = acc.name
        chosen_courses: List[Dict[str, Any]] = getattr(acc, "boya_selected_courses", [])

        for course in chosen_courses:
            cid = course.get("id") or course.get("courseId")
            if not cid:
                continue
            cname = course.get("courseName") or course.get("name") or str(cid)
            cfg = parse_sign_config(course.get("courseSignConfig"))
            points = cfg.get("signPointList") or []
            if not points:
                continue  # 无定位配置无法执行自主签到

            ref_point = points[-1]
            try:
                base_lat = float(ref_point.get("lat") or ref_point.get("signLat") or 0)
                base_lng = float(ref_point.get("lng") or ref_point.get("signLng") or 0)
                radius = float(ref_point.get("radius") or ref_point.get("signRadius") or 15)
            except (ValueError, TypeError):
                continue

            today_str = now.strftime("%Y-%m-%d")

            # 1. 签到检查
            sign_key = f"{username}_sign_{cid}_{today_str}"
            if sign_key not in self.done_records and in_window(cfg.get("signStartDate"), cfg.get("signEndDate"), now):
                lat, lng = random_point_in_radius(base_lat, base_lng, radius)
                self.add_log(
                    "info",
                    f"进入博雅课程 [{cname}] 签到窗口，正在生成定位坐标 ({lat}, {lng}) 提交签到...",
                    username=username,
                    user_name=user_name,
                    category="boya",
                )
                try:
                    acc.boya_client.sign_course(cid, lat, lng, sign_type=1)
                    self.done_records.add(sign_key)
                    self.add_log(
                        "success",
                        f"✅ 博雅课程 [{cname}] 自动签到成功！",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )
                except Exception as e:
                    self.add_log(
                        "warning",
                        f"博雅课程 [{cname}] 自动签到未能完成: {e}",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )

            # 2. 签退检查
            signout_key = f"{username}_signout_{cid}_{today_str}"
            if signout_key not in self.done_records and in_window(cfg.get("signOutStartDate"), cfg.get("signOutEndDate"), now):
                lat, lng = random_point_in_radius(base_lat, base_lng, radius)
                self.add_log(
                    "info",
                    f"进入博雅课程 [{cname}] 签退窗口，正在生成定位坐标 ({lat}, {lng}) 提交签退...",
                    username=username,
                    user_name=user_name,
                    category="boya",
                )
                try:
                    acc.boya_client.sign_course(cid, lat, lng, sign_type=2)
                    self.done_records.add(signout_key)
                    self.add_log(
                        "success",
                        f"🏁 博雅课程 [{cname}] 自动签退成功！",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )
                except Exception as e:
                    self.add_log(
                        "warning",
                        f"博雅课程 [{cname}] 自动签退未能完成: {e}",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )