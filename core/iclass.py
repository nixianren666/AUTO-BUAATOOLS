"""
BUAA 课程签到 (iclass) 核心服务模块
复刻自 BUAASubnet/UBAA LocalSigninApiBackend & SigninClient
"""

import base64
import asyncio
import datetime
import logging
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.cas import CasParser
from core.cas_transport import resolve_auth_redirect, follow_auth_response, CasFlowError, CasCaptchaRequired, REDIRECTS
from core.domain import now as china_now, trusted_url, regular_allowed, regular_window, CHINA
from core import operations
from core.regular_policy import MAX_POSTS, minimum_retry_delay
from core.webvpn import from_webvpn_url, to_webvpn_url

logger = logging.getLogger("buaa_signin")


class IclassSessionExpired(RuntimeError):
    """An explicit authentication response, distinct from a transport failure."""


class IclassReadError(RuntimeError):
    """A failed read must not discard credentials or authorize a write."""

SIGNIN_MY_CENTER_URL = "https://iclass.buaa.edu.cn:8346/?type=jumpMyCenter"
SIGNIN_LOGIN_REDIRECT_LIMIT = 10


def extract_login_name_from_url(url: str) -> Optional[str]:
    """从重定向 URL 或 Location 中提取 loginName 查询参数"""
    if not url:
        return None
    parsed = urllib.parse.urlsplit(url)
    query_params = urllib.parse.parse_qs(parsed.query)
    if "loginName" in query_params and query_params["loginName"]:
        return query_params["loginName"][0]
    # 尝试在整个 URL 字符串中匹配 loginName=...
    if "loginName=" in url:
        part = url.split("loginName=", 1)[1]
        raw_val = part.split("&", 1)[0].split("#", 1)[0]
        return urllib.parse.unquote(raw_val)
    return None


def resolve_redirect_url(current_url: str, location: str) -> str:
    """处理相对路径或绝对路径的重定向目标 URL"""
    return resolve_auth_redirect(current_url, location)


def sanitize_signin_message(success: bool, raw_message: Optional[str]) -> str:
    """标准化签到反馈文案，保持与 UBAA 一致的友好提示"""
    if success:
        return raw_message if (raw_message and raw_message.strip()) else "签到成功"
    msg = raw_message or ""
    if "已签到" in msg:
        return "您今天已经签到过了"
    if "未开始" in msg:
        return "当前还未到签到时间"
    if "不是上课时间" in msg:
        return "当前不是上课时间，无法签到"
    if "已结束" in msg:
        return "本次签到已结束"
    if "范围" in msg:
        return "当前不在可签到范围内"
    if "用户不存在" in msg:
        return "签到账号不存在，请联系管理员"
    if "课程" in msg and "不存在" in msg:
        return "未找到对应课程，请刷新后重试"
    return msg if msg else "签到失败，请稍后重试"


class IclassClient:
    def __init__(self, mode: str = "direct"):
        """
        mode: 'direct' (校园网直连) 或 'webvpn' (外网 WebVPN)
        """
        self.mode = mode.lower()
        self._client: Optional[httpx.AsyncClient] = None
        self._cookies = httpx.Cookies()
        self.user_info: Dict[str, Any] = {}
        self.user_id: Optional[str] = None
        self.session_id: Optional[str] = None
        self.login_name: Optional[str] = None
        self.last_error: Optional[str] = None
        self.request_guard = lambda: True
        self.operation_user = None
        self.clock = china_now
        self._signin_lock = asyncio.Lock()
        self.actual_sign_posts = 0

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                cookies=self._cookies,
                verify=True,
                trust_env=False,
                timeout=httpx.Timeout(timeout=20.0, connect=4.0),
                follow_redirects=False,
            )
        return self._client

    def wrap_url(self, url: str) -> str:
        """根据当前连接模式决定是否进行 WebVPN URL 封装"""
        if self.mode == "webvpn":
            return to_webvpn_url(url)
        return url

    def is_authenticated(self) -> bool:
        return bool((self.user_id and self.session_id) or self.user_info.get("schoolid"))

    async def close(self):
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._cookies.clear()
        self.user_id = None
        self.session_id = None
        self.login_name = None
        self.user_info.clear()
        self._captcha_form = None

    async def get_captcha_image(self, captcha_id: str) -> Optional[str]:
        """获取验证码并返回 Base64 编码的 data URL"""
        base_url = self.wrap_url("https://sso.buaa.edu.cn/captcha")
        resp = await self.client.get(base_url, params={"captchaId":captcha_id})
        if resp.status_code == 200:
            b64 = base64.b64encode(resp.content).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
        return None

    async def _captcha_result(self, username, response, info):
        kind, captcha_id = info
        self._captcha_form = (username, self.mode, captcha_id, response)
        try:
            image = await self.get_captcha_image(captcha_id)
        except httpx.HTTPError:
            image = None
        return {"status":"captcha_required", "captcha_id":captcha_id,
                "captcha_type":kind, "captcha_image":image, "mode":self.mode,
                "message":"统一认证需要验证码，请输入图中内容后再提交" if image else "学校要求额外验证，验证码暂未加载，请重试或先在学校官方页面处理"}

    async def login_sso(self, username: str, password: str, captcha: str = "", captcha_id: str = "") -> Dict[str, Any]:
        # A failed new authentication cannot keep an old business identity live.
        self.user_info = {}
        self.user_id = self.session_id = self.login_name = None
        sso_url = self.wrap_url("https://sso.buaa.edu.cn/login")
        pending = getattr(self, '_captcha_form', None)
        self._captcha_form = None
        retry_challenge = bool(captcha and pending and pending[:3] == (username, self.mode, captcha_id))
        try:
            if retry_challenge:
                response = pending[3]
            else:
                response = await self.client.get(sso_url)
                if response.status_code in REDIRECTS:
                    await follow_auth_response(response, self.client, self.mode)
                    return await self._finish_sso_login(username)
                if response.status_code != 200:
                    return {"status":"failed","message":"统一认证登录页面暂不可用，请稍后重试"}
                info = CasParser.detect_captcha(response.text)
                if info:
                    return await self._captcha_result(username, response, info)
            html = response.text
            if CasParser.is_ignorable_password_expiry(html):
                await follow_auth_response(response, self.client, self.mode)
                return await self._finish_sso_login(username)
            error = None if retry_challenge else CasParser.find_login_error(html)
            if error:
                return {"status":"failed","message":error}
            if not CasParser.extract_execution(html):
                return {"status":"failed","message":"统一认证登录页面格式异常，请稍后重试"}
            params = CasParser.build_login_params(html, username, password, captcha=captcha)
            submitted = await self.client.post(sso_url, data=params)
            await follow_auth_response(submitted, self.client, self.mode)
            return await self._finish_sso_login(username)
        except CasCaptchaRequired as challenge:
            return await self._captcha_result(username, challenge.response, challenge.captcha)
        except CasFlowError as error:
            return {"status":"failed","message":str(error)}

    async def _finish_sso_login(self, username):
        activation = await self.client.get(self.wrap_url("https://uc.buaa.edu.cn/api/login?target=https%3A%2F%2Fuc.buaa.edu.cn%2F%23%2Fuser%2Flogin"))
        await follow_auth_response(activation, self.client, self.mode)
        response = await self.client.get(self.wrap_url("https://uc.buaa.edu.cn/api/uc/status"))
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or str(payload.get("code")) != "0" or not isinstance(data, dict) or not (data.get("schoolid") or data.get("username")):
            self.user_info = {}
            return {"status": "failed", "message": "官方未确认登录身份"}
        if str(username).isascii() and str(username).isdigit() and str(data.get("schoolid") or data.get("username")) != str(username):
            self.user_info = {}
            return {"status": "failed", "message": "官方登录身份与请求账号不一致"}
        self.user_info = {"name": data.get("name") or data.get("realName") or username, "schoolid": data.get("schoolid") or data["username"], "department": data.get("department") or ""}
        return {"status": "success", "user": self.user_info}

    async def resolve_login_name(self) -> Optional[str]:
        """
        通过跟踪 iclass MyCenter 跳转页提取 loginName
        对应 UBAA LocalSigninApiBackend.resolveLoginName
        """
        if self.login_name:
            return self.login_name

        raw_url = SIGNIN_MY_CENTER_URL
        name = extract_login_name_from_url(raw_url)
        if name:
            self.login_name = name
            return name

        curr_url = self.wrap_url(raw_url)
        try:
            for _ in range(SIGNIN_LOGIN_REDIRECT_LIMIT):
                resp = await self.client.get(curr_url)
                final_url = str(resp.url)
                if self.mode == "webvpn":
                    final_url = from_webvpn_url(final_url)

                name = extract_login_name_from_url(trusted_url(final_url))
                if name:
                    self.login_name = name
                    return name

                location = resp.headers.get("Location")
                if location:
                    loc_unwrapped = from_webvpn_url(location) if self.mode == "webvpn" else location
                    loc_unwrapped = resolve_auth_redirect(final_url, loc_unwrapped, 'direct')
                    name = extract_login_name_from_url(loc_unwrapped)
                    if name:
                        self.login_name = name
                        return name

                if resp.status_code not in range(300, 400) or not location:
                    return None

                resolved = resolve_redirect_url(final_url, loc_unwrapped)
                name = extract_login_name_from_url(resolved)
                if name:
                    self.login_name = name
                    return name

                curr_url = self.wrap_url(resolved)
        except Exception as e:
            logger.warning(f"Error during resolve_login_name: {type(e).__name__}")
            self.last_error = f"连接 iclass 服务失败: {type(e).__name__}"
            return None

        return None

    async def login_iclass(self) -> bool:
        """
        使用解析出的 loginName 登录 iclass 移动客户端系统
        优先接入当前主流 8346 端口 /esp/auth/signIn，同时兼容备用 8347 端口
        """
        login_name = await self.resolve_login_name()
        if not login_name:
            self.last_error = "未取得可信课堂登录名，请重新认证"
        if not login_name:
            self.last_error = self.last_error or "无法从北航课堂系统中解析登录名 (loginName)"
            return False

        # 方案一：8346 端口 /esp/auth/signIn (当前官方移动端/外网主流接口，响应极速)
        esp_login_url = self.wrap_url("https://iclass.buaa.edu.cn:8346/esp/auth/signIn")
        try:
            esp_resp = await self.client.get(
                esp_login_url,
                params={
                    "flag": "3",
                    "verifyCode": "",
                    "verifyUuid": "",
                    "loginName": login_name,
                    "password": "",
                    "verificationType": "",
                    "deviceType": "phone",
                },
                timeout=httpx.Timeout(timeout=5.0, connect=3.0),
            )
            if esp_resp.status_code == 200:
                data = esp_resp.json()
                meta = data.get("meta") or {}
                if meta.get("code") == "0" or meta.get("success") is True:
                    result = data.get("data", {}).get("result", {})
                    self.user_id = str(result.get("id") or "")
                    self.session_id = result.get("sessionId") if isinstance(result.get("sessionId"), str) else None
                    real_name = result.get("realName") or result.get("nickName")
                    if real_name:
                        self.user_info["name"] = real_name
                    if self.user_id and self.session_id:
                        return True
        except Exception as e:
            logger.debug(f"8346 esp/auth/signIn attempt: {type(e).__name__}")

        # 方案二：8347 端口 /app/user/login.action (旧版客户端接口降级兜底)
        app_login_url = self.wrap_url("https://iclass.buaa.edu.cn:8347/app/user/login.action")
        try:
            resp = await self.client.get(
                app_login_url,
                params={
                    "password": "",
                    "phone": login_name,
                    "userLevel": "1",
                    "verificationType": "2",
                    "verificationUrl": "",
                },
                timeout=httpx.Timeout(timeout=4.0, connect=2.5),
            )
            if resp.status_code == 200:
                data = resp.json()
                status = str(data.get("STATUS", ""))
                if status in ("0", "200", "success"):
                    result = data.get("result") or {}
                    self.user_id = str(result.get("id") or "")
                    self.session_id = result.get("sessionId") if isinstance(result.get("sessionId"), str) else None
                    real_name = result.get("realName") or result.get("nickName")
                    if real_name:
                        self.user_info["name"] = real_name
                    return bool(self.user_id and self.session_id)
                else:
                    self.last_error = data.get("ERRMSG") or "iclass 登录失败"
        except Exception as e:
            self.last_error = f"连接 iclass 接口失败: {type(e).__name__}"

        return bool(self.user_id and self.session_id)

    async def ensure_iclass_session(self) -> bool:
        """确保当前具备可用的 iclass userId 与 sessionId"""
        if self.user_id and self.session_id:
            return True
        return await self.login_iclass()

    async def get_today_classes(self) -> List[Dict[str, Any]]:
        return await self.get_classes(self.clock().date())

    async def get_classes(self, class_date) -> List[Dict[str, Any]]:
        """
        获取今日排课列表及签到状态
        对应 UBAA LocalSigninApiBackend.getTodayClasses
        """
        if not await self.ensure_iclass_session():
            # Failed bootstrap can be a routing/HTTP/protocol failure. It does
            # not establish that the existing SSO cookies need a password POST.
            raise IclassReadError("课堂会话暂未建立，请检查网络或在界面重新连接")

        date_str = class_date.strftime("%Y%m%d")

        headers = {"sessionId": self.session_id or ""}
        params = {"id": self.user_id or "", "dateStr": date_str}

        candidate_urls = [
            self.wrap_url("https://iclass.buaa.edu.cn:8346/app/course/get_stu_course_sched.action"),
            self.wrap_url("https://iclass.buaa.edu.cn:8347/app/course/get_stu_course_sched.action"),
        ]

        errors = []
        for url in candidate_urls:
            try:
                resp = await self.client.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=httpx.Timeout(timeout=4.0, connect=2.5),
                )
                expired = resp.status_code == 401
                if resp.status_code in REDIRECTS and resp.headers.get("location"):
                    target = resolve_auth_redirect(str(resp.url), resp.headers["location"], self.mode)
                    parsed = urllib.parse.urlsplit(from_webvpn_url(target))
                    expired = (parsed.hostname in ("sso.buaa.edu.cn", "uc.buaa.edu.cn", "d.buaa.edu.cn")
                               and parsed.path in ("/login", "/api/login"))
                if expired:
                    self.user_id = self.session_id = None
                    raise IclassSessionExpired("课堂会话失效，请重新认证")
                resp.raise_for_status()

                data = resp.json()
                if not isinstance(data, dict):
                    raise IclassReadError("课堂课表响应格式异常")
                # The course-read endpoint uses this exact envelope for a day
                # without a returned schedule (observed across both ports).
                # Do not generalize non-success statuses, contradictory result
                # rows or error messages into an empty successful read.
                if data == {"STATUS": "2"}:
                    return []
                status = str(data.get("STATUS", ""))
                if "STATUS" not in data or status not in ("0", "200", "success"):
                    message = data.get("ERRMSG")
                    if isinstance(message, str) and any(marker in message for marker in
                            ("未登录", "未登陆", "请重新登录", "会话失效", "会话已失效", "会话过期", "登录已过期")):
                        self.user_id = self.session_id = None
                        raise IclassSessionExpired("课堂会话失效，请重新认证")
                    raise IclassReadError("课堂服务未确认课表数据，保留现有会话")
                if not isinstance(data.get("result"), list):
                    raise RuntimeError("课堂课表响应不完整")

                classes = []
                for item in data.get("result") or []:
                    raw_status = item.get("signStatus")
                    valid_status = (type(raw_status) is int and raw_status in (0,1)) or (type(raw_status) is str and raw_status in ("0","1"))
                    sign_status = int(raw_status) if valid_status else None

                    c_sched_id = str(item.get("id") or item.get("courseSchedId") or "")
                    c_id = str(item.get("courseId") or c_sched_id)
                    begin_time = str(item.get("classBeginTime") or "")
                    end_time = str(item.get("classEndTime") or "")
                    if len(begin_time) in (5, 8):
                        begin_time = class_date.isoformat() + " " + begin_time
                    if len(end_time) in (5, 8):
                        end_time = class_date.isoformat() + " " + end_time
                    start_str = begin_time[11:16] if len(begin_time) >= 16 else (begin_time or "--")
                    end_str = end_time[11:16] if len(end_time) >= 16 else (end_time or "--")
                    room = str(item.get("classroomName") or item.get("classroom") or item.get("roomName") or "校内教室")
                    teacher = str(item.get("teacherName") or item.get("teacher") or "任课教师")

                    classes.append(
                        {
                            "id": c_sched_id,
                            "courseSchedId": c_sched_id,
                            "courseId": c_id,
                            "courseName": str(item.get("courseName") or "未知课程"),
                            "classBeginTime": begin_time,
                            "classEndTime": end_time,
                            "startTime": start_str,
                            "endTime": end_str,
                            "classroomName": room,
                            "classroom": room,
                            "teacherName": teacher,
                            "teacher": teacher,
                            "signStatus": sign_status,  # 0: 未签到, 1: 已签到
                        }
                    )
                return classes
            except IclassSessionExpired:
                raise
            except Exception as e:
                errors.append(type(e).__name__)
                logger.debug("课表读取失败: %s", type(e).__name__)
                continue

        raise IclassReadError("课表读取失败，保留上次数据，请检查网络与认证")

    def signin_record(self, course_id):
        user = self.operation_user or self.user_info.get("schoolid")
        if not user:
            return None
        key = operations.ledger.key(user, "iclass-sign", course_id, self.clock().date())
        return operations.ledger.read(key)

    async def perform_signin(self, course_id, guard=None):
        """Manual and automatic callers share identity, window and actual POST budget."""
        if not str(course_id).isdigit() or int(course_id) <= 0:
            return False, "排课 ID 无效，未提交"
        async with self._signin_lock:
            if not self.request_guard() or (guard is not None and not guard()):
                return False, "账号、连接模式或守护状态已变化，未提交"
            if not await self.ensure_iclass_session():
                return False, "课堂认证未完成"
            user = self.operation_user or self.user_info.get("schoolid")
            if not user:
                return False, "未确认账号身份，未提交"
            query_day = self.clock().date()
            classes = await self.get_today_classes()
            course = next((c for c in classes if str(c.get("courseSchedId") or c.get("id")) == str(course_id)), None)
            if not course:
                return False, "不属于此账号今日排课，未提交"
            key = operations.ledger.key(user, "iclass-sign", course_id, self.clock().date())
            if str(course.get("signStatus")) == "1":
                operations.ledger.confirmed(key)
                return True, "官方已确认签到，无需重复提交"
            if not regular_allowed(course, self.clock()):
                return False, "不在开课前十分钟至下课的有效窗口、下课时间未核实或考勤状态未知，未提交"
            response = await self.client.get(self.wrap_url("https://iclass.buaa.edu.cn:8347/app/common/get_timestamp.action"))
            response.raise_for_status()
            timestamp = response.json().get("timestamp")
            if not timestamp or not str(timestamp).isdigit() or len(str(timestamp)) not in (10, 13):
                return False, "获取学校时间失败，未提交签到"
            seconds = int(timestamp) / (1000 if len(str(timestamp)) == 13 else 1)
            school_now = datetime.datetime.fromtimestamp(seconds, CHINA).replace(tzinfo=None)
            if abs((school_now-self.clock()).total_seconds()) > 30 or not regular_allowed(course, school_now):
                return False, "设备与学校时间偏差过大或学校窗口已关闭，未提交"
            if self.clock().date() != query_day or not self.request_guard() or (guard is not None and not guard()) or not regular_allowed(course, self.clock()):
                return False, "账号已暂停或已超过签到窗口，未提交"
            try:
                start, _ = regular_window(course, self.clock())
                claimed = operations.ledger.claim(key, limit=MAX_POSTS, retry_delay=lambda attempts: minimum_retry_delay(attempts, self.clock() < start and school_now < start))
            except operations.OperationBusy as exc:
                return False, str(exc)
            if not claimed:
                return True, "请求已被接受，等待官方状态同步，不再重发"
            # A persistent claim can wait for another writer; recheck before sending.
            if self.clock().date() != query_day or not self.request_guard() or (guard is not None and not guard()) or not regular_allowed(course, self.clock()):
                operations.ledger.failed_before_send(key)
                return False, "账号已暂停或已超过签到窗口，未提交"
            try:
                self.actual_sign_posts += 1
                response = await self.client.post(self.wrap_url("https://iclass.buaa.edu.cn:8347/app/course/stu_scan_sign.action"), headers={"sessionId": self.session_id}, params={"courseSchedId": course_id, "timestamp": str(timestamp)}, data={"id": self.user_id})
                if response.status_code in (401, 403):
                    self.user_id = self.session_id = None
                    operations.ledger.finish(key, "failed")
                    return False, "课堂会话过期，请重新认证"
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or "STATUS" not in data:
                    raise ValueError("签到返回缺少官方状态")
                if str(data.get("STATUS")) in ("0", "200", "success") and not isinstance(data.get("result"), dict):
                    raise ValueError("签到已接受但缺少动作结果，等待官方复核")
                if str(data.get("STATUS")) in ("0", "200", "success") and str(data["result"].get("stuSignStatus")) not in ("0", "1"):
                    raise ValueError("签到动作结果不明确，等待官方复核")
                success = str(data.get("STATUS")) in ("0", "200", "success") and str((data.get("result") or {}).get("stuSignStatus")) == "1"
                message = data.get("ERRMSG")
                operations.ledger.finish(key, "success" if success else "failed")
                if not success and message and "登录" in message:
                    self.user_id = self.session_id = None
                return success, sanitize_signin_message(success, message)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                operations.ledger.failed_before_send(key)
                self.actual_sign_posts -= 1
                return False, "连接尚未建立，未发送签到；将在有效窗口内退避重试"
            except BaseException:
                operations.ledger.finish(key, "uncertain")
                raise
