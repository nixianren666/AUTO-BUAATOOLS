"""One preflight and submission contract shared by manual APIs and automation."""
import math
import threading
import time

from core import operations
from core.boya_client import BoyaApiError, BoyaSessionExpired
from core.domain import (now, course_id, course_times, sign_config, sign_points,
    attendance_allowed, within_semester, semester_bounds, in_window)

_creation_lock = threading.Lock()

def account_lock(account):
    with _creation_lock:
        if not hasattr(account, "boya_lock"):
            account.boya_lock = threading.RLock()
        return account.boya_lock

def merge_selected(course, pool):
    cid = course_id(course)
    result = dict(course)
    match = next((p for p in pool if cid is not None and course_id(p) == cid), None)
    if match:
        for key in ("courseSignConfig", "courseStartDate", "courseStartTime", "courseEndDate", "courseEndTime", "coursePosition", "courseKind", "courseNewKind2"):
            if result.get(key) in (None, "", {}) or (key == "courseSignConfig" and not sign_points(sign_config(result.get(key)))):
                result[key] = match.get(key)
    return result

def reconcile_official(account, selected):
    """Resolve ambiguous writes only from an affirmative official attendance/selection."""
    for course in selected:
        cid = course_id(course)
        if cid is None:
            continue
        operations.ledger.clear_reservation(account.username, cid)
        getattr(account, "boya_pending_courses", {}).pop(cid, None)
        def group(api, sign_type=""):
            return operations.ledger.key(account.username, api+":"+str(sign_type), cid, "group")
        operations.ledger.settle_group(group("choseCourse"))
        state = str(course.get("checkin"))
        if state in ("1","5","6","9","10","11"):
            operations.ledger.settle_group(group("signCourseByUser",1))
        if state in ("1","7","8","9","10","11"):
            operations.ledger.settle_group(group("signCourseByUser",2))

def _normal_conflicts(account, course, ordinary):
    from core.domain import regular_start
    start, end = course_times(course)
    if not start or not end or end <= start or (end.date()-start.date()).days > 14:
        raise BoyaApiError("unknown_schedule", "课程时间不完整或跨度过长，无法安全核对普通课冲突")
    if ordinary is None:
        raise BoyaApiError("unknown_schedule", "普通课表尚不能核实，暂停本门自动抢选")
    rows = ordinary(account, start.date(), end.date())
    if not isinstance(rows, list):
        raise BoyaApiError("unknown_schedule", "普通课表未完整同步")
    for row in rows:
        a = regular_start(row.get("classBeginTime"), start)
        b = regular_start(row.get("classEndTime"), start)
        if not a or not b or b <= a:
            raise BoyaApiError("unknown_schedule", "普通课程时间未知，不能断言无冲突")
        if max(a, start) < min(b, end):
            return True
    return False

def perform_boya_action(account, action, cid, sign_type=1, coordinates=None,
                        automatic=False, guard=None, renew=None, ordinary=None):
    """Return accepted/pending separately; never retry an ambiguous write here."""
    from core.boya_scheduler import (is_auto_select_candidate, capacity_available, capacity_values,
        get_course_category, get_user_category_demands, courses_time_overlap, random_point_in_radius)
    if isinstance(cid, bool) or not str(cid).isdigit() or int(cid) <= 0:
        raise BoyaApiError("invalid_id", "无效课程本体 ID")
    cid = int(cid)
    epoch = getattr(account, "auth_epoch", 0)
    if action not in ("select", "drop", "sign") or (action == "sign" and sign_type not in (1, 2)):
        raise BoyaApiError("invalid_action", "无效操作类型")
    def active():
        return not getattr(account, "removed", False) and not getattr(account, "maintenance", False) and getattr(account, "auth_epoch", 0) == epoch and (guard is None or guard())
    with account_lock(account):
        if not active():
            raise BoyaApiError("cancelled", "账号或任务已停止")
        client = account.boya_client
        if not client.is_authenticated() and (renew is None or not renew(account)):
            raise BoyaSessionExpired("请重新认证")
        try:
            selected = client.query_chosen_courses()
        except BoyaSessionExpired:
            if renew is None or not renew(account):
                raise
            selected = client.query_chosen_courses()
        account.boya_selected_courses = selected
        reconcile_official(account, selected)
        pool = account.boya_all_courses or []
        course = next((c for c in selected if course_id(c) == cid), None)
        def group(api, kind=""):
            return operations.ledger.key(account.username, api+":"+str(kind), cid, "group")
        if action == "select" and course is not None:
            operations.ledger.settle_group(group("choseCourse"))
            return {"status": "success", "submitted": False, "officially_confirmed": True}
        if action == "drop" and course is None:
            return {"status": "success", "submitted": False, "officially_confirmed": True}
        if action == "sign" and course is None:
            raise BoyaApiError("not_selected", "本账号未选此课程，拒绝考勤")
        if action == "drop" and course.get("checkin") is not None and str(course.get("checkin")) != "0":
            raise BoyaApiError("attendance_recorded", "已有官方考勤记录，不能在本程序退选")
        if action == "select":
            # Read a fresh complete pool; a stale capacity snapshot cannot authorize a write.
            pool = client.query_courses()
            account.boya_all_courses = pool
            course = next((c for c in pool if course_id(c) == cid), None)
            if course is None:
                raise BoyaApiError("not_found", "官方课池不存在此课程")
            if not capacity_available(course) or not in_window(course.get("courseSelectStartDate"), course.get("courseSelectEndDate"), now()):
                raise BoyaApiError("unavailable", "名额未知/已满或不在官方选课窗口")
            if automatic:
                info = client.semester_info or client.current_semester()
                if not within_semester(course, info) or not is_auto_select_candidate(course, now(), getattr(account, "campus", "北京")):
                    raise BoyaApiError("unsafe_auto", "不满足本学期线上自主考勤抢选契约")
                reservations = list(selected) + list(getattr(account, "boya_pending_courses", {}).values())
                start, end = semester_bounds(info)
                demands = get_user_category_demands(reservations, start, end, getattr(account, "boya_targets", None))
                category = get_course_category(course)
                if demands.get(category, {}).get("remaining", 0) <= 0:
                    raise BoyaApiError("target_filled", "本类别已完成或已有足够预约，停止额外抢选")
                if any(courses_time_overlap(course, existing) for existing in reservations):
                    raise BoyaApiError("conflict", "与已选博雅/在途预约的时间冲突")
                if _normal_conflicts(account, course, ordinary):
                    raise BoyaApiError("conflict", "与普通课堂时间冲突")
        elif action == "sign":
            if not sign_points(sign_config(course.get("courseSignConfig"))):
                pool = client.query_courses()
                account.boya_all_courses = pool
            course = merge_selected(course, pool)
            if not attendance_allowed(course, sign_type, now()):
                raise BoyaApiError("outside_window", "官方考勤已完成、配置不完整或不在签到/签退窗口")
            points = sign_points(sign_config(course.get("courseSignConfig")))
            if coordinates is None:
                point = points[-1]
                coordinates = random_point_in_radius(point["lat"], point["lng"], point["radius"])
            lat, lng = coordinates
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in coordinates) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise BoyaApiError("invalid_location", "无效考勤坐标")
            # Reject supplied locations outside every official point, using great-circle distance.
            def distance(point):
                a, b = math.radians(lat), math.radians(point["lat"])
                h = math.sin((a-b)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lng-point["lng"])/2)**2
                return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))
            if not any(distance(point) <= point["radius"] for point in points):
                raise BoyaApiError("invalid_location", "坐标不在官方自主签到范围")
        # The network client evaluates this again immediately before its only POST.
        def final_guard():
            if not active():
                return False
            if action == "sign":
                return attendance_allowed(course, sign_type, now())
            if action == "select":
                return in_window(course.get("courseSelectStartDate"), course.get("courseSelectEndDate"), now()) and (not automatic or is_auto_select_candidate(course, now(), getattr(account, "campus", "北京")))
            return True
        previous_guard = client.request_guard
        previous_scope = client.operation_scope
        client.request_guard = final_guard
        client.operation_user = account.username
        # Attendance is scoped to the course's official window, not a process or guessed day.
        cfg = sign_config(course.get("courseSignConfig"))
        if action == "sign":
            client.operation_scope = cfg.get("signStartDate" if sign_type == 1 else "signOutStartDate")
        elif action == "select":
            # A newly released seat changes this epoch; temporary full-state failures
            # do not permanently disable a later genuine availability change.
            current, maximum = capacity_values(course)
            client.operation_scope = str(course.get("courseSelectStartDate")) + ":" + str(current) + ":" + str(maximum)
        else:
            client.operation_scope = str(course.get("chosenCourseId") or course.get("courseSelectStartDate"))
        try:
            if not final_guard():
                raise BoyaApiError("cancelled", "提交前复核失败，未发送")
            if action == "select":
                response = client.select_course(cid)
                pending = getattr(account, "boya_pending_courses", {})
                pending[cid] = course
                account.boya_pending_courses = pending
                operations.ledger.reserve(account.username, course)
            elif action == "drop":
                response = client.drop_course(cid)  # Never substitute a registration ID.
            else:
                response = client.sign_course(cid, coordinates[0], coordinates[1], sign_type=sign_type)
        except BoyaSessionExpired:
            # Refresh authorization separately; never replay the just-failed write here.
            if active() and renew is not None:
                renew(account)
            raise
        except BoyaApiError as exc:
            if action == "select":
                key = operations.ledger.key(account.username, "choseCourse:", cid, client.operation_scope)
                state = operations.ledger.read(key)
                if state and state[0] in ("pending", "uncertain"):
                    operations.ledger.reserve(account.username, course)
                    account.boya_pending_courses = {**getattr(account, "boya_pending_courses", {}),cid:course}
            if action != "select" or not any(word in str(exc.message) for word in ("已报名", "重复报名", "已经选择", "已选课")):
                raise
            # The explicit business rejection forbids replay, but is not a substitute
            # for the official chosen-course record or final assessment.
            key = operations.ledger.key(account.username, "choseCourse:", cid, client.operation_scope)
            operations.ledger.confirmed(key)
            pending = getattr(account, "boya_pending_courses", {})
            pending[cid] = course
            account.boya_pending_courses = pending
            operations.ledger.reserve(account.username, course)
            response = {"status": "pending", "already_accepted": True, "message": "学校提示已报名，等待官方已选记录同步"}
        finally:
            try:
                if action == "select":
                    state = operations.ledger.read(operations.ledger.key(account.username, "choseCourse:", cid, client.operation_scope))
                    if state and state[0] in ("pending", "uncertain"):
                        operations.ledger.reserve(account.username, course)
                        account.boya_pending_courses = {**getattr(account, "boya_pending_courses", {}),cid:course}
            finally:
                client.request_guard = previous_guard
                client.operation_scope = previous_scope
        result = {"status": "success", "result": response, "submitted": not response.get("already_accepted", False), "pending_verification": response.get("status") == "pending"}
        try:
            refreshed = client.query_chosen_courses()
            account.boya_selected_courses = refreshed
            selected_ids = {course_id(c) for c in refreshed}
            if action == "select" and cid not in selected_ids:
                result["pending_verification"] = True
            elif action == "drop" and cid in selected_ids:
                result["pending_verification"] = True
            elif action == "sign":
                official_course = next((c for c in refreshed if course_id(c) == cid), {})
                state = str(official_course.get("checkin"))
                recorded = state in ("1", "5", "6", "9", "10", "11") if sign_type == 1 else state in ("1", "7", "8", "9", "10", "11")
                result["pending_verification"] = not recorded
                if recorded:
                    operations.ledger.settle_group(group("signCourseByUser", sign_type))
            else:
                getattr(account, "boya_pending_courses", {}).pop(cid, None)
            if action == "select" and cid in selected_ids:
                operations.ledger.clear_reservation(account.username, cid)
                getattr(account, "boya_pending_courses", {}).pop(cid, None)
                operations.ledger.settle_group(group("choseCourse"))
                operations.ledger.forget_group_confirmed(group("delChosenCourse"))
            elif action == "drop" and cid not in selected_ids:
                operations.ledger.settle_group(group("delChosenCourse"))
                operations.ledger.forget_group_confirmed(group("choseCourse"))
            account.boya_last_refresh_time = now().isoformat(timespec="seconds")
        except Exception as exc:
            result["pending_verification"] = True
            account.boya_health = {"stale": True, "pending_verification": True, "error": type(exc).__name__}
        return result
