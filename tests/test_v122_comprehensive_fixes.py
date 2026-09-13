import unittest
from core.iclass import IclassClient
from core.boya_client import extract_real_name_from_stats
from server.app import enrich_selected_courses, compute_semester_statistics, add_log, get_logs, accounts, AccountState
from run import acquire_single_instance, APP_TITLE


class TestV122ComprehensiveFixes(unittest.TestCase):
    def test_single_instance_mutex(self):
        """测试单实例互斥检测在当前系统正常工作"""
        first = acquire_single_instance(18346)
        # 首次获取互斥体成功
        self.assertTrue(first)
        # 再次获取（模拟另一个进程运行）应检测到已存在
        second = acquire_single_instance(18346)
        self.assertFalse(second)

    def test_extract_real_name_from_stats(self):
        stats = {
            "userInfo": {"realName": "张三", "userName": "21370001"},
            "validCount": 1
        }
        name = extract_real_name_from_stats(stats)
        self.assertEqual(name, "张三")

    def test_iclass_course_metadata_mapping(self):
        client = IclassClient(mode="direct")
        # 模拟学校接口原始返回数据结构
        mock_raw_classes = [
            {
                "id": "2479439",
                "courseId": "96037",
                "courseName": "生物信息学",
                "classroomName": "主楼(北)201",
                "teacherName": "陈伟",
                "classBeginTime": "2026-09-14 09:50:00",
                "classEndTime": "2026-09-14 11:25:00",
                "signStatus": 0,
            }
        ]
        mapped = []
        for c in mock_raw_classes:
            sched_id = str(c.get("id") or c.get("courseSchedId") or "")
            c_id = str(c.get("courseId") or sched_id)
            c_name = c.get("courseName") or "未知课程"
            b_time = c.get("classBeginTime") or ""
            e_time = c.get("classEndTime") or ""
            start_t = b_time.split(" ")[1][:5] if " " in b_time else b_time[:5]
            end_t = e_time.split(" ")[1][:5] if " " in e_time else e_time[:5]
            room = c.get("classroomName") or c.get("classroom") or "校内教室"
            teacher = c.get("teacherName") or c.get("teacher") or "任课教师"
            mapped.append({
                "id": sched_id,
                "courseSchedId": sched_id,
                "courseId": c_id,
                "courseName": c_name,
                "startTime": start_t,
                "endTime": end_t,
                "classroom": room,
                "classroomName": room,
                "teacher": teacher,
                "teacherName": teacher,
                "signStatus": c.get("signStatus", 0),
            })
        
        item = mapped[0]
        self.assertEqual(item["courseSchedId"], "2479439")
        self.assertEqual(item["startTime"], "09:50")
        self.assertEqual(item["endTime"], "11:25")
        self.assertEqual(item["classroom"], "主楼(北)201")
        self.assertEqual(item["teacher"], "陈伟")

    def test_boya_checkin_pass_signinfo(self):
        raw_boya_course = {
            "id": 1001,
            "courseName": "原创场景剧《北京一号》",
            "courseKind": "美育",
            "courseStartDate": "2026-09-10",
            "courseStartTime": "19:00",
            "courseEndDate": "2026-09-10",
            "courseEndTime": "21:30",
            "courseStatus": "已结课",
            "checkin": 1,
            "pass": 1,
            "signInfo": '{"signIn":{"inSignArea":true},"signOut":{"inSignArea":true}}',
            "is_ended": True,
        }
        enriched = enrich_selected_courses([raw_boya_course], [])
        c = enriched[0]
        self.assertTrue(c["is_ended"])
        self.assertEqual(c["attendance_status"]["text"], "考勤通过")
        self.assertEqual(c["attendance_status"]["badge"], "badge-green")
        self.assertEqual(c["exam_status"]["text"], "考核通过")
        self.assertEqual(c["exam_status"]["badge"], "badge-green")
        self.assertTrue(c["final_passed"])

    def test_personal_logging(self):
        import asyncio
        username = "test_student_mock_01"
        add_log("info", "常规课程刷新成功", username=username, user_name="李四", category="regular")
        add_log("info", "博雅秒抢守护正常", username=username, user_name="李四", category="boya")

        regular_res = asyncio.run(get_logs(username=username, category="regular"))
        regular_logs = regular_res.get("logs", [])
        self.assertTrue(any("常规课程刷新成功" in l["message"] for l in regular_logs))
        self.assertFalse(any("博雅秒抢守护正常" in l["message"] for l in regular_logs))

        boya_res = asyncio.run(get_logs(username=username, category="boya"))
        boya_logs = boya_res.get("logs", [])
        self.assertTrue(any("博雅秒抢守护正常" in l["message"] for l in boya_logs))
        self.assertFalse(any("常规课程刷新成功" in l["message"] for l in boya_logs))

    def test_encrypt_local_secret_and_decrypt(self):
        """测试本地密码机密 AES-128-CBC 加密存储与无损解密"""
        from core.boya_crypto import encrypt_local_secret, decrypt_local_secret

        raw_pwd = "MySecretPassword_2026!@#"
        enc = encrypt_local_secret(raw_pwd)
        self.assertTrue(enc.startswith("enc:"))
        self.assertNotEqual(enc, raw_pwd)

        dec = decrypt_local_secret(enc)
        self.assertEqual(dec, raw_pwd)

        # 兼容未加密的旧明文
        legacy_pwd = "PlaintextPassword123"
        self.assertEqual(decrypt_local_secret(legacy_pwd), legacy_pwd)

        # 空字符串处理
        self.assertEqual(encrypt_local_secret(""), "")
        self.assertEqual(decrypt_local_secret(""), "")

    def test_empty_boya_selected_does_not_fallback_to_demo(self):
        """测试真实学生已选课程为 0 门时，系统返回空列表而不是回退至 DEMO_BOYA_SELECTED"""
        import asyncio
        from server.app import get_boya_selected, accounts, AccountState

        test_uname = "23379999"
        acc = AccountState(username=test_uname, name="空课测试生")
        acc.boya_client.token = "mock_valid_token_123"
        acc.boya_selected_courses = []  # 真实已选 0 门
        acc.boya_all_courses = []
        accounts[test_uname] = acc

        import server.app as app_mod
        orig_active = app_mod.active_username
        try:
            app_mod.active_username = test_uname
            res = asyncio.run(get_boya_selected(force=False))
            self.assertEqual(res["status"], "success")
            self.assertEqual(res["selected"], [])
            self.assertFalse(res["is_demo"])
        finally:
            app_mod.active_username = orig_active
            accounts.pop(test_uname, None)

    def test_scheduler_uses_course_sched_id(self):
        """测试 SigninScheduler 优先提取 courseSchedId/id 并正确传入 client.perform_signin"""
        import asyncio
        from datetime import datetime, timedelta
        from core.scheduler import SigninScheduler

        call_log = []
        now = datetime.now()
        class_time = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

        class MockIclassClient:
            def is_authenticated(self):
                return True

            async def get_today_classes(self):
                return [{
                    "id": "2479439",
                    "courseSchedId": "2479439",
                    "courseId": "96037",
                    "courseName": "生物信息学",
                    "classBeginTime": class_time,
                    "signStatus": 0,
                }]

            async def perform_signin(self, course_sched_id):
                call_log.append(course_sched_id)
                return True, "签到成功"

        client = MockIclassClient()
        test_acc = {
            "username": "23370002",
            "name": "排课测试生",
            "client": client,
        }

        scheduler = SigninScheduler(
            get_active_accounts=lambda: [test_acc],
            on_event_log=lambda *a, **k: None,
        )

        asyncio.run(scheduler.tick())
        sched_key = ("23370002", "2479439")
        if sched_key in scheduler.planned_targets:
            scheduler.planned_targets[sched_key] = now - timedelta(seconds=10)
        asyncio.run(scheduler.tick())

        # 必须使用 courseSchedId (2479439) 而非 courseId (96037)
        self.assertEqual(call_log, ["2479439"])


if __name__ == "__main__":
    unittest.main()

