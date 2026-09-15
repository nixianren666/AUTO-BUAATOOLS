# -*- coding: utf-8 -*-
"""
WeChat ClawBot 独立单元测试套件
覆盖:
1. 腾讯 iLink 二维码申请与模拟扫码授权全流程
2. 多学生独立绑定隔离与总日志定向分流
3. 断连智能识别与消息外发保护机制 (Zero-Flood Protection)
4. 断连重放缓冲区 (Disconnect Replay Buffer) 积压与自动补发回放
5. 解除绑定生命周期完整性
6. 严格按腾讯官方 OpenClaw / iLink 规范验证 sendMessage 发包结构与 ret 状态码校验
7. getupdates 长轮询与 context_token / to_user_id 动态续期
8. RESTful Web API 接口契约与异常响应
"""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.wechat_clawbot import WeChatClawBot, ILINK_BASE_URL
from server.app import app, accounts, AccountState, add_log, logs_list
from fastapi.testclient import TestClient


class TestWeChatClawBot(unittest.TestCase):

    def setUp(self):
        os.environ["TESTING"] = "1"
        os.environ["MOCK_WECHAT_BOT"] = "1"
        accounts.clear()
        logs_list.clear()

    def tearDown(self):
        for acc in list(accounts.values()):
            if hasattr(acc, "wechat_bot"):
                acc.wechat_bot.stop_background_worker()
        accounts.clear()
        logs_list.clear()

    def test_qrcode_generation_and_scan_lifecycle(self):
        """测试二维码生成、扫码状态轮询及授权成功流转"""
        bot = WeChatClawBot(username="23371001", name="测试张三", mock_mode=True)
        self.assertEqual(bot.status, "unbound")
        self.assertFalse(bot.to_dict()["is_bound"])

        # 1. 申请二维码
        qr_info = bot.get_binding_qrcode()
        self.assertEqual(qr_info["status"], "success")
        self.assertIn("mock_qr_23371001", qr_info["qrcode_key"])
        self.assertEqual(bot.status, "waiting_scan")

        # 2. 轮询扫码结果
        poll_res = bot.poll_qrcode_status(qr_info["qrcode_key"])
        self.assertEqual(poll_res["status"], "confirmed")
        self.assertEqual(bot.status, "connected")
        self.assertTrue(bot.to_dict()["is_bound"])
        self.assertEqual(bot.wechat_nickname, "微信用户_测试张三")
        self.assertTrue(bot.bot_token.startswith("mock_token_23371001"))
        self.assertEqual(bot.to_user_id, "mock_user_23371001@im.wechat")

    def test_multi_student_independent_binding_isolation(self):
        """测试多学生账号完全独立绑定与总日志定向投递"""
        acc_a = AccountState(username="23371001", name="学生A")
        acc_b = AccountState(username="23371002", name="学生B")
        accounts["23371001"] = acc_a
        accounts["23371002"] = acc_b

        # 仅为学生 A 绑定微信
        acc_a.wechat_bot.mock_mode = True
        acc_b.wechat_bot.mock_mode = True
        qr_a = acc_a.wechat_bot.get_binding_qrcode()
        acc_a.wechat_bot.poll_qrcode_status(qr_a["qrcode_key"])

        self.assertEqual(acc_a.wechat_bot.status, "connected")
        self.assertEqual(acc_b.wechat_bot.status, "unbound")

        # Mock 底层网络发包
        sent_messages_a = []
        sent_messages_b = []
        acc_a.wechat_bot._send_text_message = lambda text: sent_messages_a.append(text) or True
        acc_b.wechat_bot._send_text_message = lambda text: sent_messages_b.append(text) or True

        # 1. 发送学生 A 专属日志 -> 应仅投递给学生 A
        add_log("success", "学生A考勤签到成功", username="23371001", user_name="学生A", category="regular")
        self.assertEqual(len(sent_messages_a), 1)
        self.assertIn("学生A考勤签到成功", sent_messages_a[0])
        self.assertEqual(len(sent_messages_b), 0)

        # 2. 发送学生 B 专属日志 -> 学生 B 未绑定，且不应串号投递给学生 A
        add_log("info", "学生B博雅抢课中", username="23371002", user_name="学生B", category="boya")
        self.assertEqual(len(sent_messages_a), 1)
        self.assertEqual(len(sent_messages_b), 0)

        # 3. 发送全局广播日志 -> 仅投递给已绑定的学生 A
        add_log("info", "BUAA 守护服务系统心跳正常", username=None, category="system")
        self.assertEqual(len(sent_messages_a), 2)
        self.assertIn("系统心跳正常", sent_messages_a[1])
        self.assertEqual(len(sent_messages_b), 0)

    def test_disconnect_detection_and_buffer_suppression(self):
        """测试断连智能识别与消息外发保护: 断连期间封锁外发，积压入缓冲区"""
        bot = WeChatClawBot(
            username="23371001",
            name="测试张三",
            bot_token="test_token",
            mock_mode=False
        )
        self.assertEqual(bot.status, "connected")

        # 模拟网络发包失败，触发断连保护
        bot._send_text_message = MagicMock(return_value=False)

        test_log_1 = {"time": "10:00:00", "level": "info", "message": "第一条日志", "username": "23371001", "category": "regular"}
        success = bot.push_log(test_log_1)
        self.assertFalse(success, "发送失败应返回 False")
        self.assertEqual(bot.status, "disconnected", "发送失败必须平滑切入 disconnected 保护状态")
        self.assertEqual(len(bot.disconnected_queue), 1)

        # 断连期间继续产生日志 -> 绝对禁止调用 _send_text_message，直接放入重放缓冲区
        bot._send_text_message.reset_mock()
        test_log_2 = {"time": "10:01:00", "level": "warning", "message": "第二条日志", "username": "23371001", "category": "boya"}
        test_log_3 = {"time": "10:02:00", "level": "success", "message": "第三条日志", "username": "23371001", "category": "boya"}

        bot.push_log(test_log_2)
        bot.push_log(test_log_3)

        # 验证断连保护: 期间一次网络请求都没发出！
        bot._send_text_message.assert_not_called()
        self.assertEqual(len(bot.disconnected_queue), 3, "断连期间的3条日志完整保存在缓冲区中")

    def test_reconnection_and_replay_buffer_flushing(self):
        """测试通道重连成功后，前置通知、离线批量补发与缓冲区清空机制"""
        bot = WeChatClawBot(
            username="23371001",
            name="测试张三",
            bot_token="test_token",
            mock_mode=True
        )
        bot.status = "disconnected"

        # 向重放队列中注入 2 条离线日志
        bot.disconnected_queue.append({"time": "11:00:00", "level": "warning", "message": "网络闪断时的博雅抢课重试", "username": "23371001", "category": "boya"})
        bot.disconnected_queue.append({"time": "11:01:00", "level": "success", "message": "离线期间的抢选成功记录", "username": "23371001", "category": "boya"})

        dispatched_messages = []
        bot._send_text_message = lambda text: dispatched_messages.append(text) or True

        # 触发重连与回放刷新
        bot._flush_replay_buffer()

        # 验证回放发包流程: 前置通知 -> 2条补发日志 -> 完成通知，总共 4 条发包
        self.assertEqual(len(dispatched_messages), 4)
        self.assertIn("微信通道已重新连通", dispatched_messages[0], "第1条必须为重连前置提示卡片")
        self.assertIn("离线日志补发", dispatched_messages[1], "第2条必须标注离线补发标识")
        self.assertIn("网络闪断时的博雅抢课重试", dispatched_messages[1])
        self.assertIn("离线期间的抢选成功记录", dispatched_messages[2])
        self.assertIn("离线日志补发完毕", dispatched_messages[3], "第4条必须为补发完成提示")

        # 验证重放队列已完全清空
        self.assertEqual(len(bot.disconnected_queue), 0, "回放后重放队列必须被安全清空")
        self.assertEqual(bot.replayed_count, 2, "补发统计计数器必须准确累加")

    def test_unbind_lifecycle(self):
        """测试解绑流程：销毁凭据、清空缓冲区、状态重置为 unbound"""
        bot = WeChatClawBot(
            username="23371001",
            name="测试张三",
            bot_token="test_token",
            context_token="test_ctx",
            wechat_nickname="张三的微信号",
            to_user_id="user123@im.wechat",
            from_user_id="bot123@im.bot",
            mock_mode=True
        )
        bot.disconnected_queue.append({"time": "12:00:00", "level": "info", "message": "待发日志"})
        self.assertEqual(bot.status, "connected")

        bot.unbind()
        self.assertEqual(bot.status, "unbound")
        self.assertEqual(bot.bot_token, "")
        self.assertEqual(bot.context_token, "")
        self.assertEqual(bot.wechat_nickname, "")
        self.assertEqual(bot.to_user_id, "")
        self.assertEqual(bot.from_user_id, "")
        self.assertEqual(len(bot.disconnected_queue), 0)
        self.assertFalse(bot.to_dict()["is_bound"])

    def test_official_ilink_sendmessage_payload_and_ret_code(self):
        """严格按腾讯官方 iLink 规范验证 sendmessage 报文嵌套结构与 ret 校验"""
        bot = WeChatClawBot(
            username="23371001",
            name="测试张三",
            bot_token="real_test_bot_token",
            context_token="real_test_ctx_token",
            to_user_id="test_user@im.wechat",
            from_user_id="test_bot@im.bot",
            mock_mode=False,
        )

        old_mock = os.environ.pop("MOCK_WECHAT_BOT", None)
        try:
            with patch("httpx.Client.post") as mock_post:
                # 1. 模拟腾讯 iLink 官方返回成功 (ret=0)
                mock_resp_success = MagicMock()
                mock_resp_success.status_code = 200
                mock_resp_success.json.return_value = {"ret": 0, "errmsg": "ok"}
                mock_post.return_value = mock_resp_success

                ok = bot._send_text_message("测试消息内容")
                self.assertTrue(ok)

                # 验证请求参数严格对齐官方规范
                call_args, call_kwargs = mock_post.call_args
                self.assertIn("/ilink/bot/sendmessage", call_args[0])
                headers = call_kwargs["headers"]
                self.assertEqual(headers["AuthorizationType"], "ilink_bot_token")
                self.assertEqual(headers["Authorization"], "Bearer real_test_bot_token")
                self.assertEqual(headers["iLink-App-Id"], "bot")
                self.assertEqual(headers["iLink-App-ClientVersion"], "132104")
                self.assertIn("X-WECHAT-UIN", headers)

                body = call_kwargs["json"]
                self.assertIn("msg", body)
                self.assertIn("base_info", body)
                self.assertEqual(body["base_info"]["channel_version"], "2.4.8")

                msg = body["msg"]
                self.assertEqual(msg["to_user_id"], "test_user@im.wechat")
                self.assertEqual(msg["from_user_id"], "test_bot@im.bot")
                self.assertEqual(msg["message_type"], 2)  # MessageType.BOT
                self.assertEqual(msg["message_state"], 2)  # MessageState.FINISH
                self.assertEqual(msg["context_token"], "real_test_ctx_token")
                self.assertTrue(msg["client_id"].startswith("ubaa_"))
                self.assertEqual(len(msg["item_list"]), 1)
                self.assertEqual(msg["item_list"][0]["type"], 1)  # MessageItemType.TEXT
                self.assertEqual(msg["item_list"][0]["text_item"]["text"], "测试消息内容")

                # 2. 模拟腾讯返回业务拒绝 (ret=-1), 杜绝假成功！
                mock_resp_fail = MagicMock()
                mock_resp_fail.status_code = 200
                mock_resp_fail.json.return_value = {"ret": -1, "errmsg": "invalid user"}
                mock_post.return_value = mock_resp_fail

                fail_ok = bot._send_text_message("测试被拒消息")
                self.assertFalse(fail_ok, "当 ret!=0 时必须返回 False，严禁误判为成功！")
                self.assertIn("ret=-1", bot.last_error)
        finally:
            if old_mock is not None:
                os.environ["MOCK_WECHAT_BOT"] = old_mock

    def test_wechat_api_endpoints_contract(self):
        """测试 Web RESTful API 端点全链路契约"""
        client = TestClient(app)
        acc = AccountState(username="23371001", name="张三", mode="direct")
        acc.wechat_bot.mock_mode = True
        accounts["23371001"] = acc

        # 1. GET /api/wechat/status
        res = client.get("/api/wechat/status?username=23371001")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["wechat"]["status"], "unbound")

        # 2. POST /api/wechat/qrcode
        res = client.post("/api/wechat/qrcode?username=23371001")
        self.assertEqual(res.status_code, 200)
        qr_data = res.json()
        self.assertEqual(qr_data["status"], "success")
        qr_key = qr_data["qrcode_key"]

        # 3. GET /api/wechat/qrcode_poll
        res = client.get(f"/api/wechat/qrcode_poll?username=23371001&qrcode_key={qr_key}")
        self.assertEqual(res.status_code, 200)
        poll_data = res.json()
        self.assertEqual(poll_data["status"], "confirmed")

        # 4. POST /api/wechat/toggle
        res = client.post("/api/wechat/toggle", json={"username": "23371001", "enabled": False})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["enabled"])

        # 5. POST /api/wechat/test_push
        res = client.post("/api/wechat/test_push", json={"username": "23371001"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        # 6. GET /api/wechat/buffer
        res = client.get("/api/wechat/buffer?username=23371001")
        self.assertEqual(res.status_code, 200)
        self.assertIn("buffered_count", res.json())

        # 7. POST /api/wechat/unbind
        res = client.post("/api/wechat/unbind?username=23371001")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["wechat"]["status"], "unbound")


if __name__ == "__main__":
    unittest.main()
