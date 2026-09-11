import os
os.environ["TESTING"] = "1"
"""
集成与单元测试：多账号并发管理、10分钟随机签到窗口、3次重试及专属日志
"""

import unittest
import asyncio
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from server.app import app, accounts, AccountState, active_username
from core.scheduler import SigninScheduler


class DummyClient:
    def __init__(self, should_succeed=True, fail_times=0):
        self.should_succeed = should_succeed
        self.fail_times = fail_times
        self.call_count = 0

    def is_authenticated(self):
        return True

    async def get_today_classes(self):
        now = datetime.now()
        # 构造一个 5 分钟后开始的课程 (处于 [start - 10m, start] 窗口内)
        start_time = (now + timedelta(minutes=5)).strftime("%H:%M")
        end_time = (now + timedelta(minutes=50)).strftime("%H:%M")
        return [
            {
                "courseId": "test_c1",
                "courseName": "测试计算机课程",
                "classBeginTime": start_time,
                "classEndTime": end_time,
                "signStatus": 0,
            }
        ]

    async def perform_signin(self, course_id):
        self.call_count += 1
        if self.call_count <= self.fail_times:
            return False, "模拟签到临时失败"
        return self.should_succeed, "模拟签到成功"

    async def close(self):
        pass


class TestMultiAccount(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        accounts.clear()

    def test_accounts_crud_and_switch(self):
        # 1. 初始账号列表应为空
        resp = self.client.get("/api/accounts")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["accounts"]), 0)

        # 2. 模拟注入两个学生账号
        acc1 = AccountState(
            username="23370001",
            name="张三",
            password="",
            mode="webvpn",
            remember=True,
            auto_checkin=True,
        )
        acc2 = AccountState(
            username="23370002",
            name="李四",
            password="",
            mode="direct",
            remember=True,
            auto_checkin=False,
        )
        accounts["23370001"] = acc1
        accounts["23370002"] = acc2

        # 3. 获取账号卡列表
        resp = self.client.get("/api/accounts")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_count"], 2)
        self.assertEqual(len(data["accounts"]), 2)

        # 4. 切换主视图到李四
        resp = self.client.post("/api/accounts/switch", json={"username": "23370002"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["active_account"]["username"], "23370002")

        # 5. 切换自动打卡开关
        resp = self.client.post("/api/accounts/toggle_auto", json={"username": "23370002", "enabled": True})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["auto_checkin"])

        # 6. 移除学生账号张三
        resp = self.client.post("/api/accounts/remove", json={"username": "23370001"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("23370001", accounts)
        self.assertIn("23370002", accounts)

    def test_per_account_logs_filtering(self):
        # 添加日志
        from server.app import add_log
        add_log("info", "张三登录成功", username="23370001", user_name="张三")
        add_log("info", "李四登录成功", username="23370002", user_name="李四")

        # 获取全部日志
        resp = self.client.get("/api/logs")
        self.assertEqual(resp.status_code, 200)
        all_logs = resp.json()["logs"]
        self.assertTrue(any("张三登录成功" in l["message"] for l in all_logs))
        self.assertTrue(any("李四登录成功" in l["message"] for l in all_logs))

        # 仅获取张三的日志
        resp = self.client.get("/api/logs?username=23370001")
        self.assertEqual(resp.status_code, 200)
        zhang_logs = resp.json()["logs"]
        for l in zhang_logs:
            self.assertEqual(l["username"], "23370001")

        # 仅获取李四的日志
        resp = self.client.get("/api/logs?username=23370002")
        self.assertEqual(resp.status_code, 200)
        li_logs = resp.json()["logs"]
        for l in li_logs:
            self.assertEqual(l["username"], "23370002")

    def test_scheduler_10_min_window_and_3_retries(self):
        logs_received = []

        def on_log(level, msg, username=None, user_name=None):
            logs_received.append((level, msg, username, user_name))

        dummy = DummyClient(should_succeed=True, fail_times=2)  # 前2次失败，第3次成功

        def get_accounts():
            return [{"username": "test_stu", "name": "测试生", "client": dummy}]

        scheduler = SigninScheduler(get_active_accounts=get_accounts, on_event_log=on_log)

        loop = asyncio.new_event_loop()
        try:
            key = ("test_stu", "test_c1")

            # 轮次 1: 规划打卡时间点
            loop.run_until_complete(scheduler._check_and_sign_all())
            self.assertIn(key, scheduler.planned_targets)

            # 模拟到达计划打卡时间 -> 触发第 1 次尝试 (失败)
            scheduler.planned_targets[key] = datetime.now() - timedelta(seconds=1)
            loop.run_until_complete(scheduler._check_and_sign_all())
            self.assertEqual(dummy.call_count, 1)

            # 模拟到达第 2 次重试时间 -> 触发第 2 次尝试 (失败)
            scheduler.planned_targets[key] = datetime.now() - timedelta(seconds=1)
            loop.run_until_complete(scheduler._check_and_sign_all())
            self.assertEqual(dummy.call_count, 2)

            # 模拟到达第 3 次重试时间 -> 触发第 3 次尝试 (成功)
            scheduler.planned_targets[key] = datetime.now() - timedelta(seconds=1)
            loop.run_until_complete(scheduler._check_and_sign_all())
            self.assertEqual(dummy.call_count, 3)

            self.assertIn(key, scheduler.signed_courses)
            self.assertTrue(any("签到成功" in msg for _, msg, _, _ in logs_received))
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
