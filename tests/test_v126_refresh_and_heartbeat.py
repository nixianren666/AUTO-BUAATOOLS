import unittest
import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock
from core.scheduler import SigninScheduler
from core.boya_scheduler import BoyaScheduler


class TestV126RefreshAndHeartbeat(unittest.TestCase):
    def test_post_signin_immediate_schedule_refresh(self):
        """测试常规签到成功后立即向教务端重新获取最新课表并刷新内存与时间戳"""
        now = datetime.datetime.now()
        future_time_str = (now + datetime.timedelta(minutes=5)).strftime("%H:%M")
        refreshed_classes = [
            {"courseSchedId": "101", "courseName": "航空航天概论", "signStatus": 1, "classBeginTime": future_time_str}
        ]
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.perform_signin = AsyncMock(return_value=(True, "签到成功"))
        mock_client.get_today_classes = AsyncMock(side_effect=[
            [{"courseSchedId": "101", "courseName": "航空航天概论", "signStatus": 0, "classBeginTime": future_time_str}],
            refreshed_classes
        ])

        acc_obj = MagicMock()
        acc_obj.last_classes = [
            {"courseSchedId": "101", "courseName": "航空航天概论", "signStatus": 0, "classBeginTime": future_time_str}
        ]
        acc_obj.last_refresh_time = "00:00:00"

        active_account = {
            "username": "20240001",
            "name": "张三",
            "client": mock_client,
            "account": acc_obj,
        }

        scheduler = SigninScheduler(get_active_accounts=lambda: [active_account])
        # 将计划时间设为过去，立即触发签到
        scheduler.planned_targets[("20240001", "101")] = datetime.datetime.now() - datetime.timedelta(seconds=5)

        # 触发巡检
        asyncio.run(scheduler._check_and_sign_all())

        # 验证 perform_signin 被调用
        mock_client.perform_signin.assert_called_once_with("101")
        # 验证在签到成功后立即触发了 get_today_classes 重新拉取
        self.assertGreaterEqual(mock_client.get_today_classes.call_count, 2)
        # 验证内存课表与时间戳已更新
        self.assertEqual(acc_obj.last_classes[0]["signStatus"], 1)
        self.assertNotEqual(acc_obj.last_refresh_time, "00:00:00")

    def test_boya_heartbeat_log_deduplication(self):
        """测试博雅课池心跳日志每个账号仅输出首条，后续后台巡检不再刷屏"""
        logs = []
        def log_cb(level, msg, **kwargs):
            logs.append((level, msg))

        mock_boya_client = MagicMock()
        mock_boya_client.is_authenticated.return_value = True
        mock_boya_client.query_chosen_courses.return_value = []
        mock_boya_client.query_courses.return_value = [
            {
                "id": 2001,
                "courseName": "博雅美术课",
                "courseCategory": "美育",
                "coursePosition": "学院路校区",
                "courseSelectStartDate": "2026-09-01 00:00:00",
                "courseSelectEndDate": "2026-09-30 00:00:00",
                "courseStartDate": "2026-09-20",
                "courseStartTime": "14:00",
                "courseEndDate": "2026-09-20",
                "courseEndTime": "16:00",
                "courseCurrentCount": 10,
                "courseMaxCount": 50,
                "signConfig": '{"signPointList":[{"lat":39.9,"lng":116.3}]}',
            }
        ]

        acc = MagicMock()
        acc.username = "20240001"
        acc.name = "李四"
        acc.boya_auto_select = True
        acc.boya_auto_sign = False
        acc.boya_client = mock_boya_client
        acc.boya_all_courses = mock_boya_client.query_courses.return_value
        acc.boya_selected_courses = []

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=log_cb)

        # 第 1 次 tick：初次开启，必须输出一条总览日志
        scheduler.tick()
        pool_logs_1 = [msg for lvl, msg in logs if "博雅抢课守护中：全校课池共" in msg]
        self.assertEqual(len(pool_logs_1), 1, "初次开启必须输出 1 条课池总览态势日志")

        # 模拟 10 分钟后的第 2 次与第 3 次 tick
        scheduler.tick()
        scheduler.tick()
        pool_logs_subsequent = [msg for lvl, msg in logs if "博雅抢课守护中：全校课池共" in msg]
        self.assertEqual(len(pool_logs_subsequent), 1, "后续周期性巡检严禁重复刷屏，依然只保留首条日志")


if __name__ == "__main__":
    unittest.main()
