"""Conservative school data contracts shared by clients, schedulers and UI APIs."""
import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CHINA = ZoneInfo("Asia/Shanghai")
REQUIREMENTS = {"德育": 2, "劳育": 2, "美育": 1, "安全健康": 1}

def now():
    return datetime.now(CHINA).replace(tzinfo=None)

def parse_dt(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        text = value.strip().replace("/", "-").replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo:
            dt = dt.astimezone(CHINA).replace(tzinfo=None)
        return dt
    except ValueError:
        return None

def course_times(course):
    result = []
    for prefix in ("Start", "End"):
        date = course.get("course" + prefix + "Date")
        clock = course.get("course" + prefix + "Time")
        result.append(parse_dt(str(date) + " " + str(clock)) if clock and isinstance(date, str) and len(date) == 10 else parse_dt(date))
    return tuple(result)

def in_window(start, end, current):
    a, b = parse_dt(start), parse_dt(end)
    return bool(a and b and a <= current <= b and a <= b)

def course_id(course):
    info = course.get("courseInfo") or {}
    value = course.get("courseId") or info.get("id") or course.get("id")
    try:
        if isinstance(value, bool) or not str(value).isdigit():
            return None
        cid = int(value)
        return cid if cid > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None

def sign_config(value):
    if isinstance(value, str):
        try:
            value = json.loads(value.replace('\\"', '"'))
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}

def sign_points(config):
    points = config.get("signPointList")
    result = []
    if not isinstance(points, list):
        return result
    for point in points:
        if not isinstance(point, dict):
            continue
        try:
            raw = [point.get("lat", point.get("signLat")), point.get("lng", point.get("signLng")), point.get("radius", point.get("signRadius"))]
            if any(isinstance(value, bool) for value in raw):
                continue
            lat, lng, radius = map(float, raw)
            if all(math.isfinite(v) for v in (lat, lng, radius)) and -90 <= lat <= 90 and -180 <= lng <= 180 and 0 < radius <= 10000:
                result.append({"lat": lat, "lng": lng, "radius": radius})
        except (ValueError, TypeError, OverflowError):
            continue
    return result

def autonomous(course, require_windows=False):
    cfg = sign_config(course.get("courseSignConfig", course.get("signConfig")))
    if not sign_points(cfg):
        return False
    if require_windows:
        for prefix in ("sign", "signOut"):
            start, end = parse_dt(cfg.get(prefix + "StartDate")), parse_dt(cfg.get(prefix + "EndDate"))
            if not start or not end or start > end:
                return False
    return True

def attendance_allowed(course, sign_type, current):
    cfg = sign_config(course.get("courseSignConfig", course.get("signConfig")))
    try:
        if isinstance(course.get("checkin"), bool) or isinstance(course.get("pass"), bool):
            return False
        checkin = int(course.get("checkin") or 0)
        passed = int(course.get("pass")) if course.get("pass") is not None else None
    except (ValueError, TypeError):
        return False
    if passed == 1 or not sign_points(cfg):
        return False
    if sign_type == 1:
        return checkin == 0 and in_window(cfg.get("signStartDate"), cfg.get("signEndDate"), current)
    if sign_type == 2:
        return checkin in (0, 5, 6) and in_window(cfg.get("signOutStartDate"), cfg.get("signOutEndDate"), current)
    return False

def drop_allowed(course, current):
    start, end = course_times(course)
    checkin = course.get("checkin")
    passed = course.get("pass")
    return bool(start and end and start <= end and current <= end and not isinstance(checkin, bool) and checkin in (None,0,"0") and not isinstance(passed, bool) and passed in (None,0,"0"))

def semester(config, current=None):
    current = current or now()
    data = config.get("data", config) if isinstance(config, dict) else {}
    rows = data.get("semester", []) if isinstance(data, dict) else []
    for row in rows:
        if isinstance(row, dict) and semester_bounds(row)[0] is not None and semester_bounds(row)[0] <= current <= semester_bounds(row)[1]:
            return row
    raise ValueError("无法确定官方当前学期，请刷新校历；自动选课已暂停")

def within_semester(course, info):
    start, end = course_times(course)
    a, b = semester_bounds(info)
    return bool(a and b and start and end and a <= start <= end <= b)

def semester_bounds(info):
    a, b = parse_dt(info.get("semesterStartDate")), parse_dt(info.get("semesterEndDate"))
    if b and len(str(info.get("semesterEndDate"))) == 10:
        b += timedelta(days=1, microseconds=-1)
    return (a, b) if a and b and a <= b else (None, None)

def regular_start(value, current=None):
    current = current or now()
    parsed = parse_dt(value)
    if parsed:
        return parsed
    try:
        return datetime.combine(current.date(), datetime.strptime(str(value), "%H:%M").time())
    except ValueError:
        try:
            return datetime.combine(current.date(), datetime.strptime(str(value), "%H:%M:%S").time())
        except ValueError:
            return None

def regular_allowed(course, current):
    start = regular_start(course.get("classBeginTime"), current)
    return bool(start and start.date() == current.date() and start - timedelta(minutes=10) <= current <= start and str(course.get("signStatus", "")) == "0")

def trusted_url(url):
    from urllib.parse import urlsplit
    p = urlsplit(url)
    allowed = {"sso.buaa.edu.cn", "uc.buaa.edu.cn", "iclass.buaa.edu.cn", "bykc.buaa.edu.cn", "d.buaa.edu.cn"}
    ports = (None, 443, 8346, 8347) if p.hostname == "iclass.buaa.edu.cn" else (None, 443)
    if p.scheme != "https" or p.hostname not in allowed or p.username or p.password or p.port not in ports:
        raise ValueError("拒绝非可信学校认证跳转")
    if p.hostname == "d.buaa.edu.cn" and p.path.startswith(("/https/", "/https-", "/http/", "/http-")):
        from core.webvpn import from_webvpn_url
        target = from_webvpn_url(url)
        if target == url:
            raise ValueError("无法验证 WebVPN 内层认证目标")
        trusted_url(target)
    return url
