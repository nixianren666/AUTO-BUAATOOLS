from core.domain import now as china_now
import unittest
from unittest.mock import patch
from core import operations
from boya_fixture import FixtureBoyaClient, FixtureCrypto, valid_course
from datetime import datetime, timedelta
from core.boya_scheduler import (
    course_matches_campus,
    has_autonomous_sign,
    parse_sign_config,
    random_point_in_radius,
    is_auto_select_candidate,
    BoyaScheduler,
)

class DummyBoyaAccount:
    def __init__(self, username="23370001", name="测试学生", campus="北京"):
        self.username = username
        self.name = name
        self.campus = campus
        self.boya_auto_select = True
        self.boya_auto_sign = True
        self.boya_all_courses = []
        self.boya_selected_courses = []
        self.boya_client = FixtureBoyaClient(self)
        self.removed = False
        self.boya_health = {}

class TestBoyaScheduler(unittest.TestCase):
    def test_target_filled_is_deduplicated_normal_state_but_real_failures_still_warn(self):
        from core.boya_client import BoyaApiError, BoyaSessionExpired
        acc=DummyBoyaAccount();acc.boya_all_courses=[valid_course(10020,"德育"),valid_course(10021,"德育")]
        acc.boya_client.semester_info={"semesterStartDate":"2026-08-31","semesterEndDate":"2027-01-03"}
        logs=[];scheduler=BoyaScheduler(lambda:[acc],lambda level,message,**kw:logs.append((level,message,kw)))
        scheduler.clock=lambda:datetime(2026,10,29,9)
        with patch('core.boya_scheduler.is_auto_select_candidate',return_value=True),patch('core.boya_actions.perform_boya_action',side_effect=BoyaApiError('target_filled','本类别已完成或已有足够预约')):
            scheduler._check_auto_select(acc,scheduler.clock());scheduler._check_auto_select(acc,scheduler.clock())
        self.assertEqual(len(logs),1);self.assertEqual(logs[0][0],'info')
        self.assertNotIn('BoyaError',logs[0][1]);self.assertEqual(logs[0][2]['username'],acc.username)
        self.assertIs(logs[0][2]['notify'],False)
        with patch('core.boya_scheduler.is_auto_select_candidate',return_value=True),patch('core.boya_actions.perform_boya_action',side_effect=BoyaApiError('user_declined','用户已放弃本门课程')):
            scheduler._check_auto_select(acc,scheduler.clock());scheduler._check_auto_select(acc,scheduler.clock())
        self.assertEqual(len(logs),3);self.assertTrue(all(x[0]=='info' and x[2]['notify'] is False for x in logs))
        for failure in (BoyaApiError('unavailable','名额已满'),BoyaSessionExpired('需要重新认证')):
            with patch('core.boya_scheduler.is_auto_select_candidate',return_value=True),patch('core.boya_actions.perform_boya_action',side_effect=failure):
                scheduler._check_auto_select(acc,scheduler.clock())
        self.assertTrue(all(level=='warning' for level,_,_ in logs[3:]));self.assertEqual(len(logs),7)

    def setUp(self):
        ledger = operations.OperationLedger()
        self.ledger_patch = patch("core.operations.ledger", ledger)
        self.ledger_patch.start()
        self.crypto_patch = patch("core.boya_client.BykcCrypto", FixtureCrypto)
        self.crypto_patch.start()
        self.addCleanup(ledger.db.close)
        self.addCleanup(self.ledger_patch.stop)
        self.addCleanup(self.crypto_patch.stop)

    def test_campus_matching(self):
        beijing_course = {"courseName": "航天简史", "coursePosition": "学院路三号楼"}
        hangzhou_course = {"courseName": "人工智能导论", "coursePosition": "杭州中法航空学院101"}

        self.assertTrue(course_matches_campus(beijing_course, "北京"))
        self.assertFalse(course_matches_campus(hangzhou_course, "北京"))

        self.assertTrue(course_matches_campus(hangzhou_course, "杭州"))
        self.assertFalse(course_matches_campus(beijing_course, "杭州"))

    def test_autonomous_sign_detection(self):
        normal_course = {
            "courseSignConfig": '{"signPointList":[{"signLat":39.9822,"signLng":116.3475,"signRadius":20}]}'
        }
        no_sign_course = {
            "courseSignConfig": '{"signPointList":[]}'
        }
        manual_paper_course = {
            "courseSignConfig": ""
        }

        self.assertTrue(has_autonomous_sign(normal_course))
        self.assertFalse(has_autonomous_sign(no_sign_course))
        self.assertFalse(has_autonomous_sign(manual_paper_course))

    def test_random_point_in_radius(self):
        lat0, lng0 = 39.9822, 116.3475
        radius = 50.0
        for _ in range(100):
            lat, lng = random_point_in_radius(lat0, lng0, radius)
            dlat_m = abs(lat - lat0) * 111320.0
            dlng_m = abs(lng - lng0) * 111320.0 * 0.766
            dist = (dlat_m**2 + dlng_m**2)**0.5
            # Must strictly be within radius * 0.65 <= 33m
            self.assertLessEqual(dist, radius * 0.7)

    def test_auto_select_candidate(self):
        now = china_now()
        start = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

        valid_course = {
            "id": 1001,
            "courseName": "航空航天与未来探索",
            "coursePosition": "沙河校区J1-101",
            "courseKind": "博雅科技",
            "courseCurrentCount": 10,
            "courseMaxCount": 50,
            "courseSelectStartDate": start,
            "courseSelectEndDate": end,
            "courseSignConfig": '{"signPointList":[{"lat":39.9,"lng":116.3}]}',
        }

        from boya_fixture import valid_course as make_valid
        valid_course = make_valid(1001, current=now)
        self.assertTrue(is_auto_select_candidate(valid_course, now, campus="北京"))

        # Category "其他方面" excluded
        other_course = dict(valid_course, courseKind="其他方面")
        self.assertFalse(is_auto_select_candidate(other_course, now, campus="北京"))

        # Capacity full excluded
        full_course = dict(valid_course, courseCurrentCount=50, courseMaxCount=50)
        self.assertFalse(is_auto_select_candidate(full_course, now, campus="北京"))

    def test_scheduler_circuit_breaker_and_new_capacity_epoch(self):
        acc = DummyBoyaAccount()
        self.addCleanup(acc.boya_client.close)
        acc.boya_client.fail_on_select = True
        acc.boya_auto_sign = False
        acc.boya_all_courses = [valid_course(9999)]
        scheduler = BoyaScheduler(lambda: [acc], lambda *args, **kwargs: None, ordinary_courses=lambda *args: [])
        import time
        base = time.time()
        for index in range(4):
            with patch("core.boya_client.time.time", return_value=base+61*index):
                scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 3)
        acc.boya_all_courses[0]["courseCurrentCount"] = 1
        acc.boya_client.fail_on_select = False
        with patch("core.boya_client.time.time", return_value=base+300):
            scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 4)
        self.assertIn(9999, acc.boya_client.selected_ids)

    def test_duplicate_course_avoidance(self):
        acc = DummyBoyaAccount()
        now = china_now()
        start = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

        # 候选课池有一门课 ID 10017
        acc.boya_all_courses = [{
            "id": 10017,
            "courseName": "航空航天概论讲座",
            "coursePosition": "沙河校区J1-101",
            "courseKind": "博雅科技",
            "courseCurrentCount": 10,
            "courseMaxCount": 100,
            "courseSelectStartDate": start,
            "courseSelectEndDate": end,
            "courseSignConfig": '{"signPointList":[{"lat":39.9,"lng":116.3}]}',
        }]

        # 学生已选课程列表中已有这门课 (比如 courseId 为 10017)
        acc.boya_selected_courses = [{
            "id": 88312,
            "courseId": 10017,
            "courseName": "航空航天概论讲座",
            "chosenCourseId": 88312,
        }]

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda *a, **k: None)
        scheduler.tick()

        # 必须跳过，绝不发起抢课请求
        self.assertEqual(acc.boya_client.select_call_count, 0)

    def test_server_already_enrolled_stops_subsequent_attempts(self):
        acc = DummyBoyaAccount()
        now = china_now()
        start = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

        acc.boya_all_courses = [{
            "id": 10018,
            "courseName": "中国传统书画鉴赏",
            "coursePosition": "学院路校区三号楼",
            "courseKind": "博雅美育",
            "courseCurrentCount": 10,
            "courseMaxCount": 100,
            "courseSelectStartDate": start,
            "courseSelectEndDate": end,
            "courseSignConfig": '{"signPointList":[{"lat":39.9,"lng":116.3}]}',
        }]
        acc.boya_selected_courses = []

        # 模拟服务端返回：已报名过该课程，请不要重复报名
        def mock_select(cid):
            acc.boya_client.select_call_count += 1
            from core.boya_client import BoyaApiError
            raise BoyaApiError("1002", "已报名过该课程，请不要重复报名")

        acc.boya_client.select_course = mock_select

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda *a, **k: None)

        acc.boya_auto_sign = False
        acc.boya_all_courses = [valid_course(10018)]
        scheduler.ordinary_courses = lambda *args: []
        # 第 1 轮 tick: 发起一次请求，服务端提示已报名
        scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 1)
        self.assertIn(10018, acc.boya_pending_courses)

        # 第 2 轮 tick: 应被 chosen_history 拦截，绝不再发起第二次请求
        scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 1)

    def test_self_selected_course_auto_sign(self):
        acc = DummyBoyaAccount()
        now = china_now()
        start = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

        # 模拟学生自己在手机端选的课（queryChosenCourse 仅返回基础信息，缺少 signPointList）
        acc.boya_selected_courses = [{
            "id": 5555,
            "courseName": "中国古典诗词意境鉴赏",
            "courseSignConfig": "{}",
            "signStatus": 0,
        }]

        acc.boya_auto_select = False
        # 课池中有该课程的完整定位与签到时间配置
        acc.boya_all_courses = [{
            "id": 5555,
            "courseName": "中国古典诗词意境鉴赏",
            "courseSignConfig": f'{{"signPointList":[{{"lat":39.9822,"lng":116.3475,"radius":30}}],"signStartDate":"{start}","signEndDate":"{end}"}}',
        }]

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda *a, **k: None)
        scheduler.tick()

        # 验证：守护引擎应当成功跨表检索补齐经纬度，并成功触发自动签到！
        signed_cids = [x[0] for x in acc.boya_client.signed_courses]
        self.assertIn(5555, signed_cids)
        self.assertEqual(acc.boya_client.signed_courses[0][3], 1)  # sign_type = 1 签到

    def test_strict_offline_course_auto_select_guard(self):
        """核心安全性铁律验证：严禁抢选不支持线上自主打卡的线下刷卡/核验考勤课程"""
        logs = []
        acc = DummyBoyaAccount()
        acc.boya_auto_select = True
        acc.boya_require_auto_sign = True
        acc.boya_allow_offline = False

        now = china_now()
        start = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

        # 课池中包含一门现场考勤沙龙和一门支持线上打卡的德育课
        acc.boya_all_courses = [
            {
                "id": 10018,
                "courseName": "正念沙龙——正念融入生活",
                "coursePosition": "学院路知行北楼313",
                "courseKind": "安全健康",
                "courseCurrentCount": 0,
                "courseMaxCount": 20,
                "courseSelectStartDate": start,
                "courseSelectEndDate": end,
                "courseSignConfig": '{"signPointList":[]}',  # 现场刷卡考勤
            },
            {
                "id": 10020,
                "courseName": "大国重器与空天精神",
                "coursePosition": "沙河J1-101",
                "courseKind": "德育",
                "courseCurrentCount": 0,
                "courseMaxCount": 100,
                "courseSelectStartDate": start,
                "courseSelectEndDate": end,
                "courseSignConfig": '{"signPointList":[{"lat":39.98,"lng":116.34}]}',  # 线上自主打卡
            }
        ]

        acc.boya_all_courses[1] = valid_course(10020, "德育")
        acc.boya_auto_sign = False
        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda level, msg, **k: logs.append(msg), ordinary_courses=lambda *args: [])
        scheduler.tick()

        # 严正断言：必须仅抢选支持线上打卡的 10020，绝不抢选 10018！
        self.assertIn(10020, acc.boya_client.selected_ids, "支持线上自主打卡的课程必须成功抢选")
        self.assertNotIn(10018, acc.boya_client.selected_ids, "现场刷卡考勤课程绝不可被自动代抢，防止旷课违约！")

        # 验证心跳日志明确指出安全排除了非线上打卡课程
        heartbeat_logs = [l for l in logs if "博雅抢课守护中" in l]
        self.assertTrue(any("非线上打卡安全排除" in l for l in heartbeat_logs), "守护日志必须透明汇报非线上打卡课程安全排除态势")

    def test_offline_course_always_excluded(self):
        """验证无论何种配置，现场刷卡考勤课程一律被安全引擎硬性排除，绝不代抢"""
        acc = DummyBoyaAccount()
        acc.boya_auto_select = True

        now = china_now()
        start = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")

        acc.boya_all_courses = [
            {
                "id": 10018,
                "courseName": "正念沙龙——正念融入生活",
                "coursePosition": "学院路知行北楼313",
                "courseKind": "安全健康",
                "courseCurrentCount": 0,
                "courseMaxCount": 20,
                "courseSelectStartDate": start,
                "courseSelectEndDate": end,
                "courseSignConfig": "",  # 现场刷卡考勤
            }
        ]

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda *a, **k: None)
        scheduler.tick()

        self.assertNotIn(10018, acc.boya_client.selected_ids, "现场考勤课程必须无条件硬性排除")

if __name__ == "__main__":
    unittest.main()
