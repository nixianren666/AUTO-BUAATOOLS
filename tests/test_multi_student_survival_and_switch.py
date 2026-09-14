import os
os.environ["TESTING"] = "1"

import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from server.app import app, accounts, AccountState, active_username
from core.scheduler import SigninScheduler
from core.boya_scheduler import BoyaScheduler


class TestMultiStudentSurvivalAndSwitch(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        accounts.clear()

    def test_switch_account_returns_cached_data_and_triggers_connect(self):
        """测试学生切换时即刻返回内存缓存课表，杜绝显示'今天没有课'的假空态"""
        # 创建学生 A 和学生 B
        acc_a = AccountState(username="20240001", name="张三", password="pwd_a")
        acc_a.last_classes = [{"courseId": "c1", "courseName": "高等数学", "signStatus": 1}]
        accounts["20240001"] = acc_a

        acc_b = AccountState(username="20240002", name="李四", password="pwd_b")
        acc_b.last_classes = [{"courseId": "c2", "courseName": "大学物理", "signStatus": 0}]
        accounts["20240002"] = acc_b

        # 切换到学生 B
        resp = self.client.post("/api/accounts/switch", json={"username": "20240002"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["active_account"]["username"], "20240002")
        self.assertEqual(len(data["classes"]), 1)
        self.assertEqual(data["classes"][0]["courseName"], "大学物理")

    def test_signin_scheduler_reconnects_unauthenticated_accounts(self):
        """测试 SigninScheduler 在后台巡检时，即使账号会话丢失，也能通过 reconnect 回调无缝拉起重连"""
        reconnected = []

        async def fake_reconnect(acc):
            reconnected.append(acc.username)
            acc.client.user_id = "uid_123"
            acc.client.session_id = "sid_456"
            return True

        acc = AccountState(username="20240003", name="王五", password="secret_pwd")
        # 初始未鉴权
        acc.client.user_id = None
        acc.client.session_id = None
        acc.auto_checkin = True
        accounts["20240003"] = acc

        acc.client.get_today_classes = AsyncMock(return_value=[])

        scheduler = SigninScheduler(
            get_active_accounts=lambda: [{"username": acc.username, "name": acc.name, "client": acc.client, "account": acc}],
            reconnect_account=fake_reconnect,
        )

        asyncio.run(scheduler._check_and_sign_all())
        self.assertIn("20240003", reconnected, "后台巡检守护必须为未鉴权但有密码的学生触发自动重连")

    def test_boya_scheduler_credentials_renew(self):
        """测试 BoyaScheduler 在 Token 过期时能自动利用凭据重新换取 Token"""
        acc = AccountState(username="20240004", name="赵六", password="boya_password")
        acc.boya_client.acquire_token = MagicMock(return_value=None)
        acc.boya_client.login_with_credentials = MagicMock(return_value="new_mock_token")

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda *a, **kw: None)
        renewed = scheduler._renew_session(acc)
        self.assertTrue(renewed, "利用 saved password 必须能成功重新恢复 Boya Session")
        acc.boya_client.login_with_credentials.assert_called_once_with("20240004", "boya_password")


if __name__ == "__main__":
    unittest.main()
