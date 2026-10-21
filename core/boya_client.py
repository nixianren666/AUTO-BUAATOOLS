"""
北航博雅系统 (BYKC) API 客户端
支持自动获取博雅 Token、全生命周期课程查询、选课/退课、定位打卡与学分统计
"""

import json
import copy
import logging
import re
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from core.cas import CasParser
from core.cas_transport import resolve_auth_redirect, follow_auth_response_sync, CasFlowError, CasCaptchaRequired, REDIRECTS
from core.webvpn import to_webvpn_url
from core.boya_crypto import BykcCrypto
from core.domain import trusted_url, semester, semester_bounds, course_id, now as china_now
from core import operations

logger = logging.getLogger(__name__)

BYKC_BASE = "https://bykc.buaa.edu.cn/sscv"
BYKC_REFERER = "https://bykc.buaa.edu.cn/system/course-select"
BYKC_ORIGIN = "https://bykc.buaa.edu.cn"
BYKC_CAS = "https://bykc.buaa.edu.cn/sscv/cas/login"
BYKC_CAS_EMPTY_TOKEN = "https://bykc.buaa.edu.cn/cas-login?token="
UC_ACTIVATE = "https://uc.buaa.edu.cn/api/login?target=https%3A%2F%2Fuc.buaa.edu.cn%2F%23%2Fuser%2Flogin"
SSO_LOGIN = "https://sso.buaa.edu.cn/login"


class BoyaApiError(Exception):
    def __init__(self, code: Any, message: str) -> None:
        super().__init__(f"[BoyaError {code}] {message}")
        self.code = code
        self.message = message


class BoyaSessionExpired(Exception):
    pass


class BoyaClient:
    def __init__(self, mode: str = "direct", token: Optional[str] = None) -> None:
        self.mode = mode.lower()  # "direct" 或 "webvpn"
        self.token = token
        self.http_client = httpx.Client(timeout=25, follow_redirects=False, verify=True, trust_env=False)
        self.request_guard = lambda: True
        self.semester_info = None
        self.calendar_range = None
        self.operation_user = None
        self.operation_scope = None
        self._request_lock = threading.RLock()

    def close(self):
        with self._request_lock:
            self.token = None
            self.http_client.close()

    def upstream(self, url: str) -> str:
        if self.mode == "webvpn":
            return to_webvpn_url(url)
        return url

    def is_authenticated(self) -> bool:
        return bool(self.token)

    def sync_cookies_from(self, cookies: httpx.Cookies) -> None:
        """Keep secure/path/expiry flags when sharing this student's SSO jar."""
        with self._request_lock:
            for cookie in cookies.jar:
                self.http_client.cookies.jar.set_cookie(copy.copy(cookie))

    def _activate_uc(self):
        response = self.http_client.get(self.upstream(UC_ACTIVATE), timeout=10)
        return follow_auth_response_sync(response, self.http_client, self.mode)

    def _verify_uc_identity(self, username):
        status = self.http_client.get(self.upstream('https://uc.buaa.edu.cn/api/uc/status'))
        status.raise_for_status()
        payload = status.json()
        identity = payload.get('data') if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or str(payload.get('code')) != '0' or not isinstance(identity, dict) or not (identity.get('schoolid') or identity.get('username')):
            raise BoyaApiError('cas_error', '官方未确认登录身份')
        if str(username).isascii() and str(username).isdigit() and str(identity.get('schoolid') or identity.get('username')) != str(username):
            raise BoyaApiError('cas_error', '官方登录身份与请求账号不一致')

    def login_with_credentials(self, username: str, password: str, captcha: str = "") -> str:
        with self._request_lock:
            self.token = None
            try:
                sso_url = self.upstream(SSO_LOGIN)
                response = self.http_client.get(sso_url)
                if response.status_code in REDIRECTS:
                    follow_auth_response_sync(response, self.http_client, self.mode)
                else:
                    if response.status_code != 200:
                        raise BoyaApiError('auth_http', '统一认证登录页面暂不可用')
                    html = response.text
                    if CasParser.detect_captcha(html) and not captcha:
                        raise BoyaApiError('captcha_required', '统一认证需要验证码，请在界面重新登录')
                    if CasParser.is_ignorable_password_expiry(html):
                        follow_auth_response_sync(response, self.http_client, self.mode)
                    else:
                        error = CasParser.find_login_error(html)
                        if error:
                            raise BoyaApiError('cas_error', error)
                        if not CasParser.extract_execution(html):
                            raise BoyaApiError('cas_error', '统一认证登录页面格式异常')
                        params = CasParser.build_login_params(html, username, password, captcha=captcha)
                        submitted = self.http_client.post(sso_url, data=params)
                        follow_auth_response_sync(submitted, self.http_client, self.mode)
                self._activate_uc()
                self._verify_uc_identity(username)
                return self._set_acquired_token()
            except CasCaptchaRequired as error:
                raise BoyaApiError('captcha_required', str(error)) from None
            except CasFlowError as error:
                raise BoyaApiError('cas_error', str(error)) from None

    def _set_acquired_token(self):
        token = self._follow_for_token()
        if not token:
            raise BoyaApiError('token_acquire_failed', '未能从博雅系统认证跳转中取得授权，请重新登录')
        self.token = token
        logger.info('博雅授权已建立')
        return token

    def acquire_token(self) -> str:
        """Complete UC/CAS ticket exchange before acquiring this student's token."""
        with self._request_lock:
            self.token = None
            try:
                self._activate_uc()
                if self.operation_user:
                    self._verify_uc_identity(self.operation_user)
                return self._set_acquired_token()
            except CasCaptchaRequired as error:
                raise BoyaApiError('captcha_required', str(error)) from None
            except CasFlowError as error:
                raise BoyaApiError('cas_error', str(error)) from None

    def _follow_for_token(self) -> Optional[str]:
        for entry in [self.upstream(BYKC_CAS), self.upstream(BYKC_CAS_EMPTY_TOKEN)]:
            curr_url = entry
            for _ in range(12):
                resp = self.http_client.get(curr_url, follow_redirects=False, timeout=15)
                if resp.status_code not in (*REDIRECTS, 200):
                    break
                # 1. 检查当前 URL 中的 token
                t = self._extract_token(trusted_url(str(resp.url)))
                if t:
                    return t
                # 2. 检查 Location 头
                loc = resp.headers.get("location")
                if loc:
                    target = resolve_auth_redirect(str(resp.url), loc, self.mode)
                    t = self._extract_token(target)
                    if t:
                        return t
                    curr_url = target
                elif 300 <= resp.status_code <= 399:
                    break
                else:
                    if resp.status_code == 200:
                        if CasParser.detect_captcha(resp.text):
                            raise BoyaApiError("captcha_required", "统一认证需要验证码，请在界面重新登录")
                        if CasParser.is_ignorable_password_expiry(resp.text):
                            final = follow_auth_response_sync(resp, self.http_client, self.mode)
                            token = self._extract_token(str(final.url))
                            if token:
                                return token
                        if CasParser.extract_execution(resp.text) or CasParser.find_login_error(resp.text):
                            raise BoyaApiError("cas_error", "统一认证会话已失效，请在界面重新登录")
                        break
                    break
        return None

    def _extract_token(self, url: str) -> Optional[str]:
        if not url:
            return None
        from core.webvpn import from_webvpn_url
        url = from_webvpn_url(trusted_url(url)) if self.mode == "webvpn" else trusted_url(url)
        parsed = urlparse(url)
        if parsed.hostname != "bykc.buaa.edu.cn":
            return None
        values = parse_qs(parsed.query).get('token', [])
        if '?' in parsed.fragment:
            values += parse_qs(parsed.fragment.split('?',1)[1]).get('token', [])
        values = list(set(values))
        return values[0] if len(values) == 1 and values[0] and not any(c.isspace() for c in values[0]) else None

    def call(self, api_name: str, payload: Any = None) -> Dict[str, Any]:
        with self._request_lock:
            return self._call_locked(api_name, payload)

    def _call_locked(self, api_name: str, payload: Any = None) -> Dict[str, Any]:
        """发起加密的 BYKC API 请求并自动解密返回"""
        if not self.token:
            raise BoyaSessionExpired("未获取到博雅 token，请先执行博雅登录")

        endpoint = f"{BYKC_BASE}/{api_name}"
        endpoint_url = self.upstream(endpoint)

        crypto = BykcCrypto()
        req_enc = crypto.encrypt_request(payload or {})

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Referer": self.upstream(BYKC_REFERER),
            "Origin": self.upstream(BYKC_ORIGIN),
            "Authtoken": self.token,
            "auth_token": self.token,
            **req_enc.headers,
        }

        writing = api_name in ("choseCourse", "delChosenCourse", "signCourseByUser")
        key = None
        if writing:
            if not self.operation_user or not self.request_guard():
                raise BoyaApiError("cancelled", "身份未绑定、账号已暂停或操作窗口已结束")
            cid = (payload or {}).get("courseId", (payload or {}).get("id"))
            action = api_name + ":" + str((payload or {}).get("signType", ""))
            key = operations.ledger.key(self.operation_user, action, cid, self.operation_scope or china_now().date())
            if api_name == "choseCourse":
                quota = operations.ledger.key(self.operation_user, "selection-budget", cid, china_now().date())
                row = operations.ledger.read(quota)
                if row and time.time()-row[2] < 60:
                    raise operations.OperationBusy("同一课程的选课请求至少间隔60秒")
            group = operations.ledger.key(self.operation_user, action, cid, "group")
            if not operations.ledger.claim(key, group=group, block_group_success=api_name == "choseCourse"):
                return {"status": "0", "already_accepted": True}
            if api_name == "choseCourse":
                try:
                    operations.ledger.claim(quota, limit=9)
                    operations.ledger.finish(quota, "failed")
                except BaseException:
                    operations.ledger.finish(key, "failed")
                    raise
        try:
            resp = self.http_client.post(endpoint_url, content=req_enc.body, headers=headers, timeout=25)
            if resp.status_code in (401, 403):
                self.token = None
                raise BoyaSessionExpired("博雅会话已失效")
            if "login" in resp.text.lower() and "<html" in resp.text.lower():
                self.token = None
                raise BoyaSessionExpired("博雅凭证过期")
            resp.raise_for_status()
            try:
                decoded = crypto.decrypt_response(resp.content)
            except Exception as exc:
                raise ValueError("博雅响应解密失败，写入结果待复核") from exc
            if not isinstance(decoded, dict) or "status" not in decoded or isinstance(decoded["status"], bool):
                raise ValueError("博雅响应缺少有效官方业务状态")
            status = decoded["status"]
            message = str(decoded.get("errmsg") or decoded.get("msg") or "")
            if str(status) == "98005399" or "会话已失效" in message or "重新登录" in message:
                self.token = None
                raise BoyaSessionExpired("博雅会话已失效")
            if status not in ("0", 0, "200", 200):
                raise BoyaApiError(status, message)
            if key:
                operations.ledger.finish(key, "success")
            return decoded
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            if key:
                operations.ledger.failed_before_send(key)
                if api_name == "choseCourse":
                    operations.ledger.failed_before_send(quota)
            raise
        except (BoyaSessionExpired, BoyaApiError):
            if key:
                operations.ledger.finish(key, "failed")
            raise
        except BaseException:
            if key:
                operations.ledger.finish(key, "uncertain")
            raise

    def get_all_config(self) -> Dict[str, Any]:
        return self.call("getAllConfig", {})

    def query_course_page(self, page_number: int = 1, page_size: int = 100) -> Dict[str, Any]:
        return self.call("queryStudentSemesterCourseByPage", {"pageNumber": page_number, "pageSize": page_size})

    def query_courses(self, max_pages=None):
        courses, ids_seen, previous_pages = [], set(), set()
        expected_total, expected_pages = None, None
        started = time.monotonic()
        for page in range(1, 1001):
            if time.monotonic()-started > 120:
                raise BoyaApiError("pagination_timeout", "本轮全量同步超时，暂停选课并等待下一轮")
            if max_pages is not None and page > max_pages:
                raise BoyaApiError("pagination_incomplete", "课池未完整读取，暂停自动选课")
            data = self.query_course_page(page, 100).get("data")
            if not isinstance(data, dict) or not isinstance(data.get("content"), list):
                raise BoyaApiError("protocol_error", "缺少课池分页数据")
            content = data["content"]
            ids = tuple(course_id(c) if isinstance(c, dict) else None for c in content)
            if content and (None in ids or len(set(ids)) != len(ids) or set(ids) & ids_seen or ids in previous_pages):
                raise BoyaApiError("protocol_error", "课程ID无效或分页重复/变化，稍后重新全量同步")
            previous_pages.add(ids)
            ids_seen.update(ids)
            courses.extend(content)
            for field in ("totalPages", "totalElements"):
                value = data.get(field)
                if value is not None and (isinstance(value, bool) or not str(value).isdigit()):
                    raise BoyaApiError("protocol_error", "无效的分页总数")
            pages = int(data["totalPages"]) if data.get("totalPages") is not None else None
            total = int(data["totalElements"]) if data.get("totalElements") is not None else None
            if page == 1:
                expected_total, expected_pages = total, pages
            elif (expected_total is not None and total != expected_total) or (expected_pages is not None and pages != expected_pages):
                raise BoyaApiError("pagination_changed", "分页数量发生变化，稍后重新全量同步")
            ended = data.get("last") is True or not content or (pages is not None and page >= pages) or (total is not None and len(courses) >= total)
            if ended:
                if (expected_total is not None and len(courses) != expected_total) or (expected_pages is not None and page < expected_pages):
                    raise BoyaApiError("pagination_incomplete", "课池分页提前结束，未取得完整课程")
                return courses
        raise BoyaApiError("pagination_incomplete", "分页超过安全上限，课池不可用于自动选课")

    def query_course_detail(self, cid):
        data = self.call("queryCourseById", {"id": int(cid)}).get("data")
        if not isinstance(data, dict) or course_id(data) != int(cid):
            raise BoyaApiError("protocol_error", "课程详情ID不匹配")
        return data

    def current_semester(self):
        config = self.get_all_config()
        self.semester_info = semester(config)
        data = config.get("data", config)
        periods = [semester_bounds(row) for row in data.get("semester", []) if isinstance(row, dict)]
        periods = [(start,end) for start,end in periods if start and end]
        self.calendar_range = (min(start for start,end in periods).isoformat(sep=" "), max(end for start,end in periods).isoformat(sep=" ")) if periods else None
        return self.semester_info

    def query_chosen_courses(self, start_date=None, end_date=None):
        if start_date is None or end_date is None:
            info = self.current_semester()
            # Keep historical selected-course views without a guessed fixed year range.
            start_date, end_date = self.calendar_range or (info["semesterStartDate"], info["semesterEndDate"])
        data = self.call("queryChosenCourse", {"startDate": start_date, "endDate": end_date}).get("data")
        if not isinstance(data, dict) or not isinstance(data.get("courseList"), list):
            raise BoyaApiError("protocol_error", "缺少官方已选课程数据")
        result = []
        for item in data["courseList"]:
            info = item.get("courseInfo") or {}
            cid = course_id({"courseInfo": info, "courseId": item.get("courseId")})
            if cid is None:
                raise BoyaApiError("protocol_error", "已选课程缺少本体ID")
            merged = {**info, **item, "id": cid, "courseId": cid, "chosenCourseId": item.get("id"), "selected": True}
            result.append(merged)
        return result

    def query_statistics(self) -> Dict[str, Any]:
        """获取学生博雅学分完成情况与分类考核统计"""
        data = self.call("queryStatisticByUserId", {})
        result = data.get("data")
        if not isinstance(result, dict):
            raise BoyaApiError("protocol_error", "缺少官方统计数据")
        result = dict(result)
        result["semesterInfo"] = self.current_semester()
        return result


    def select_course(self, course_id: int) -> Dict[str, Any]:
        """执行真实抢课/选课"""
        return self.call("choseCourse", {"courseId": course_id})

    def drop_course(self, chosen_id: int) -> Dict[str, Any]:
        """执行真实退课"""
        return self.call("delChosenCourse", {"id": chosen_id})

    def sign_course(self, course_id: int, lat: float, lng: float, sign_type: int = 1) -> Dict[str, Any]:
        """
        执行定位打卡
        sign_type: 1 为签到, 2 为签退
        """
        return self.call(
            "signCourseByUser",
            {"courseId": course_id, "signLat": lat, "signLng": lng, "signType": sign_type},
        )


def extract_real_name_from_stats(stats: Dict[str, Any]) -> Optional[str]:
    """从 queryStatisticByUserId 返回的数据树或顶层字段中提取学生真实姓名"""
    if not isinstance(stats, dict):
        return None

    # 1. 顶层 userInfo 提取
    top_user = stats.get("userInfo")
    if isinstance(top_user, dict):
        rn = top_user.get("realName") or top_user.get("name")
        if rn and str(rn).strip():
            return str(rn).strip()
    if stats.get("realName"):
        return str(stats["realName"]).strip()

    # 2. 多层分类统计树提取
    statistical = stats.get("statistical")
    if not isinstance(statistical, dict):
        return None
    boya_courses = statistical.get("60|博雅课程")
    if not isinstance(boya_courses, dict):
        return None
    for cat_data in boya_courses.values():
        if isinstance(cat_data, dict):
            u_list = cat_data.get("courseUserList") or []
            for u_item in u_list:
                if isinstance(u_item, dict):
                    user_info = u_item.get("userInfo") or {}
                    real_name = user_info.get("realName") or user_info.get("name")
                    if real_name and str(real_name).strip():
                        return str(real_name).strip()
    return None
