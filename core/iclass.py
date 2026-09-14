"""
BUAA 课程签到 (iclass) 核心服务模块
复刻自 BUAASubnet/UBAA LocalSigninApiBackend & SigninClient
"""

import base64
import datetime
import logging
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import httpx

from core.cas import CasParser
from core.webvpn import from_webvpn_url, to_webvpn_url

logger = logging.getLogger("buaa_signin")

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
    loc = location.strip()
    if loc.startswith("http://") or loc.startswith("https://"):
        return loc
    if loc.startswith("//"):
        parsed = urllib.parse.urlsplit(current_url)
        return f"{parsed.scheme}:{loc}"
    # WebVPN 网关返回的相对路径（如 /https-8346/encryptedHost/path）
    if any(loc.startswith(p) for p in ("/https-", "/http-", "/wss-", "/ws-")):
        return f"https://d.buaa.edu.cn{loc}"
    return urllib.parse.urljoin(current_url, loc)


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
                verify=False,
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

    async def get_captcha_image(self, captcha_id: str) -> Optional[str]:
        """获取验证码并返回 Base64 编码的 data URL"""
        base_url = self.wrap_url("https://sso.buaa.edu.cn/captcha")
        url = f"{base_url}?captchaId={captcha_id}"
        resp = await self.client.get(url)
        if resp.status_code == 200:
            b64 = base64.b64encode(resp.content).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
        return None

    async def login_sso(
        self,
        username: str,
        password: str,
        captcha: str = "",
        captcha_id: str = "",
    ) -> Dict[str, Any]:
        """
        执行北航统一认证 (SSO) 登录
        返回格式:
        - 成功: {"status": "success", "user": user_info}
        - 需验证码: {"status": "captcha_required", "captcha_id": id, "captcha_image": data_url}
        - 失败: {"status": "failed", "message": error_msg}
        """
        sso_url = self.wrap_url("https://sso.buaa.edu.cn/login")
        resp = await self.client.get(sso_url)

        # 若直接返回 30x，可能已有登录态
        if resp.status_code in (301, 302, 303, 307):
            return await self._finish_sso_login(username)

        html = resp.text
        # 检查是否需要验证码
        captcha_info = CasParser.detect_captcha(html)
        if captcha_info and not captcha:
            c_type, c_id = captcha_info
            img = await self.get_captcha_image(c_id)
            return {
                "status": "captcha_required",
                "captcha_id": c_id,
                "captcha_image": img,
                "message": "本次登录需要输入图形验证码",
            }

        # 检查页面错误提示
        tip = CasParser.extract_tip_text(html)
        if tip:
            return {"status": "failed", "message": tip}

        # 构造 POST 参数
        params = CasParser.build_login_params(
            html=html,
            username=username,
            password=password,
            captcha=captcha,
        )

        post_resp = await self.client.post(sso_url, data=params)

        # 检查是否要求跟随重定向
        curr_resp = post_resp
        max_hops = 8
        while curr_resp.status_code in (301, 302, 303, 307) and max_hops > 0:
            max_hops -= 1
            loc = curr_resp.headers.get("Location")
            if not loc:
                break
            redirect_target = resolve_redirect_url(str(curr_resp.url), loc)
            if self.mode == "webvpn":
                redirect_target = self.wrap_url(from_webvpn_url(redirect_target))
            curr_resp = await self.client.get(redirect_target)

        final_html = curr_resp.text
        # 检查是否有跳过密码风险提示页面
        if CasParser.is_ignorable_password_expiry(final_html):
            execution = CasParser.extract_execution(final_html)
            if execution:
                curr_url = str(curr_resp.url).split("?")[0]
                cont_resp = await self.client.post(
                    curr_url,
                    data={"execution": execution, "_eventId": "ignoreAndContinue"},
                )
                curr_resp = cont_resp

        # 检查是否有登录错误信息
        login_err = CasParser.find_login_error(curr_resp.text)
        if login_err:
            return {"status": "failed", "message": login_err}

        if "input name=\"execution\"" in curr_resp.text and curr_resp.status_code == 200:
            return {"status": "failed", "message": "账号或密码错误，请重新输入"}

        return await self._finish_sso_login(username)

    async def _finish_sso_login(self, username: str) -> Dict[str, Any]:
        """激活统一用户中心并拉取用户信息"""
        try:
            # 激活 UC 登录
            uc_login_url = self.wrap_url(
                "https://uc.buaa.edu.cn/api/login?target=https%3A%2F%2Fuc.buaa.edu.cn%2F%23%2Fuser%2Flogin"
            )
            await self.client.get(uc_login_url)

            # 查询用户信息
            user_status_url = self.wrap_url("https://uc.buaa.edu.cn/api/user/info")
            info_resp = await self.client.get(user_status_url)
            if info_resp.status_code == 200:
                try:
                    data = info_resp.json()
                    user_data = data.get("data") or {}
                    self.user_info = {
                        "name": user_data.get("name") or user_data.get("realName") or username,
                        "schoolid": user_data.get("schoolid") or user_data.get("username") or username,
                        "department": user_data.get("department") or "",
                    }
                except Exception:
                    self.user_info = {"name": username, "schoolid": username}
            else:
                self.user_info = {"name": username, "schoolid": username}

            return {"status": "success", "user": self.user_info}
        except Exception as e:
            logger.warning(f"Failed to fetch UC user info: {e}")
            self.user_info = {"name": username, "schoolid": username}
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

                name = extract_login_name_from_url(final_url)
                if name:
                    self.login_name = name
                    return name

                location = resp.headers.get("Location")
                if location:
                    loc_unwrapped = from_webvpn_url(location) if self.mode == "webvpn" else location
                    name = extract_login_name_from_url(loc_unwrapped)
                    if name:
                        self.login_name = name
                        return name

                if resp.status_code not in range(300, 400) or not location:
                    # 检查响应 body 中是否包含 loginName
                    name = extract_login_name_from_url(resp.text)
                    if name:
                        self.login_name = name
                        return name
                    return None

                resolved = resolve_redirect_url(final_url, loc_unwrapped)
                name = extract_login_name_from_url(resolved)
                if name:
                    self.login_name = name
                    return name

                curr_url = self.wrap_url(resolved)
        except Exception as e:
            logger.warning(f"Error during resolve_login_name: {e}")
            self.last_error = f"连接 iclass 服务失败: {e}"
            return None

        return None

    async def login_iclass(self) -> bool:
        """
        使用解析出的 loginName 登录 iclass 移动客户端系统
        优先接入当前主流 8346 端口 /esp/auth/signIn，同时兼容备用 8347 端口
        """
        login_name = await self.resolve_login_name()
        if not login_name:
            login_name = self.user_info.get("schoolid")
            if login_name:
                self.login_name = str(login_name)
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
                    self.user_id = str(result.get("id", ""))
                    self.session_id = str(result.get("sessionId", ""))
                    real_name = result.get("realName") or result.get("nickName")
                    if real_name:
                        self.user_info["name"] = real_name
                    if self.user_id and self.session_id:
                        return True
        except Exception as e:
            logger.debug(f"8346 esp/auth/signIn attempt: {e}")

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
                    self.user_id = str(result.get("id", ""))
                    self.session_id = str(result.get("sessionId", ""))
                    real_name = result.get("realName") or result.get("nickName")
                    if real_name:
                        self.user_info["name"] = real_name
                    return bool(self.user_id and self.session_id)
                else:
                    self.last_error = data.get("ERRMSG") or "iclass 登录失败"
        except Exception as e:
            self.last_error = f"连接 iclass 接口失败: {e}"

        return bool(self.user_id and self.session_id)

    async def ensure_iclass_session(self) -> bool:
        """确保当前具备可用的 iclass userId 与 sessionId"""
        if self.user_id and self.session_id:
            return True
        return await self.login_iclass()

    async def get_today_classes(self) -> List[Dict[str, Any]]:
        """
        获取今日排课列表及签到状态
        对应 UBAA LocalSigninApiBackend.getTodayClasses
        """
        if not await self.ensure_iclass_session():
            raise RuntimeError(self.last_error or "未登录课堂考勤系统或登录会话已失效")

        now = datetime.datetime.now()
        date_str = now.strftime("%Y%m%d")

        headers = {"sessionId": self.session_id or ""}
        params = {"id": self.user_id or "", "dateStr": date_str}

        candidate_urls = [
            self.wrap_url("https://iclass.buaa.edu.cn:8346/app/course/get_stu_course_sched.action"),
            self.wrap_url("https://iclass.buaa.edu.cn:8347/app/course/get_stu_course_sched.action"),
        ]

        for url in candidate_urls:
            try:
                resp = await self.client.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=httpx.Timeout(timeout=4.0, connect=2.5),
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                status = str(data.get("STATUS", ""))
                if "STATUS" in data and status not in ("0", "200", "success"):
                    continue

                classes = []
                for item in data.get("result") or []:
                    raw_status = item.get("signStatus", 0)
                    try:
                        sign_status = int(raw_status)
                    except (ValueError, TypeError):
                        sign_status = 0

                    c_sched_id = str(item.get("id") or item.get("courseSchedId") or "")
                    c_id = str(item.get("courseId") or c_sched_id)
                    begin_time = str(item.get("classBeginTime") or "")
                    end_time = str(item.get("classEndTime") or "")
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
            except Exception as e:
                logger.debug(f"Fetch sched from {url} error: {e}")
                continue

        return []

    async def perform_signin(self, course_id: str) -> Tuple[bool, str]:
        """
        提交指定排课的课堂签到
        对应 UBAA LocalSigninApiBackend.performSignin
        """
        if not await self.ensure_iclass_session():
            return False, self.last_error or "未登录 iclass 系统"

        # 1. 获取服务器时间戳
        ts_candidates = [
            self.wrap_url("https://iclass.buaa.edu.cn:8346/app/common/get_timestamp.action"),
            self.wrap_url("https://iclass.buaa.edu.cn:8347/app/common/get_timestamp.action")
            if self.mode == "webvpn"
            else "http://iclass.buaa.edu.cn:8081/app/common/get_timestamp.action",
        ]
        timestamp = None
        for ts_url in ts_candidates:
            try:
                ts_resp = await self.client.get(ts_url, timeout=httpx.Timeout(timeout=4.0, connect=2.5))
                if ts_resp.status_code == 200:
                    ts_data = ts_resp.json()
                    timestamp = ts_data.get("timestamp")
                    if timestamp:
                        break
            except Exception:
                continue

        if not timestamp:
            timestamp = int(datetime.datetime.now().timestamp() * 1000)

        # 2. 提交扫码签到
        sign_candidates = [
            self.wrap_url("https://iclass.buaa.edu.cn:8346/eschool/app/course/stu_scan_sign.action"),
            self.wrap_url("https://iclass.buaa.edu.cn:8347/eschool/app/course/stu_scan_sign.action")
            if self.mode == "webvpn"
            else "http://iclass.buaa.edu.cn:8081/eschool/app/course/stu_scan_sign.action",
        ]

        headers = {"sessionId": self.session_id or ""}
        params = {"courseSchedId": course_id, "timestamp": str(timestamp)}
        form_data = {"id": self.user_id or ""}

        for sign_url in sign_candidates:
            try:
                resp = await self.client.post(
                    sign_url,
                    headers=headers,
                    params=params,
                    data=form_data,
                    timeout=httpx.Timeout(timeout=5.0, connect=3.0),
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                status = str(data.get("STATUS", ""))
                raw_msg = data.get("ERRMSG")
                result = data.get("result") or {}
                stu_status = str(result.get("stuSignStatus", ""))

                is_ok = (status in ("0", "200", "success")) and (stu_status == "1")

                # 若提示需要登录则重新登录后重试一次
                if not is_ok and raw_msg and "登录" in raw_msg:
                    self.user_id = None
                    self.session_id = None
                    if await self.login_iclass():
                        headers["sessionId"] = self.session_id or ""
                        form_data["id"] = self.user_id or ""
                        resp = await self.client.post(
                            sign_url,
                            headers=headers,
                            params=params,
                            data=form_data,
                            timeout=httpx.Timeout(timeout=5.0, connect=3.0),
                        )
                        data = resp.json()
                        status = str(data.get("STATUS", ""))
                        raw_msg = data.get("ERRMSG")
                        result = data.get("result") or {}
                        stu_status = str(result.get("stuSignStatus", ""))
                        is_ok = (status in ("0", "200", "success")) and (stu_status == "1")

                msg = sanitize_signin_message(is_ok, raw_msg)
                return is_ok, msg
            except Exception as e:
                logger.debug(f"Sign attempt at {sign_url} failed: {e}")
                continue

        return False, "提交签到请求失败，网络连接超时"

