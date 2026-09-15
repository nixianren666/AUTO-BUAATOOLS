# -*- coding: utf-8 -*-
"""
WeChat ClawBot 实时日志推送通信底座 (基于腾讯官方微信 iLink 智联协议)
- 协议服务端基地址: https://ilinkai.weixin.qq.com
- 核心功能特性:
  1. 多学生独立绑定隔离 (Independent per-student bot instance & credentials)
  2. 实时全景总日志流式卡片推送 (Total system & student execution logs)
  3. 智能断连识别与消息外发保护 (Disconnect detection & zero flood protection)
  4. 离线日志滑动重放缓冲区 (Disconnect replay buffer with seamless batch replay)
  5. 纯原生轻量化实现 (Zero heavy external npm/pip dependencies)
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
from typing import Any, Callable, Deque, Dict, List, Optional
import urllib.parse

import httpx

logger = logging.getLogger("wechat_clawbot")

ILINK_BASE_URL = "https://ilinkai.weixin.qq.com"


def _generate_wechat_uin() -> str:
    """生成随机微信 X-WECHAT-UIN 头 (Base64 编码的 32 位无符号整数)"""
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
        self.poll_cursor: str = ""

        # 线程与锁控制
        self._lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._reconnecting = False

        # 若初始已存在 token，则启动长轮询保活
        if self.bot_token and not self.mock_mode:
            self.start_background_worker()

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

    def get_binding_qrcode(self) -> Dict[str, Any]:
        """
        向腾讯官方 iLink 网关申请绑定二维码
        返回结构: { status, qrcode_key, qrcode_url, qrcode_img_base64 }
        """
        with self._lock:
            self.status = "waiting_scan"

        if self.mock_mode or os.environ.get("MOCK_WECHAT_BOT") == "1":
            mock_key = f"mock_qr_{self.username}_{int(time.time())}"
            # 生成精美的 SVG 模拟二维码数据 URI
            svg_data = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220" viewBox="0 0 220 220">'
                f'<rect width="220" height="220" fill="#ffffff" rx="16"/>'
                f'<rect x="20" y="20" width="60" height="60" fill="#07c160" rx="8"/>'
                f'<rect x="30" y="30" width="40" height="40" fill="#ffffff" rx="4"/>'
                f'<rect x="40" y="40" width="20" height="20" fill="#07c160" rx="2"/>'
                f'<rect x="140" y="20" width="60" height="60" fill="#07c160" rx="8"/>'
                f'<rect x="150" y="30" width="40" height="40" fill="#ffffff" rx="4"/>'
                f'<rect x="160" y="40" width="20" height="20" fill="#07c160" rx="2"/>'
                f'<rect x="20" y="140" width="60" height="60" fill="#07c160" rx="8"/>'
                f'<rect x="30" y="150" width="40" height="40" fill="#ffffff" rx="4"/>'
                f'<rect x="40" y="160" width="20" height="20" fill="#07c160" rx="2"/>'
                f'<rect x="95" y="95" width="30" height="30" fill="#07c160" rx="6"/>'
                f'<text x="110" y="185" font-family="system-ui,sans-serif" font-size="11" fill="#666" text-anchor="middle">微信扫一扫绑定</text>'
                f'</svg>'
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
                res = client.get(url, headers={"User-Agent": "BUAA-Signin-ClawBot/1.3.1"})
                if res.status_code == 200:
                    data = res.json()
                    qr_key = data.get("qrcode") or data.get("qrcode_key") or ""
                    qr_content = data.get("qrcode_img_content") or data.get("url") or data.get("qrcode_url") or ""
                    if not qr_content and qr_key:
                        qr_content = f"https://liteapp.weixin.qq.com/q/7GiQu1?qrcode={qr_key}&bot_type=3"

                    # 使用 qrcode 库将官方授权链接渲染为本地高清晰 PNG Base64 Data URI
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
            # 优雅降级返回模拟二维码，避免本地离线测试阻断
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
        """将任意文本链接动态编码为标准 Base64 PNG 图片 Data URI"""
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
            # 降级生成纯文本占位 SVG
            svg_data = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">'
                f'<rect width="200" height="200" fill="#ffffff" rx="12"/>'
                f'<text x="100" y="100" font-family="sans-serif" font-size="12" fill="#333" text-anchor="middle">扫码链接已生成</text>'
                f'</svg>'
            )
            return f"data:image/svg+xml;base64,{base64.b64encode(svg_data.encode()).decode()}"

    def poll_qrcode_status(self, qrcode_key: str) -> Dict[str, Any]:
        """
        轮询扫码确认状态 (采用长轮询机制与异常兜底)
        返回结构: { status: "waiting" | "scanned" | "confirmed" | "expired", ... }
        """
        if self.mock_mode or qrcode_key.startswith("mock_qr_") or os.environ.get("MOCK_WECHAT_BOT") == "1":
            # 模拟扫码确认流程
            self.bot_token = f"mock_token_{self.username}_{int(time.time())}"
            self.context_token = f"mock_ctx_{self.username}"
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
            }

        url = f"{ILINK_BASE_URL}/ilink/bot/get_qrcode_status?qrcode={urllib.parse.quote(qrcode_key)}"
        try:
            with httpx.Client(timeout=35.0) as client:
                res = client.get(url, headers={"User-Agent": "BUAA-Signin-ClawBot/1.3.1"})
                if res.status_code == 200:
                    data = res.json()
                    status_str = str(data.get("status", "")).lower()
                    ret_code = data.get("ret", 0)

                    if status_str in ("confirmed", "success") or "bot_token" in data:
                        self.bot_token = data.get("bot_token") or data.get("token") or data.get("ilink_bot_token") or ""
                        self.context_token = data.get("context_token") or data.get("context") or ""
                        user_info = data.get("user_info") or {}
                        self.wechat_nickname = user_info.get("nickname") or data.get("nickname") or data.get("wechat_nickname") or "微信用户"
                        with self._lock:
                            self.status = "connected"
                            self.last_active_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        self.start_background_worker()
                        self._log("success", f"【{self.name}】微信 ClawBot 绑定成功！已关联微信号 [{self.wechat_nickname}]")
                        self._notify_change()
                        return {
                            "status": "confirmed",
                            "bot_token": self.bot_token,
                            "wechat_nickname": self.wechat_nickname,
                        }
                    elif status_str in ("scaned", "scanned"):
                        return {"status": "scanned"}
                    elif status_str in ("expired", "timeout"):
                        with self._lock:
                            if self.status == "waiting_scan":
                                self.status = "unbound"
                        return {"status": "expired"}
                    elif status_str == "wait" or ret_code == 0:
                        return {"status": "waiting"}
                    else:
                        return {"status": "waiting"}
                else:
                    return {"status": "waiting"}
        except httpx.TimeoutException:
            # 官方 HTTP 长轮询超时为正常心跳保持，返回 waiting 等待下次探测
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
            f"━━━━━━━━━━━━━━━━━━",
            f"⏰ 时间: {time_str} | {level_icon}",
            f"👤 学生: {self.name} ({self.username})",
            f"🏷️ 分类: {category_label}",
            f"📝 详情: {message}",
            f"━━━━━━━━━━━━━━━━━━",
            f"💡 AUTO-BUAA Pro 实时推送守护中",
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
                self.last_error = "微信网关通信超时或已断开"
            self._log("warning", f"【{self.name}】微信 ClawBot 网络连接中断，已转入断连保护与重连缓冲区")
            self._trigger_reconnect()
            return False

    def _send_text_message(self, text: str) -> bool:
        """底层网络发包调用腾讯官方 iLink /sendmessage 接口"""
        if self.mock_mode or os.environ.get("MOCK_WECHAT_BOT") == "1":
            return True

        if not self.bot_token:
            return False

        url = f"{ILINK_BASE_URL}/ilink/bot/sendmessage"
        headers = {
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.bot_token}",
            "X-WECHAT-UIN": _generate_wechat_uin(),
            "Content-Type": "application/json",
            "User-Agent": "BUAA-Signin-ClawBot/1.3.1",
        }
        body = {
            "msg_type": 1,  # 文本消息
            "content": {"text": text},
        }
        if self.context_token:
            body["context_token"] = self.context_token

        try:
            with httpx.Client(timeout=12.0) as client:
                res = client.post(url, headers=headers, json=body)
                if res.status_code == 200:
                    res_json = res.json()
                    errcode = res_json.get("errcode", 0)
                    if errcode == 0:
                        return True
                    else:
                        logger.warning(f"sendmessage api errcode: {errcode} - {res_json.get('errmsg')}")
                        return False
                else:
                    logger.warning(f"sendmessage HTTP status: {res.status_code}")
                    return False
        except Exception as e:
            logger.warning(f"sendmessage network error: {e}")
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
                        # 触发离线日志重放缓冲回放
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
        headers = {
            "AuthorizationType": "ilink_bot_token",
            "Authorization": f"Bearer {self.bot_token}",
            "X-WECHAT-UIN": _generate_wechat_uin(),
            "Content-Type": "application/json",
            "User-Agent": "BUAA-Signin-ClawBot/1.3.1",
        }
        body = {"offset": self.poll_cursor or "", "timeout": 5}
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.post(url, headers=headers, json=body)
                return res.status_code == 200
        except Exception:
            return False

    def _flush_replay_buffer(self):
        """
        重放缓冲区批量补发机制:
        1. 首先发送一条专属重连提示卡片；
        2. 批量将离线期间积压的日志依序补发；
        3. 发送补发完毕通知，恢复实时流式推送。
        """
        with self._lock:
            pending_logs = list(self.disconnected_queue)
            self.disconnected_queue.clear()

        if not pending_logs:
            return

        # 1. 发送重连及补发前置通知
        preamble = (
            f"【BUAA 智能守护】微信通道已重新连通！\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"已为您在断连离线期间拦截并保护了 {len(pending_logs)} 条关键运行日志，正在为您自动补发回放...\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        self._send_text_message(preamble)

        # 2. 依次补发积压日志
        for log in pending_logs:
            msg = self.format_log_message(log, is_replayed=True)
            self._send_text_message(msg)
            with self._lock:
                self.replayed_count += 1
                self.push_count += 1
            time.sleep(0.3)  # 微扰防频控

        # 3. 发送补发完成提示
        postamble = (
            f"【BUAA 智能守护】离线日志补发完毕！\n"
            f"━━━━━━━━━━━━━━━━━━\n"
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

    def _background_poll_loop(self):
        """长轮询循环，维持与微信智联网关的会话保活并感知通道健康"""
        consecutive_errors = 0
        while not self._stop_event.is_set():
            if not self.bot_token or self.status == "unbound":
                time.sleep(2.0)
                continue

            if self.mock_mode or os.environ.get("MOCK_WECHAT_BOT") == "1":
                time.sleep(5.0)
                continue

            url = f"{ILINK_BASE_URL}/ilink/bot/getupdates"
            headers = {
                "AuthorizationType": "ilink_bot_token",
                "Authorization": f"Bearer {self.bot_token}",
                "X-WECHAT-UIN": _generate_wechat_uin(),
                "Content-Type": "application/json",
                "User-Agent": "BUAA-Signin-ClawBot/1.3.1",
            }
            body = {"offset": self.poll_cursor or "", "timeout": 35}

            try:
                with httpx.Client(timeout=45.0) as client:
                    res = client.post(url, headers=headers, json=body)
                    if res.status_code == 200:
                        consecutive_errors = 0
                        data = res.json()
                        self.poll_cursor = data.get("cursor") or self.poll_cursor
                        updates = data.get("updates", [])
                        # 如果收到任何新消息，更新 context_token
                        for upd in updates:
                            ctx = upd.get("context_token")
                            if ctx:
                                self.context_token = ctx

                        with self._lock:
                            if self.status in ("disconnected", "reconnecting"):
                                self.status = "connected"
                                self.last_error = None
                                self._flush_replay_buffer()
                    elif res.status_code in (401, 403):
                        # Token 失效
                        self.last_error = "微信会话凭证已过期，请重新扫码授权"
                        self._log("error", f"【{self.name}】微信 ClawBot 会话凭据失效，需要重新扫码")
                        with self._lock:
                            self.status = "disconnected"
                        time.sleep(10.0)
                    else:
                        consecutive_errors += 1
                        if consecutive_errors >= 2:
                            with self._lock:
                                self.status = "disconnected"
                        time.sleep(5.0)
            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors >= 2:
                    with self._lock:
                        self.status = "disconnected"
                        self.last_error = f"长轮询异常: {e}"
                time.sleep(5.0)

    def to_dict(self) -> Dict[str, Any]:
        """为前端提供安全的脱敏状态字典"""
        # 脱敏展示 bot_token (仅显示前6位与后4位)
        masked_token = ""
        if self.bot_token:
            if len(self.bot_token) > 10:
                masked_token = f"{self.bot_token[:6]}...{self.bot_token[-4:]}"
            else:
                masked_token = "******"

        return {
            "username": self.username,
            "name": self.name,
            "status": self.status,
            "is_bound": bool(self.bot_token),
            "enabled": self.enabled,
            "wechat_nickname": self.wechat_nickname or "未绑定",
            "masked_token": masked_token,
            "push_count": self.push_count,
            "replayed_count": self.replayed_count,
            "buffered_count": len(self.disconnected_queue),
            "last_active_time": self.last_active_time or "--",
            "last_error": self.last_error,
        }
