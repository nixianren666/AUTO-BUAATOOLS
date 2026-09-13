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
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
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
        val = kind.get("kindName") or ""
    else:
        val = course.get("courseKind") or course.get("kindName") or course.get("courseType") or ""
    if "安全" in val or "健康" in val:
        return "安全健康"
    return val


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
        # 记录 3 次失败熔断字典：(username, target_key) -> fail_count
        self.fail_counters: Dict[Tuple[str, Any], int] = {}
        # 已完成操作防重记录：(username, action, course_id, date_str) -> bool
        self.done_records: Set[str] = set()
        # 记录选课成功或已报名的历史：(username, course_id_or_name)
        self.chosen_history: Set[Tuple[str, str]] = set()
        # 记录各账号后台周期静默同步已选课表的时间戳：username -> float
        self.last_sync_times: Dict[str, float] = {}

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

            # 定期静默同步最新已选课程（每 5 分钟巡检一次）
            # 确保无论课程是本软件自动抢到的，还是学生在微信小程序/学校官网自行选中的，都能被守护引擎自动捕获并无缝纳入自动签到/签退！
            if username not in self.last_sync_times:
                self.last_sync_times[username] = time.time()
            elif time.time() - self.last_sync_times[username] > 300:
                try:
                    synced = acc.boya_client.query_chosen_courses()
                    if synced:
                        acc.boya_selected_courses = synced
                    self.last_sync_times[username] = time.time()
                except Exception as sync_e:
                    logger.debug(f"Auto sync chosen courses error for {username}: {sync_e}")

            # 1. 自动抢选课流程
            if getattr(acc, "boya_auto_select", False):
                self._check_auto_select(acc, now)

            # 2. 自动签到/签退流程（覆盖全部已选课程，包含自选与代抢课程）
            if getattr(acc, "boya_auto_sign", False):
                self._check_auto_sign(acc, now)

    def _check_auto_select(self, acc: Any, now: datetime) -> None:
        username = acc.username
        user_name = acc.name
        campus = getattr(acc, "campus", "北京")
        cached_courses: List[Dict[str, Any]] = getattr(acc, "boya_all_courses", [])
        
        # 建立当前已选课程的完备索引（提取所有可能的 ID 形式与课程名）
        selected_ids: Set[str] = set()
        selected_names: Set[str] = set()
        for c in getattr(acc, "boya_selected_courses", []):
            for k in ("id", "courseId", "course_id", "chosenCourseId"):
                v = c.get(k)
                if v is not None:
                    selected_ids.add(str(v))
            name = (c.get("courseName") or c.get("name") or "").strip()
            if name:
                selected_names.add(name)

        for course in cached_courses:
            cid = course.get("id") or course.get("courseId")
            if not cid:
                continue
            cid_str = str(cid)
            cname = (course.get("courseName") or course.get("name") or cid_str).strip()

            # 防重检查 1：已在已选课程列表中
            if cid_str in selected_ids or cname in selected_names:
                continue

            # 防重检查 2：已在运行时已选历史中（已抢中或服务端提示已报名过）
            if (username, cid_str) in self.chosen_history or (username, cname) in self.chosen_history:
                continue

            # 检查熔断：连续失败达 3 次则本轮停止重试
            fail_key = (username, cid)
            fail_key_str = (username, cid_str)
            if self.fail_counters.get(fail_key, 0) >= 3 or self.fail_counters.get(fail_key_str, 0) >= 3:
                continue

            # 检查候选条件（校区、分类、自主签到、选课时间窗口、容量）
            if is_auto_select_candidate(course, now, campus=campus):
                self.add_log(
                    "info",
                    f"发现符合策略的博雅课程 [{cname} (ID: {cid})]，正在触发自动抢课...",
                    username=username,
                    user_name=user_name,
                    category="boya",
                )
                try:
                    res = acc.boya_client.select_course(cid)
                    # 抢课成功！登记历史防重
                    self.chosen_history.add((username, cid_str))
                    self.chosen_history.add((username, cname))
                    self.fail_counters.pop(fail_key, None)
                    self.fail_counters.pop(fail_key_str, None)
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
                    err_msg = str(e.message or "")
                    already_selected_keywords = ["已报名", "重复报名", "已经选", "已存在", "已参加", "请勿重复", "不可重复"]
                    if any(kw in err_msg for kw in already_selected_keywords):
                        # 服务器反馈已经报名或不可重复，明确为已选课程，坚决不再重复发送请求！
                        self.chosen_history.add((username, cid_str))
                        self.chosen_history.add((username, cname))
                        self.fail_counters.pop(fail_key, None)
                        self.fail_counters.pop(fail_key_str, None)
                        self.add_log(
                            "info",
                            f"博雅课程 [{cname} (ID: {cid})] 提示已报名/已在选课记录中，已自动标记并停止后续抢课请求。",
                            username=username,
                            user_name=user_name,
                            category="boya",
                        )
                        try:
                            acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
                        except Exception:
                            pass
                    else:
                        self.fail_counters[fail_key] = self.fail_counters.get(fail_key, 0) + 1
                        self.fail_counters[fail_key_str] = self.fail_counters[fail_key]
                        attempts = self.fail_counters[fail_key]
                        if attempts >= 3:
                            self.add_log(
                                "warning",
                                f"抢课 [{cname}] 连续尝试失败达到安全上限 (3次)，已触发熔断保护，本轮停止重试以防风控。",
                                username=username,
                                user_name=user_name,
                                category="boya",
                            )
                        else:
                            self.add_log(
                                "warning",
                                f"抢课 [{cname}] 响应提示: {e.message} (重试 {attempts}/3 次)",
                                username=username,
                                user_name=user_name,
                                category="boya",
                            )
                except Exception as e:
                    self.add_log(
                        "error",
                        f"抢课 [{cname}] 发生网络异常: {e}",
                        username=username,
                        user_name=user_name,
                        category="boya",
                    )

    def _check_auto_sign(self, acc: Any, now: datetime) -> None:
        username = acc.username
        user_name = acc.name
        chosen_courses: List[Dict[str, Any]] = getattr(acc, "boya_selected_courses", [])
        today_str = now.strftime("%Y-%m-%d")

        for course in chosen_courses:
            cid = course.get("id") or course.get("courseId")
            if not cid:
                continue
            cid_str = str(cid)
            cname = course.get("courseName") or course.get("name") or cid_str

            # 检查课程状态：已结课或已结束跳过
            status_str = str(course.get("courseStatus") or course.get("status") or "")
            if "结课" in status_str or "结束" in status_str:
                continue

            cfg = parse_sign_config(course.get("courseSignConfig"))
            points = cfg.get("signPointList") or []
            
            # 【重要逻辑增强】：如果学生手动在手机/网页端选的课在已选课程接口中缺少签到配置，
            # 自动从全量学期课池 boya_all_courses 中检索补齐老师配置的签到定位经纬度与时间窗口！
            if not points:
                pool_match = next((c for c in getattr(acc, "boya_all_courses", []) if (
                    str(c.get("id")) == cid_str or str(c.get("courseId")) == cid_str or 
                    (c.get("courseName") and c.get("courseName") == course.get("courseName"))
                )), None)
                if pool_match:
                    cfg = parse_sign_config(pool_match.get("courseSignConfig"))
                    points = cfg.get("signPointList") or []
                    if not course.get("courseStartDate"):
                        course["courseStartDate"] = pool_match.get("courseStartDate")
                        course["courseStartTime"] = pool_match.get("courseStartTime")
                        course["courseEndDate"] = pool_match.get("courseEndDate")
                        course["courseEndTime"] = pool_match.get("courseEndTime")

            if not points:
                continue  # 无自主定位打卡配置（如线下纸质签名或闸机刷卡课），安全跳过

            ref_point = points[-1]
            try:
                base_lat = float(ref_point.get("lat") or ref_point.get("signLat") or 0)
                base_lng = float(ref_point.get("lng") or ref_point.get("signLng") or 0)
                radius = float(ref_point.get("radius") or ref_point.get("signRadius") or 15)
            except (ValueError, TypeError):
                continue

            # 1. 签到检查
            sign_key = f"{username}_sign_{cid_str}_{today_str}"
            already_signed = (course.get("signStatus") == 1 or course.get("courseSignStatus") == 1 or course.get("signInStatus") == 1)
            if already_signed:
                self.done_records.add(sign_key)

            sign_fail_key = (username, f"sign_{cid_str}_{today_str}")
            if sign_key not in self.done_records and self.fail_counters.get(sign_fail_key, 0) < 3:
                in_sign_window = in_window(cfg.get("signStartDate"), cfg.get("signEndDate"), now)
                if not in_sign_window and not cfg.get("signStartDate"):
                    c_start = parse_dt(f"{course.get('courseStartDate')} {course.get('courseStartTime')}") if course.get('courseStartDate') and course.get('courseStartTime') else None
                    if c_start:
                        from datetime import timedelta
                        if c_start - timedelta(minutes=15) <= now <= c_start + timedelta(minutes=30):
                            in_sign_window = True

                if in_sign_window:
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
                        self.fail_counters.pop(sign_fail_key, None)
                        self.add_log(
                            "success",
                            f"✅ 博雅课程 [{cname}] 自动签到成功！",
                            username=username,
                            user_name=user_name,
                            category="boya",
                        )
                    except Exception as e:
                        err_msg = str(e)
                        if any(kw in err_msg for kw in ["已签到", "不能重复", "已完成"]):
                            self.done_records.add(sign_key)
                            self.fail_counters.pop(sign_fail_key, None)
                            self.add_log("info", f"博雅课程 [{cname}] 提示已完成签到，记录完成状态。", username=username, user_name=user_name, category="boya")
                        else:
                            self.fail_counters[sign_fail_key] = self.fail_counters.get(sign_fail_key, 0) + 1
                            attempts = self.fail_counters[sign_fail_key]
                            self.add_log(
                                "warning" if attempts < 3 else "error",
                                f"博雅课程 [{cname}] 自动签到未能完成: {e} ({attempts}/3 次)",
                                username=username,
                                user_name=user_name,
                                category="boya",
                            )

            # 2. 签退检查
            signout_key = f"{username}_signout_{cid_str}_{today_str}"
            already_signed_out = (course.get("signOutStatus") == 1 or course.get("courseSignOutStatus") == 1)
            if already_signed_out:
                self.done_records.add(signout_key)

            signout_fail_key = (username, f"signout_{cid_str}_{today_str}")
            if signout_key not in self.done_records and self.fail_counters.get(signout_fail_key, 0) < 3:
                in_signout_window = in_window(cfg.get("signOutStartDate"), cfg.get("signOutEndDate"), now)
                if not in_signout_window and not cfg.get("signOutStartDate"):
                    c_end = parse_dt(f"{course.get('courseEndDate')} {course.get('courseEndTime')}") if course.get('courseEndDate') and course.get('courseEndTime') else None
                    if c_end:
                        from datetime import timedelta
                        if c_end - timedelta(minutes=15) <= now <= c_end + timedelta(minutes=30):
                            in_signout_window = True

                if in_signout_window:
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
                        self.fail_counters.pop(signout_fail_key, None)
                        self.add_log(
                            "success",
                            f"🏁 博雅课程 [{cname}] 自动签退成功！",
                            username=username,
                            user_name=user_name,
                            category="boya",
                        )
                    except Exception as e:
                        err_msg = str(e)
                        if any(kw in err_msg for kw in ["已签退", "不能重复", "已完成"]):
                            self.done_records.add(signout_key)
                            self.fail_counters.pop(signout_fail_key, None)
                            self.add_log("info", f"博雅课程 [{cname}] 提示已完成签退，记录完成状态。", username=username, user_name=user_name, category="boya")
                        else:
                            self.fail_counters[signout_fail_key] = self.fail_counters.get(signout_fail_key, 0) + 1
                            attempts = self.fail_counters[signout_fail_key]
                            self.add_log(
                                "warning" if attempts < 3 else "error",
                                f"博雅课程 [{cname}] 自动签退未能完成: {e} ({attempts}/3 次)",
                                username=username,
                                user_name=user_name,
                                category="boya",
                            )