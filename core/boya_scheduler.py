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
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return None


def get_current_semester_range(ref_date: Optional[datetime] = None) -> Tuple[datetime, datetime, str]:
    """
    根据北航校历基准动态推算当前所属学期起止时间与学期全称：
    - 秋季学期（第一学期）：通常自当年 8 月下旬（约 8-25）开学至次年 1 月中下旬（约 1-20）；
    - 春季学期（第二学期）：通常自当年 2 月中旬（约 2-15）开学至当年 7 月上旬（约 7-10）；
    - 夏季学期（第三学期）：7 月中旬至 8 月中旬。
    """
    dt = ref_date or datetime.now()
    y = dt.year
    m = dt.month

    if m in (9, 10, 11, 12):
        start = datetime(y, 8, 25, 0, 0, 0)
        end = datetime(y + 1, 1, 31, 23, 59, 59)
        name = f"{y}-{y+1}学年第一学期（秋季）"
    elif m == 1:
        start = datetime(y - 1, 8, 25, 0, 0, 0)
        end = datetime(y, 1, 31, 23, 59, 59)
        name = f"{y-1}-{y}学年第一学期（秋季）"
    else:
        start = datetime(y, 2, 15, 0, 0, 0)
        end = datetime(y, 7, 15, 23, 59, 59)
        name = f"{y-1}-{y}学年第二学期（春季）"

    return start, end, name


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
    cfg = parse_sign_config(course.get("courseSignConfig") or course.get("signConfig"))
    points = cfg.get("signPointList")
    return isinstance(points, list) and len(points) > 0


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


def parse_course_time_range(course: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    解析博雅课程上课起止时间：
    优先从 courseStartDate / courseStartTime / courseEndDate / courseEndTime 组合解析；
    兼顾 courseTime 或 timeRange 文本字符串。
    """
    start_d = course.get("courseStartDate") or course.get("startDate")
    start_t = course.get("courseStartTime") or course.get("startTime")
    end_d = course.get("courseEndDate") or course.get("endDate")
    end_t = course.get("courseEndTime") or course.get("endTime")

    start_dt = None
    end_dt = None

    if start_d and start_t:
        start_dt = parse_dt(f"{start_d} {start_t}")
    elif start_d:
        start_dt = parse_dt(str(start_d))

    if end_d and end_t:
        end_dt = parse_dt(f"{end_d} {end_t}")
    elif end_d:
        end_dt = parse_dt(str(end_d))

    if (not start_dt or not end_dt) and course.get("courseTime"):
        ctime = str(course["courseTime"]).replace("至", "-").replace("~", "-")
        if "-" in ctime:
            parts = ctime.split("-", 1)
            p1 = parse_dt(parts[0].strip())
            p2 = parse_dt(parts[1].strip())
            if p1 and p2:
                start_dt = p1
                end_dt = p2

    return start_dt, end_dt


def courses_time_overlap(c1: Dict[str, Any], c2: Dict[str, Any]) -> bool:
    """
    判断两门课程的上课时间是否存在冲突（重叠）：
    两门课程均有明确起止时间且为正常时间段时：
    max(start1, start2) < min(end1, end2) 为区间交集。
    """
    s1, e1 = parse_course_time_range(c1)
    s2, e2 = parse_course_time_range(c2)
    if not s1 or not e1 or not s2 or not e2:
        return False
    if e1 <= s1 or e2 <= s2:
        return False
    return max(s1, s2) < min(e1, e2)


def get_user_category_demands(
    selected_courses: List[Dict[str, Any]],
    sem_start: Optional[datetime] = None,
    sem_end: Optional[datetime] = None
) -> Dict[str, Dict[str, int]]:
    """
    分析学生本学期已选/已修各板块课程数与达标缺口：
    基准要求：德育: 2, 劳育: 2, 美育: 1, 安全健康: 1
    返回各板块达标需求与剩余缺口
    """
    standards = {
        "德育": 2,
        "劳育": 2,
        "美育": 1,
        "安全健康": 1,
    }
    counts = {"德育": 0, "劳育": 0, "美育": 0, "安全健康": 0}
    for c in selected_courses or []:
        if sem_start and sem_end:
            c_date_str = c.get("courseStartDate") or c.get("courseEndDate") or c.get("selectDate")
            c_dt = parse_dt(c_date_str)
            if c_dt and not (sem_start <= c_dt <= sem_end):
                continue
        cat = get_course_category(c)
        if cat in counts:
            counts[cat] += 1

    demands = {}
    for k, req in standards.items():
        cnt = counts.get(k, 0)
        demands[k] = {
            "required": req,
            "count": cnt,
            "remaining": max(0, req - cnt),
        }
    return demands


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


def is_auto_select_candidate(
    course: Dict[str, Any],
    now: datetime,
    campus: str = "北京",
    require_auto_sign: bool = True
) -> bool:
    if not course_matches_campus(course, campus):
        return False
    if get_course_category(course) == "其他方面":
        return False
    # 安全性铁律：全自动秒抢仅抢选支持线上自主打卡的课程（现场刷卡/核验考勤课程严禁抢选，杜绝旷课违约）
    if not has_autonomous_sign(course):
        return False

    # 检查课程是否停开/取消/已结束
    status_str = str(course.get("courseStatus") or course.get("status") or "")
    if any(kw in status_str for kw in ("已停开", "已取消", "未发布", "已结课", "已结束", "关闭")):
        return False

    # 检查上课时间：已过上课时间的课程坚决不选
    s_dt, e_dt = parse_course_time_range(course)
    if e_dt and e_dt <= now:
        return False

    # 检查选课时间窗口（如果差 <= 5 秒允许放行做高精度临近等待）
    if not in_window(course.get("courseSelectStartDate"), course.get("courseSelectEndDate"), now):
        sel_start = parse_dt(course.get("courseSelectStartDate"))
        if sel_start and 0 < (sel_start - now).total_seconds() <= 5:
            pass
        else:
            return False

    # 检查容量
    cur = course.get("courseCurrentCount") if course.get("courseCurrentCount") is not None else (course.get("courseCurrentNum") if course.get("courseCurrentNum") is not None else course.get("currentCount"))
    max_c = course.get("courseMaxCount") if course.get("courseMaxCount") is not None else (course.get("courseMaxNum") if course.get("courseMaxNum") is not None else course.get("maxCount"))
    if cur is not None and max_c is not None:
        try:
            if int(max_c) <= 0 or int(cur) >= int(max_c):
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
        # 记录各账号后台周期静默同步全量课池的时间戳：username -> float
        self.last_pool_sync_times: Dict[str, float] = {}
        # 记录各账号课池巡检日志心跳输出时间戳：username -> float
        self.last_inspect_log_times: Dict[str, float] = {}
        # 记录各账号课池守护总览日志是否已输出过（每个账号仅输出首条，彻底杜绝10分钟无意义重复刷屏）：username
        self.logged_pool_summary: Set[str] = set()

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
        self.logged_pool_summary.clear()
        self.add_log("info", "博雅自动化守护任务已停止", category="boya")

    def _run_loop(self) -> None:
        while self.running and not self._stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                logger.error(f"BoyaScheduler tick error: {e}", exc_info=True)

            # 智能夜间免打扰策略：23:30 ~ 07:00 校园服务休眠期，自动降频等待 180 秒，杜绝无意义的网络频繁唤醒
            now = datetime.now()
            is_deep_night = (now.hour == 23 and now.minute >= 30) or (0 <= now.hour < 7)
            wait_sec = 180 if is_deep_night else self.interval_seconds
            self._stop_event.wait(wait_sec)

    def _renew_session(self, acc: Any) -> bool:
        """尝试自动为账号静默续期博雅 Token（支持从 Cookies 换取或通过凭据全自动重新登录）"""
        try:
            acc.boya_client.sync_cookies_from(acc.client.client.cookies)
            token = acc.boya_client.acquire_token()
            if token:
                self.add_log("info", f"【{acc.name}】博雅会话已自动静默续期成功！", username=acc.username, user_name=acc.name, category="boya")
                return True
        except Exception as e:
            logger.debug(f"Auto renew boya token via cookies failed for {acc.username}: {e}")

        # 若从已有 cookies 换取失败，且该账号保存了登录密码，使用 credentials 全自动重新登录
        pwd = getattr(acc, "password", None)
        if pwd:
            try:
                token = acc.boya_client.login_with_credentials(acc.username, pwd)
                if token:
                    self.add_log("success", f"【{acc.name}】博雅凭据已自动重新登录认证成功，守护服务无缝恢复！", username=acc.username, user_name=acc.name, category="boya")
                    return True
            except Exception as login_err:
                logger.debug(f"Auto renew boya token via credentials failed for {acc.username}: {login_err}")

        return False

    def tick(self) -> None:
        now = datetime.now()
        is_deep_night = (now.hour == 23 and now.minute >= 30) or (0 <= now.hour < 7)
        pool_sync_interval = 1800 if is_deep_night else 60
        chosen_sync_interval = 1800 if is_deep_night else 300
        accounts = self.get_accounts()

        for acc in accounts:
            if not getattr(acc, "boya_auto_select", False) and not getattr(acc, "boya_auto_sign", False):
                continue
            username = acc.username
            user_name = acc.name
            boya_client: BoyaClient = getattr(acc, "boya_client", None)
            if not boya_client or not boya_client.is_authenticated():
                if not self._renew_session(acc):
                    continue

            # 首次运行或定期静默同步最新已选课程
            # 确保无论课程是本软件自动抢到的，还是学生在微信小程序/学校官网自行选中的，都能被守护引擎自动捕获并无缝纳入自动签到/签退！
            need_sync = False
            last_sync = self.last_sync_times.get(username)
            if last_sync is None:
                if getattr(acc, "boya_selected_courses", None) is None:
                    need_sync = True
                else:
                    self.last_sync_times[username] = time.time()
            elif time.time() - last_sync > chosen_sync_interval:
                need_sync = True

            if need_sync:
                try:
                    synced = acc.boya_client.query_chosen_courses()
                    if synced is not None:
                        acc.boya_selected_courses = synced
                    try:
                        stats = acc.boya_client.query_statistics()
                        if stats:
                            acc.boya_statistics = stats
                    except Exception:
                        pass
                    self.last_sync_times[username] = time.time()
                except BoyaSessionExpired:
                    if self._renew_session(acc):
                        try:
                            synced = acc.boya_client.query_chosen_courses()
                            if synced is not None:
                                acc.boya_selected_courses = synced
                            try:
                                stats = acc.boya_client.query_statistics()
                                if stats:
                                    acc.boya_statistics = stats
                            except Exception:
                                pass
                            self.last_sync_times[username] = time.time()
                        except Exception:
                            pass
                except Exception as sync_e:
                    logger.debug(f"Auto sync chosen courses error for {username}: {sync_e}")
                    self.last_sync_times[username] = time.time()

            # 1.1 若开启自动抢课，定期静默同步全量课池，实时捕捉新放号与退选名额
            if getattr(acc, "boya_auto_select", False):
                last_p_sync = self.last_pool_sync_times.get(username, 0)
                if getattr(acc, "boya_all_courses", None) is None or (time.time() - last_p_sync > pool_sync_interval):
                    try:
                        synced_pool = acc.boya_client.query_courses(max_pages=3)
                        if synced_pool is not None:
                            acc.boya_all_courses = synced_pool
                        self.last_pool_sync_times[username] = time.time()
                    except BoyaSessionExpired:
                        if self._renew_session(acc):
                            try:
                                synced_pool = acc.boya_client.query_courses(max_pages=3)
                                if synced_pool is not None:
                                    acc.boya_all_courses = synced_pool
                                self.last_pool_sync_times[username] = time.time()
                            except Exception:
                                pass
                    except Exception as pool_e:
                        logger.debug(f"Auto sync boya pool error for {username}: {pool_e}")
                        self.last_pool_sync_times[username] = time.time()

            # 1.2 自动抢选课流程
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
        
        # 安全铁律：全自动秒抢严格仅限支持线上自主打卡课程（严禁抢选现场刷卡考勤课程，从源头杜绝旷课违约）
        require_auto_sign = True

        # 建立当前已选课程的完备索引（提取所有可能的 ID 形式与课程名）
        selected_ids: Set[str] = set()
        selected_names: Set[str] = set()
        enrolled_courses = getattr(acc, "boya_selected_courses", []) or []
        for c in enrolled_courses:
            for k in ("id", "courseId", "course_id", "chosenCourseId"):
                v = c.get(k)
                if v is not None:
                    selected_ids.add(str(v))
            name = (c.get("courseName") or c.get("name") or "").strip()
            if name:
                selected_names.add(name)

        full_count = 0
        upcoming_count = 0
        chosen_count = 0
        past_count = 0
        conflict_count = 0
        offline_count = 0
        candidates = []

        for course in cached_courses:
            cid = course.get("id") or course.get("courseId")
            if not cid:
                continue
            cid_str = str(cid)
            cname = (course.get("courseName") or course.get("name") or cid_str).strip()

            # 防重检查 1：已在已选课程列表中
            if cid_str in selected_ids or cname in selected_names:
                chosen_count += 1
                continue

            # 防重检查 2：已在运行时已选历史中（已抢中或服务端提示已报名过）
            if (username, cid_str) in self.chosen_history or (username, cname) in self.chosen_history:
                chosen_count += 1
                continue

            # 检查熔断：连续失败达 3 次则本轮停止重试
            fail_key = (username, cid)
            fail_key_str = (username, cid_str)
            if self.fail_counters.get(fail_key, 0) >= 3 or self.fail_counters.get(fail_key_str, 0) >= 3:
                continue

            # 致命安全性防线：严格排除不支持线上自动打卡的现场刷卡/线下核验考勤课程
            # 既然软件无法为其线上自动打卡，抢下后学生如果未亲临现场刷卡，将直接导致旷课违约记过扣分！
            if require_auto_sign and not has_autonomous_sign(course):
                offline_count += 1
                continue

            # 统计各课程时间与容量状态
            s_start = course.get("courseSelectStartDate")
            s_end = course.get("courseSelectEndDate")
            parsed_s = parse_dt(s_start)
            parsed_e = parse_dt(s_end)
            if parsed_s and now < parsed_s:
                diff = (parsed_s - now).total_seconds()
                # 只有大于5秒的才算作未开始，<=5秒放行进行毫秒级倒计时抢选
                if diff > 5:
                    upcoming_count += 1
                    continue
            if parsed_e and now > parsed_e:
                past_count += 1
                continue

            cur = course.get("courseCurrentCount")
            max_c = course.get("courseMaxCount")
            if cur is not None and max_c is not None:
                try:
                    if int(max_c) <= 0 or int(cur) >= int(max_c):
                        full_count += 1
                        continue
                except Exception:
                    pass

            # 防选错检查：上课时间冲突检测（与学生本学期已选的任一门博雅课程上课时间重叠则坚决不选）
            conflict_course = None
            for enrolled in enrolled_courses:
                if courses_time_overlap(course, enrolled):
                    conflict_course = enrolled
                    break
            if conflict_course:
                conflict_count += 1
                continue

            # 检查候选条件（校区、分类、选课时间窗口、容量、已过上课时间排除、线上自主打卡校验）
            if is_auto_select_candidate(course, now, campus=campus, require_auto_sign=require_auto_sign):
                candidates.append(course)

        # 智能优先级排序：计算当前学期达标缺口，缺口越大的板块优先排序，已达标板块沉底
        sem_start, sem_end, _ = get_current_semester_range(now)
        demands = get_user_category_demands(enrolled_courses, sem_start, sem_end)
        candidates.sort(key=lambda c: calculate_candidate_priority(c, demands), reverse=True)

        # 仅在初次开启或初次课池同步时向个人日志输出一条守护态势总览，后续每 10 分钟在后台静默巡检，彻底杜绝刷屏
        if username not in self.logged_pool_summary:
            self.logged_pool_summary.add(username)
            self.last_inspect_log_times[username] = time.time()
            guard_note = f"，{offline_count}门非线上打卡安全排除" if offline_count > 0 or require_auto_sign else ""
            self.add_log(
                "info",
                f"【{user_name}】博雅抢课守护中：全校课池共 {len(cached_courses)} 门（{full_count}门满额{guard_note}，{upcoming_count}门待开放，{chosen_count}门已选，{conflict_count}门时冲跳过），保持毫秒级巡检捡漏与定点抢选...",
                username=username,
                user_name=user_name,
                category="boya",
            )

        for course in candidates:
            cid = course.get("id") or course.get("courseId")
            cid_str = str(cid)
            cname = (course.get("courseName") or course.get("name") or cid_str).strip()
            fail_key = (username, cid)
            fail_key_str = (username, cid_str)

            # 选课开始时间临界点高精度等待（若在 0 < diff <= 5 秒内，高精度倒计时对齐开抢时刻）
            s_start = course.get("courseSelectStartDate")
            parsed_s = parse_dt(s_start)
            if parsed_s and now < parsed_s:
                diff = (parsed_s - now).total_seconds()
                if 0 < diff <= 5:
                    time.sleep(diff)

            # 防封号与频控保护：请求抖动随机延时 0.5s ~ 1.2s，模拟真人操作
            time.sleep(random.uniform(0.5, 1.2))

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
                has_sign = has_autonomous_sign(course)
                sign_hint = "支持线上自主打卡，开课时将自动微扰打卡" if has_sign else "⚠️ 严正提醒：该课程需主办方现场刷卡/线下核验考勤，请务必亲临现场刷卡！"
                self.add_log(
                    "success",
                    f"🎉 成功抢中博雅课程 [{cname}]！{sign_hint}",
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

            sign_info_obj = None
            if course.get("signInfo"):
                try:
                    s_raw = course["signInfo"]
                    sign_info_obj = json.loads(s_raw) if isinstance(s_raw, str) else s_raw
                except Exception:
                    pass

            # 1. 签到检查
            sign_key = f"{username}_sign_{cid_str}_{today_str}"
            already_signed = bool(
                course.get("signStatus") == 1
                or course.get("courseSignStatus") == 1
                or course.get("signInStatus") == 1
                or (sign_info_obj and isinstance(sign_info_obj, dict) and sign_info_obj.get("signIn"))
            )
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
                    # 请求抖动与防频控保护
                    time.sleep(random.uniform(0.5, 1.0))
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
                        # 步骤完成铁律：自动签到成功后立即同步最新已选列表与学分统计
                        try:
                            acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
                            acc.boya_statistics = acc.boya_client.query_statistics()
                            acc.boya_last_refresh_time = datetime.now().strftime("%H:%M:%S")
                        except Exception as ref_err:
                            logger.debug(f"Post-signin Boya refresh error for {username}: {ref_err}")
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
            already_signed_out = bool(
                course.get("signOutStatus") == 1
                or course.get("courseSignOutStatus") == 1
                or (sign_info_obj and isinstance(sign_info_obj, dict) and sign_info_obj.get("signOut"))
            )
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
                    # 请求抖动与防频控保护
                    time.sleep(random.uniform(0.5, 1.0))
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
                        # 步骤完成铁律：自动签退成功后立即同步最新已选列表与学分统计
                        try:
                            acc.boya_selected_courses = acc.boya_client.query_chosen_courses()
                            acc.boya_statistics = acc.boya_client.query_statistics()
                            acc.boya_last_refresh_time = datetime.now().strftime("%H:%M:%S")
                        except Exception as ref_err:
                            logger.debug(f"Post-signout Boya refresh error for {username}: {ref_err}")
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