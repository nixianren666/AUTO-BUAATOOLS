"""
北航博雅系统 (BYKC) API 客户端
支持自动获取博雅 Token、全生命周期课程查询、选课/退课、定位打卡与学分统计
"""

import json
import logging
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from core.cas import CasParser
from core.webvpn import to_webvpn_url
from core.boya_crypto import BykcCrypto

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
        self.http_client = httpx.Client(timeout=25, follow_redirects=False, verify=False)

    def upstream(self, url: str) -> str:
        if self.mode == "webvpn":
            return to_webvpn_url(url)
        return url

    def is_authenticated(self) -> bool:
        return bool(self.token)

    def sync_cookies_from(self, cookies: httpx.Cookies) -> None:
        """从已登录的 IclassClient 同步 SSO/WebVPN 会话 Cookies"""
        for c in cookies.jar:
            self.http_client.cookies.set(
                c.name,
                c.value,
                domain=c.domain,
                path=c.path,
            )

    def login_with_credentials(self, username: str, password: str, captcha: str = "") -> str:
        """使用北航统一认证账号密码直接登录并换取博雅 Token"""
        sso_url = self.upstream(SSO_LOGIN)
        resp = self.http_client.get(sso_url)

        # 检查是否已有会话
        if resp.status_code not in (301, 302, 303, 307):
            html = resp.text
            err = CasParser.find_login_error(html)
            if err:
                raise BoyaApiError("cas_error", err)

            params = CasParser.build_login_params(html, username, password, captcha=captcha)
            post_resp = self.http_client.post(sso_url, data=params)

            # 跟随重定向
            curr = post_resp
            for _ in range(8):
                if curr.status_code in (301, 302, 303, 307) and curr.headers.get("location"):
                    target = urljoin(str(curr.url), curr.headers.get("location"))
                    curr = self.http_client.get(target)
                else:
                    break

            final_html = curr.text
            if CasParser.is_ignorable_password_expiry(final_html):
                execution = CasParser.extract_execution(final_html)
                if execution:
                    action_url = str(curr.url).split("?")[0]
                    self.http_client.post(
                        action_url,
                        data={"execution": execution, "_eventId": "ignoreAndContinue"},
                    )

        # 激活用户中心并换取 token
        return self.acquire_token()

    def acquire_token(self) -> str:
        """在已具备 SSO/WebVPN 会话的基础上访问博雅系统 CAS 换取 token"""
        # 激活用户中心
        try:
            self.http_client.get(self.upstream(UC_ACTIVATE), timeout=10)
        except Exception:
            pass

        token = self._follow_for_token()
        if not token:
            raise BoyaApiError("token_acquire_failed", "未能从博雅系统重定向中解析出 token")

        self.token = token
        logger.info(f"成功提取博雅 Token: {token[:8]}***")
        return token

    def _follow_for_token(self) -> Optional[str]:
        for entry in [self.upstream(BYKC_CAS), self.upstream(BYKC_CAS_EMPTY_TOKEN)]:
            curr_url = entry
            for _ in range(12):
                resp = self.http_client.get(curr_url, follow_redirects=False, timeout=15)
                # 1. 检查当前 URL 中的 token
                t = self._extract_token(str(resp.url))
                if t:
                    return t
                # 2. 检查 Location 头
                loc = resp.headers.get("location")
                if loc:
                    t = self._extract_token(loc)
                    if t:
                        return t
                    curr_url = urljoin(str(resp.url), loc)
                elif 300 <= resp.status_code <= 399:
                    break
                else:
                    if resp.status_code == 200:
                        t = self._extract_token(resp.text)
                        if t:
                            return t
                    break
        return None

    def _extract_token(self, url: str) -> Optional[str]:
        if not url:
            return None
        parsed = urlparse(url)
        q = parse_qs(parsed.query).get("token")
        if q and q[0]:
            return q[0]
        m = re.search(r"[?&]token=([^&#\s]+)", url)
        return m.group(1) if m else None

    def call(self, api_name: str, payload: Any = None) -> Dict[str, Any]:
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
            "authtoken": self.token,
            **req_enc.headers,
        }

        resp = self.http_client.post(endpoint_url, content=req_enc.body, headers=headers, timeout=25)
        if resp.status_code in (401, 403):
            raise BoyaSessionExpired(f"博雅会话已失效 (HTTP {resp.status_code})")

        # 检查是否被重定向到 CAS 登录页
        if "login" in resp.text.lower() and "<html" in resp.text.lower():
            raise BoyaSessionExpired("博雅凭证过期，已被重定向至登录页")

        try:
            decoded = crypto.decrypt_response(resp.content)
        except Exception as e:
            raise BoyaApiError("decrypt_error", f"解密博雅响应失败: {str(e)[:120]}")

        if not isinstance(decoded, dict):
            return {"data": decoded}

        status = decoded.get("status")
        errmsg = decoded.get("errmsg") or decoded.get("msg") or ""
        if status not in ("0", 0, "200", 200, None):
            raise BoyaApiError(status, str(errmsg))

        return decoded

    def get_all_config(self) -> Dict[str, Any]:
        return self.call("getAllConfig", {})

    def query_course_page(self, page_number: int = 1, page_size: int = 100) -> Dict[str, Any]:
        return self.call("queryStudentSemesterCourseByPage", {"pageNumber": page_number, "pageSize": page_size})

    def query_courses(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        """拉取全量学期博雅课程"""
        all_courses = []
        page = 1
        while page <= max_pages:
            res = self.query_course_page(page, page_size=100)
            data = res.get("data") or {}
            content = data.get("content") or []
            all_courses.extend(content)

            total_pages = data.get("totalPages") or 1
            if data.get("last") is True or page >= int(total_pages):
                break
            if not content:
                break
            page += 1
        return all_courses

    def query_chosen_courses(self, start_date: str = "2024-01-01", end_date: str = "2027-01-01") -> List[Dict[str, Any]]:
        """查询当前学生已选中的博雅课程"""
        data = self.call("queryChosenCourse", {"startDate": start_date, "endDate": end_date})
        raw_list = (data.get("data") or {}).get("courseList") or []
        res = []
        for item in raw_list:
            info = item.get("courseInfo") or {}
            real_cid = info.get("id") or item.get("courseId") or item.get("course_id")
            chosen_reg_id = item.get("id")
            merged = {**info, **item}
            if real_cid is not None:
                merged["id"] = real_cid
                merged["courseId"] = real_cid
            merged["chosenCourseId"] = chosen_reg_id
            merged["selected"] = True
            if "checkin" in item:
                merged["checkin"] = item["checkin"]
            if "pass" in item:
                merged["pass"] = item["pass"]
            if "score" in item:
                merged["score"] = item["score"]
            if "signInfo" in item:
                merged["signInfo"] = item["signInfo"]
            res.append(merged)
        return res

    def query_statistics(self) -> Dict[str, Any]:
        """获取学生博雅学分完成情况与分类考核统计"""
        data = self.call("queryStatisticByUserId", {})
        return data.get("data") or {}


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