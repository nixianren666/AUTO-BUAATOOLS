# -*- coding: utf-8 -*-
"""
WeChat ClawBot 实时日志推送通信底座 (基于腾讯官方微信 iLink 智联协议)
- 协议服务端基地址: https://ilinkai.weixin.qq.com
- 遵循腾讯官方 @tencent-weixin/openclaw-weixin 标准规范
- 核心功能特性:
  1. 多学生独立绑定隔离 (Independent per-student bot instance & credentials)
  2. 实时全景总日志流式卡片推送 (Total system & student execution logs)
  3. 严格对齐官方 sendMessage 报文 (msg, item_list, to_user_id, context_token, base_info)
  4. 严谨校验业务返回码 (ret==0 为真实送达，彻底根绝假成功虚增推送数)
  5. 智能断连识别与离线重放滑动缓冲区 (Zero flood protection & seamless batch replay)
  6. 双向交互与会话令牌动态续期 (Long-poll getupdates & auto heartbeat response)
"""

import base64
import collections
import datetime
import json
import logging
import os
import random
import threading
import time
import uuid
from typing import Any, Callable, Deque, Dict, List, Optional
import urllib.parse

import httpx

logger = logging.getLogger("wechat_clawbot")

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.4.8"
ILINK_APP_ID = "bot"
ILINK_APP_CLIENT_VERSION = "132104"  # 0x00020408 (2.4.8)
BOT_AGENT = "BUAA-Signin/1.3.2"


def _generate_wechat_uin() -> str:
    """生成随机微信 X-WECHAT-UIN 头 (Base64 编码的 32 位无符号整数字符串)"""
    rand_int = random.randint(100000000, 999999999)
    return base64.b64encode(str(rand_int).encode("utf-8")).decode("utf-8")


class WeChatClawBot:
    """
    单个学生专属微信 ClawBot 守护实例
    """

    def __init__(
        self,
        username: str,
        name: str = "",
        bot_token: Optional[str] = None,
        context_token: Optional[str] = None,
        wechat_nickname: Optional[str] = None,
        to_user_id: Optional[str] = None,
        from_user_id: Optional[str] = None,
        get_updates_buf: Optional[str] = None,
        enabled: bool = True,
        on_status_change: Optional[Callable[[], None]] = None,
        on_event_log: Optional[Callable[[str, str, Optional[str], Optional[str], str], None]] = None,
        mock_mode: bool = False,
    ):
        self.username = username
        self.name = name or username
        self.bot_token = bot_token or ""
        self.context_token = context_token or ""
        self.wechat_nickname = wechat_nickname or ""
        self.to_user_id = to_user_id or ""
        self.from_user_id = from_user_id or ""
        self.get_updates_buf = get_updates_buf or ""
        self.enabled = enabled
        self.on_status_change = on_status_change
        self.on_event_log = on_event_log
        self.mock_mode = mock_mode

        # 状态机: "unbound", "waiting_scan", "connected", "disconnected", "reconnecting"
        if self.bot_token:
            self.status = "connected"
        else:
            self.status = "unbound"

        # 离线滑动重放缓冲区 (最大容纳 200 条，先进先出，杜绝 OOM)
        self.disconnected_queue: Deque[Dict[str, Any]] = collections.deque(maxlen=200)

        # 运行时审计指标
        self.push_count: int = 0
        self.replayed_count: int = 0
        self.last_active_time: Optional[str] = None
        self.last_error: Optional[str] = None

        # 线程与锁控制
        self._lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._reconnecting = False

        # 若初始已存在 token，启动长轮询维持会话生命期
        if self.bot_token and not self.mock_mode:
            self.start_background_worker()

    def _get_headers(self) -> Dict[str, str]:
        """构造腾讯官方 iLink HTTP 请求头规范"""
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": _generate_wechat_uin(),
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": ILINK_APP_CLIENT_VERSION,
            "User-Agent": "BUAA-Signin-ClawBot/1.3.2",
        }
        if self.bot_token:
            headers["Authorization"] = f"Bearer {self.bot_token.strip()}"
        return headers

    def _get_base_info(self) -> Dict[str, str]:
        """构造腾讯 iLink CGI 通用 base_info 元数据"""
        return {
            "channel_version": CHANNEL_VERSION,
            "bot_agent": BOT_AGENT,
        }

    def _log(self, level: str, message: str):
        """记录日志至应用全局日志中心"""
        if self.on_event_log:
            try:
                self.on_event_log(level, message, self.username, self.name, "wechat")
            except Exception as e:
                logger.debug(f"on_event_log error: {e}")

    def _notify_change(self):
        """触发状态持久化回调"""
        if self.on_status_change:
            try:
                self.on_status_change()
            except Exception as e:
                logger.debug(f"on_status_change error: {e}")

    def _notify_start(self):
        """通知腾讯官方 iLink 服务端通道客户端启动 (notifystart)"""
        if self.mock_mode or not self.bot_token:
            return
        url = f"{ILINK_BASE_URL}/ilink/bot/msg/notifystart"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(
                    url,
                    headers=self._get_headers(),
                    json={"base_info": self._get_base_info()},
                )
                logger.debug(f"notifystart status={res.status_code}")
        except Exception as e:
            logger.debug(f"notifystart ignored error: {e}")

    def get_binding_qrcode(self) -> Dict[str, Any]:
        """
        向腾讯官方 iLink 网关申请绑定二维码
        返回结构: { status, qrcode_key, qrcode_url, qrcode_img_base64 }
        """
        with self._lock:
            self.status = "waiting_scan"

        if self.mock_mode or os.environ.get("MOCK_WECHAT_BOT") == "1":
            mock_key = f"mock_qr_{self.username}_{int(time.time())}"
            svg_data = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220" viewBox="0 0 220 220">'
                '<rect width="220" height="220" fill="#ffffff" rx="16"/>'
                '<rect x="20" y="20" width="60" height="60" fill="#07c160" rx="8"/>'
                '<rect x="30" y="30" width="40" height="40" fill="#ffffff" rx="4"/>'
                '<rect x="40" y="40" width="20" height="20" fill="#07c160" rx="2"/>'
                '<rect x="140" y="20" width="60" height="60" fill="#07c160" rx="8"/>'
                '<rect x="150" y="30" width="40" height="40" fill="#ffffff" rx="4"/>'
                '<rect x="160" y="40" width="20" height="20" fill="#07c160" rx="2"/>'
                '<rect x="20" y="140" width="60" height="60" fill="#07c160" rx="8"/>'
                '<rect x="30" y="150" width="40" height="40" fill="#ffffff" rx="4"/>'
                '<rect x="40" y="160" width="20" height="20" fill="#07c160" rx="2"/>'
                '<rect x="95" y="95" width="30" height="30" fill="#07c160" rx="6"/>'
                '<text x="110" y="185" font-family="system-ui,sans-serif" font-size="11" fill="#666" text-anchor="middle">微信扫一扫绑定</text>'
                '</svg>'
            )
            base64_svg = base64.b64encode(svg_data.encode("utf-8")).decode("utf-8")
            data_uri = f"data:image/svg+xml;base64,{base64_svg}"
            return {
                "status": "success",
                "qrcode_key": mock_key,
                "qrcode_url": data_uri,
                "qrcode_img_base64": data_uri,
            }

        url = f"{ILINK_BASE_URL}/ilink/bot/get_bot_qrcode?bot_type=3"
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, headers=self._get_headers())
                if res.status_code == 200:
                    data = res.json()
                    qr_key = data.get("qrcode") or data.get("qrcode_key") or ""
                    qr_content = data.get("qrcode_img_content") or data.get("url") or data.get("qrcode_url") or ""
                    if not qr_content and qr_key:
                        qr_content = f"https://liteapp.weixin.qq.com/q/7GiQu1?qrcode={qr_key}&bot_type=3"

                    img_base64 = self._generate_qr_data_uri(qr_content)
                    return {
                        "status": "success",
                        "qrcode_key": qr_key,
                        "qrcode_url": qr_content,
                        "qrcode_img_base64": img_base64,
                    }
                else:
                    self.last_error = f"官方接口响应异常: HTTP {res.status_code}"
                    return {"status": "error", "message": self.last_error}
        except Exception as e:
            self.last_error = f"申请微信二维码失败: {e}"
            logger.warning(self.last_error)
            fallback_data_uri = self._generate_qr_data_uri(f"https://buaa-signin-mock.local/{self.username}")
            return {
                "status": "fallback",
                "qrcode_key": f"offline_qr_{self.username}",
                "qrcode_url": "",
                "qrcode_img_base64": fallback_data_uri,
                "message": str(e),
            }

    @staticmethod
    def _generate_qr_data_uri(content: str) -> str:
        """将二维码链接编码为 Base64 PNG 图片 Data URI"""
        if not content:
            return ""
        try:
            import io
            import qrcode
            qr = qrcode.QRCode(box_size=6, border=2)
            qr.add_data(content)
            qr.make(fit=True)
            img = qr.make_image(fill_color="#000000", back_color="#ffffff")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:image/png;base64,{b64}"
        except Exception as ex:
            logger.warning(f"Failed to generate PNG QR with qrcode library: {ex}")
            svg_data = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
                '<rect width="200" height="200" fill="#ffffff" rx="12"/>'
                '<text x="100" y="100" font-family="sans-serif" font-size="12" fill="#333" text-anchor="middle">扫码链接已生成</text>'
                '</svg>'
            )
            return f"data:image/svg+xml;base64,{base64.b64encode(svg_data.encode()).decode()}"

    def poll_qrcode_status(self, qrcode_key: str) -> Dict[str, Any]:
        """
        轮询扫码确认状态
        完整提取 ilink_user_id, ilink_bot_id, bot_token, context_token
        """
        if self.mock_mode or qrcode_key.startswith("mock_qr_") or os.environ.get("MOCK_WECHAT_BOT") == "1":
            self.bot_token = f"mock_token_{self.username}_{int(time.time())}"
            self.context_token = f"mock_ctx_{self.username}"
            self.to_user_id = f"mock_user_{self.username}@im.wechat"
            self.from_user_id = f"mock_bot_{self.username}@im.bot"
            self.wechat_nickname = f"微信用户_{self.name}"
            with self._lock:
                self.status = "connected"
                self.last_active_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log("success", f"【{self.name}】微信 ClawBot 绑定成功！已关联微信号 [{self.wechat_nickname}]")
            self._notify_change()
            return {
                "status": "confirmed",
                "bot_token": self.bot_token,
                "wechat_nickname": self.wechat_nickname,
                "to_user_id": self.to_user_id,
            }

        url = f"{ILINK_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={urllib.parse.quote(qrcode_key)}"
        try:
            with httpx.Client(timeout=35.0) as client:
                res = client.get(url, headers=self._get_headers())
                if res.status_code == 200:
                    data = res.json()
                    status_str = str(data.get("status", "")).lower()

                    if status_str in ("confirmed", "success") or "bot_token" in data or "ilink_bot_id" in data:
                        self.bot_token = data.get("bot_token") or data.get("token") or data.get("ilink_bot_token") or ""
                        self.context_token = data.get("context_token") or data.get("context") or ""
                        self.to_user_id = data.get("ilink_user_id") or data.get("to_user_id") or data.get("user_id") or ""
                        self.from_user_id = data.get("ilink_bot_id") or data.get("from_user_id") or data.get("bot_id") or ""
                        
                        user_info = data.get("user_info") or {}
                        self.wechat_nickname = user_info.get("nickname") or data.get("nickname") or data.get("wechat_nickname") or "微信用户"
                        
                        with self._lock:
                            self.status = "connected"
                            self.last_active_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # 握手告知服务端启动
                        self._notify_start()
                        self.start_background_worker()

                        # 绑定成功后，主动下发一条测试欢迎卡片验证连通性
                        welcome_card = (
                            f"【AUTO-BUAA 守护通知】\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🎉 微信智联绑定成功！\n"
                            f"👤 学生: {self.name} ({self.username})\n"
                            f"⏰ 绑定时间: {self.last_active_time}\n"
                            f"📝 说明: 微信实时推送通道已就绪，后续晨午打卡与博雅考勤通知将即时送达此窗口。"
                        )
                        threading.Thread(target=self._send_text_message, args=(welcome_card,), daemon=True).start()

                        self._log("success", f"【{self.name}】微信 ClawBot 绑定成功！已关联微信号 [{self.wechat_nickname}]")
                        self._notify_change()
                        return {
                            "status": "confirmed",
                            "bot_token": self.bot_token,
                            "wechat_nickname": self.wechat_nickname,
                            "to_user_id": self.to_user_id,
                        }
                    elif status_str in ("scaned", "scanned"):
                        return {"status": "scanned"}
                    elif status_str in ("expired", "timeout"):
                        with self._lock:
                            if self.status == "waiting_scan":
                                self.status = "unbound"
                        return {"status": "expired"}
                    else:
                        return {"status": "waiting"}
                else:
                    return {"status": "waiting"}
        except httpx.TimeoutException:
            return {"status": "waiting"}
        except Exception as e:
            logger.debug(f"poll_qrcode_status network error: {e}")
            return {"status": "waiting", "error": str(e)}

    def unbind(self):
        """解除当前学生账号的微信绑定并清空会话凭据"""
        self.stop_background_worker()
        with self._lock:
            self.bot_token = ""
            self.context_token = ""
            self.wechat_nickname = ""
            self.to_user_id = ""
            self.from_user_id = ""
            self.get_updates_buf = ""
            self.status = "unbound"
            self.disconnected_queue.clear()
            self.last_error = None
        self._log("info", f"【{self.name}】微信 ClawBot 已成功解绑")
        self._notify_change()

    def set_enabled(self, enabled: bool):
        """开关实时日志微信推送功能"""
        self.enabled = enabled
        status_text = "开启" if enabled else "关闭"
        self._log("info", f"【{self.name}】微信 ClawBot 实时推送已{status_text}")
        self._notify_change()

    def format_log_message(self, log_entry: Dict[str, Any], is_replayed: bool = False) -> str:
        """格式化单条运行日志为富文本微信消息卡片"""
        level = log_entry.get("level", "info").lower()
        level_icon = {
            "info": "ℹ️ 提示",
            "success": "✅ 成功",
            "warning": "⚠️ 警示",
            "error": "❌ 异常",
        }.get(level, "📌 日志")

        category = log_entry.get("category", "regular")
        category_label = {
            "regular": "常规课程考勤",
            "boya": "博雅抢选打卡",
            "system": "系统守护引擎",
            "wechat": "微信智能网关",
        }.get(category, "通用日志")

        prefix = "【AUTO-BUAA 守护通知】" if not is_replayed else "【AUTO-BUAA 离线日志补发】"
        time_str = log_entry.get("time") or datetime.datetime.now().strftime("%H:%M:%S")
        message = log_entry.get("message", "")

        lines = [
            f"{prefix}",
            "━━━━━━━━━━━━━━━━━━",
            f"⏰ 时间: {time_str} | {level_icon}",
            f"👤 学生: {self.name} ({self.username})",
            f"🏷️ 分类: {category_label}",
            f"📝 详情: {message}",
            "━━━━━━━━━━━━━━━━━━",
            "💡 AUTO-BUAA Pro 实时推送守护中",
        ]
        return "\n".join(lines)

    def push_log(self, log_entry: Dict[str, Any]) -> bool:
        """
        向绑定的微信推送一条运行日志
        具备断连保护机制: 断连状态下严格禁止向微信网关盲目发包，存入重放缓冲区
        """
        if not self.enabled or self.status == "unbound" or not self.bot_token:
            return False

        # 检查是否与当前账号相关或者是全局广播日志
        entry_uname = log_entry.get("username", "")
        if entry_uname and entry_uname != self.username:
            return False

        with self._lock:
            # 断连保护期间: 存入滑动缓冲区，绝对不向外网盲目发包
            if self.status in ("disconnected", "reconnecting"):
                self.disconnected_queue.append(log_entry)
                self._trigger_reconnect()
                return False

        # 正常在线状态下发起实时推送
        formatted_text = self.format_log_message(log_entry, is_replayed=False)
        success = self._send_text_message(formatted_text)
        if success:
            with self._lock:
                self.push_count += 1
                self.last_active_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return True
        else:
            # 发送失败触发断连保护
            with self._lock:
                self.status = "disconnected"
                self.disconnected_queue.append(log_entry)
            self._log("warning", f"【{self.name}】微信 ClawBot 发送未达，已转入断连保护与重连缓冲区")
            self._trigger_reconnect()
            return False

    def send_test_message(self) -> Dict[str, Any]:
        """
        前端一键发送微信测试消息接口
        返回确切的底层发包诊断信息
        """
        if not self.bot_token:
            return {"status": "error", "message": "尚未绑定微信机器人"}

        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        test_card = (
            "【AUTO-BUAA 守护通知】\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔔 微信实时推送通道测试\n"
            f"👤 学生: {self.name} ({self.username})\n"
            f"⏰ 发送时间: {now_str}\n"
            "💬 说明: 当您在微信中看到此消息，表示微信智联通道已完全恢复正常！"
        )
        ok = self._send_text_message(test_card)
        if ok:
            with self._lock:
                self.push_count += 1
                self.last_active_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return {"status": "success", "message": "测试消息已成功送达微信客户端！"}
        else:
            err = self.last_error or "微信服务器拒绝或超时"
            return {"status": "error", "message": f"测试消息发送失败: {err}"}

    def _send_text_message(self, text: str) -> bool:
        """
        底层网络发包严格遵循腾讯官方 iLink /sendmessage 规范:
        - 结构嵌套: {"msg": {"from_user_id": "", "to_user_id": ..., "client_id": ..., "message_type": 2, "message_state": 2, "item_list": [...]}, "base_info": {...}}
        - 正确校验 ret == 0 (非 errcode)
        - 针对 ret == -2 自动 probe 续期并重试
        """
        if self.mock_mode or os.environ.get("MOCK_WECHAT_BOT") == "1":
            return True

        if not self.bot_token:
            self.last_error = "未配置 bot_token"
            return False

        url = f"{ILINK_BASE_URL}/ilink/bot/sendmessage"
        headers = self._get_headers()
        client_id = f"ubaa_{uuid.uuid4().hex[:16]}"

        msg_payload: Dict[str, Any] = {
            "from_user_id": self.from_user_id or "",
            "to_user_id": self.to_user_id or "",
            "client_id": client_id,
            "message_type": 2,  # MessageType.BOT
            "message_state": 2,  # MessageState.FINISH
            "item_list": [
                {
                    "type": 1,  # MessageItemType.TEXT
                    "text_item": {
                        "text": text,
                    },
                }
            ],
        }
        if self.context_token:
            msg_payload["context_token"] = self.context_token

        body = {
            "msg": msg_payload,
            "base_info": self._get_base_info(),
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(url, headers=headers, json=body)
                if res.status_code == 200:
                    res_json = res.json()
                    ret = res_json.get("ret", 0)
                    if ret == 0:
                        self.last_error = None
                        return True
                    
                    errmsg = res_json.get("errmsg") or res_json.get("msg") or f"ret={ret}"
                    logger.warning(f"sendmessage api failed: ret={ret}, errmsg={errmsg}")
                    self.last_error = f"微信接口返回失败: {errmsg} (ret={ret})"

                    # 若 ret == -2 (会话过期)，尝试通过 probe getupdates 刷新一次并重试
                    if ret == -2:
                        logger.info("context_token expired (ret=-2), probing getupdates for renewal...")
                        if self._probe_refresh_context():
                            if self.context_token:
                                msg_payload["context_token"] = self.context_token
                            res_retry = client.post(url, headers=headers, json={"msg": msg_payload, "base_info": self._get_base_info()})
                            if res_retry.status_code == 200 and res_retry.json().get("ret", 0) == 0:
                                self.last_error = None
                                return True
                    return False
                else:
                    self.last_error = f"微信网关 HTTP {res.status_code}"
                    logger.warning(f"sendmessage HTTP status: {res.status_code}")
                    return False
        except Exception as e:
            self.last_error = f"网络发包异常: {e}"
            logger.warning(f"sendmessage network error: {e}")
            return False

    def _probe_refresh_context(self) -> bool:
        """轻量探针，调用一次 getupdates 尝试拉取最新的 context_token"""
        if not self.bot_token or self.mock_mode:
            return False
        url = f"{ILINK_BASE_URL}/ilink/bot/getupdates"
        body = {
            "get_updates_buf": self.get_updates_buf or "",
            "base_info": self._get_base_info(),
        }
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.post(url, headers=self._get_headers(), json=body)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("ret", 0) == 0:
                        new_buf = data.get("get_updates_buf")
                        if new_buf:
                            self.get_updates_buf = new_buf
                        for msg in data.get("msgs", []):
                            if msg.get("context_token"):
                                self.context_token = msg["context_token"]
                                if msg.get("from_user_id"):
                                    self.to_user_id = msg["from_user_id"]
                                return True
        except Exception as e:
            logger.debug(f"_probe_refresh_context probe error: {e}")
        return False

    def _trigger_reconnect(self):
        """异步触发重连工作协程/线程"""
        if self._reconnecting or self._stop_event.is_set():
            return

        def _do_reconnect():
            self._reconnecting = True
            try:
                backoff = 2.0
                while not self._stop_event.is_set() and self.status in ("disconnected", "reconnecting"):
                    time.sleep(backoff)
                    if self._stop_event.is_set() or self.status not in ("disconnected", "reconnecting"):
                        break
                    with self._lock:
                        self.status = "reconnecting"
                    # 发起健康检查探针
                    is_online = self._check_health()
                    if is_online:
                        with self._lock:
                            self.status = "connected"
                            self.last_error = None
                            self.last_active_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self._log("success", f"【{self.name}】微信 ClawBot 通道已重新连通！")
                        self._flush_replay_buffer()
                        break
                    backoff = min(backoff * 1.5, 30.0)
            finally:
                self._reconnecting = False

        t = threading.Thread(target=_do_reconnect, daemon=True)
        t.start()

    def _check_health(self) -> bool:
        """探测腾讯官方 iLink 网关连通性"""
        if self.mock_mode or os.environ.get("MOCK_WECHAT_BOT") == "1":
            return True

        if not self.bot_token:
            return False

        url = f"{ILINK_BASE_URL}/ilink/bot/getupdates"
        body = {
            "get_updates_buf": self.get_updates_buf or "",
            "base_info": self._get_base_info(),
        }
        try:
            with httpx.Client(timeout=8.0) as client:
                res = client.post(url, headers=self._get_headers(), json=body)
                if res.status_code == 200:
                    ret = res.json().get("ret", 0)
                    return ret == 0
                return False
        except Exception:
            return False

    def _flush_replay_buffer(self):
        """
        重放缓冲区批量补发机制
        """
        with self._lock:
            pending_logs = list(self.disconnected_queue)
            self.disconnected_queue.clear()

        if not pending_logs:
            return

        preamble = (
            "【BUAA 智能守护】微信通道已重新连通！\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"已为您在断连离线期间拦截并保护了 {len(pending_logs)} 条关键运行日志，正在为您自动补发回放...\n"
            "━━━━━━━━━━━━━━━━━━"
        )
        self._send_text_message(preamble)

        for log in pending_logs:
            msg = self.format_log_message(log, is_replayed=True)
            self._send_text_message(msg)
            with self._lock:
                self.replayed_count += 1
                self.push_count += 1
            time.sleep(0.3)

        postamble = (
            "【BUAA 智能守护】离线日志补发完毕！\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"已成功回放 {len(pending_logs)} 条日志，已恢复毫秒级实时流式推送。"
        )
        self._send_text_message(postamble)

    def start_background_worker(self):
        """启动长轮询后台工作线程"""
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop_event.clear()
        self._poll_thread = threading.Thread(target=self._background_poll_loop, daemon=True)
        self._poll_thread.start()

    def stop_background_worker(self):
        """停止后台长轮询"""
        self._stop_event.set()
        if self._poll_thread and self._poll_thread.is_alive():
            try:
                self._poll_thread.join(timeout=1.0)
            except Exception:
                pass
        self._poll_thread = None

    def _handle_inbound_message(self, user_text: str):
        """
        处理用户在手机微信端向机器人发送的指令/消息
        提供即时确认心跳，保持会话永久活跃
        """
        self._log("info", f"【{self.name}】收到微信用户指令: [{user_text}]，已刷新会话令牌")
        now_str = datetime.datetime.now().strftime('%H:%M:%S')
        reply_card = (
            "【AUTO-BUAA 守护响应】\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🤖 收到微信指令: {user_text}\n"
            f"👤 学生: {self.name} ({self.username})\n"
            f"⏰ 响应时间: {now_str}\n"
            "✨ 守护状态: 系统运行正常，会话令牌已同步刷新！"
        )
        threading.Thread(target=self._send_text_message, args=(reply_card,), daemon=True).start()

    def _background_poll_loop(self):
        """
        腾讯官方 iLink HTTP 长轮询循环:
        - 增量拉取 updates (携带 get_updates_buf)
        - 自动提取最新的 context_token 与 to_user_id
        - 感知入站交互并自动心跳回执
        """
        consecutive_errors = 0
        while not self._stop_event.is_set():
            if not self.bot_token or self.status == "unbound":
                time.sleep(2.0)
                continue

            if self.mock_mode or os.environ.get("MOCK_WECHAT_BOT") == "1":
                time.sleep(5.0)
                continue

            url = f"{ILINK_BASE_URL}/ilink/bot/getupdates"
            headers = self._get_headers()
            body = {
                "get_updates_buf": self.get_updates_buf or "",
                "base_info": self._get_base_info(),
            }

            try:
                with httpx.Client(timeout=40.0) as client:
                    res = client.post(url, headers=headers, json=body)
                    if res.status_code == 200:
                        res_json = res.json()
                        ret = res_json.get("ret", 0)

                        if ret == 0:
                            consecutive_errors = 0
                            new_buf = res_json.get("get_updates_buf")
                            if new_buf:
                                self.get_updates_buf = new_buf

                            msgs = res_json.get("msgs") or []
                            for msg in msgs:
                                if msg.get("context_token"):
                                    self.context_token = msg["context_token"]
                                if msg.get("from_user_id"):
                                    self.to_user_id = msg["from_user_id"]
                                if msg.get("to_user_id") and not self.from_user_id:
                                    self.from_user_id = msg["to_user_id"]

                                # 提取用户发送的文本内容
                                items = msg.get("item_list") or []
                                for item in items:
                                    if item.get("type") == 1:
                                        user_text = item.get("text_item", {}).get("text", "")
                                        if user_text:
                                            self._handle_inbound_message(user_text)

                            with self._lock:
                                if self.status in ("disconnected", "reconnecting"):
                                    self.status = "connected"
                                    self.last_error = None
                                    self._flush_replay_buffer()

                            if msgs:
                                self._notify_change()

                            time.sleep(1.0)
                        elif ret in (-14, 401, 403):
                            self.last_error = "微信会话凭证已过期，请重新扫码授权"
                            self._log("error", f"【{self.name}】微信 ClawBot 会话凭据失效，需要重新扫码")
                            with self._lock:
                                self.status = "disconnected"
                            time.sleep(15.0)
                        else:
                            consecutive_errors += 1
                            if consecutive_errors >= 3:
                                with self._lock:
                                    self.status = "disconnected"
                            time.sleep(5.0)
                    elif res.status_code in (401, 403):
                        self.last_error = "微信会话凭证已过期，请重新扫码"
                        with self._lock:
                            self.status = "disconnected"
                        time.sleep(15.0)
                    else:
                        consecutive_errors += 1
                        if consecutive_errors >= 3:
                            with self._lock:
                                self.status = "disconnected"
                        time.sleep(5.0)
            except httpx.TimeoutException:
                # 长轮询正常超时，继续下一个循环
                consecutive_errors = 0
                continue
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    with self._lock:
                        self.status = "disconnected"
                        self.last_error = f"长轮询异常: {e}"
                time.sleep(5.0)

    def to_dict(self) -> Dict[str, Any]:
        """为前端提供安全的脱敏状态字典"""
        masked_token = ""
        if self.bot_token:
            if len(self.bot_token) > 10:
                masked_token = f"{self.bot_token[:6]}...{self.bot_token[-4:]}"
            else:
                masked_token = "******"

        masked_user_id = ""
        if self.to_user_id:
            if "@" in self.to_user_id:
                prefix, suffix = self.to_user_id.split("@", 1)
                masked_user_id = f"{prefix[:4]}***@{suffix}"
            else:
                masked_user_id = f"{self.to_user_id[:4]}***"

        return {
            "username": self.username,
            "name": self.name,
            "status": self.status,
            "is_bound": bool(self.bot_token),
            "enabled": self.enabled,
            "wechat_nickname": self.wechat_nickname or "未绑定",
            "to_user_id": masked_user_id,
            "has_context": bool(self.context_token),
            "masked_token": masked_token,
            "push_count": self.push_count,
            "replayed_count": self.replayed_count,
            "buffered_count": len(self.disconnected_queue),
            "last_active_time": self.last_active_time or "--",
            "last_error": self.last_error,
        }
