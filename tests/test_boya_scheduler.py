import unittest
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
        self.boya_client = DummyBoyaClient()

class DummyBoyaClient:
    def __init__(self):
        self.selected_ids = []
        self.signed_courses = []
        self.fail_on_select = False
        self.select_call_count = 0

    def is_authenticated(self):
        return True

    def select_course(self, cid):
        self.select_call_count += 1
        if self.fail_on_select:
            from core.boya_client import BoyaApiError
            raise BoyaApiError("1002", "课程容量已满或选课冲突")
        self.selected_ids.append(cid)
        return {"status": "0", "msg": "选课成功"}

    def query_chosen_courses(self):
        return []

    def sign_course(self, cid, lat, lng, sign_type=1):
        self.signed_courses.append((cid, lat, lng, sign_type))
        return {"status": "0", "msg": "打卡成功"}

class TestBoyaScheduler(unittest.TestCase):
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
        now = datetime.now()
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

        self.assertTrue(is_auto_select_candidate(valid_course, now, campus="北京"))

        # Category "其他方面" excluded
        other_course = dict(valid_course, courseKind="其他方面")
        self.assertFalse(is_auto_select_candidate(other_course, now, campus="北京"))

        # Capacity full excluded
        full_course = dict(valid_course, courseCurrentCount=50, courseMaxCount=50)
        self.assertFalse(is_auto_select_candidate(full_course, now, campus="北京"))

    def test_scheduler_circuit_breaker(self):
        logs = []
        acc = DummyBoyaAccount()
        acc.boya_client.fail_on_select = True

        now = datetime.now()
        start = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
        acc.boya_all_courses = [{
            "id": 9999,
            "courseName": "热门讲座",
            "coursePosition": "学院路校区晨兴音乐厅",
            "courseKind": "博雅美育",
            "courseCurrentCount": 0,
            "courseMaxCount": 100,
            "courseSelectStartDate": start,
            "courseSelectEndDate": end,
            "courseSignConfig": '{"signPointList":[{"lat":39.9,"lng":116.3}]}',
        }]

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda *args, **kwargs: logs.append(args))

        # First 3 ticks should attempt and fail 3 times
        scheduler.tick()
        scheduler.tick()
        scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 3)
        self.assertEqual(scheduler.fail_counters.get((acc.username, 9999)), 3)

        # 4th tick should be blocked by circuit breaker
        scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 3)

    def test_duplicate_course_avoidance(self):
        acc = DummyBoyaAccount()
        now = datetime.now()
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
        now = datetime.now()
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
        
        # 第 1 轮 tick: 发起一次请求，服务端提示已报名
        scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 1)
        self.assertIn((acc.username, "10018"), scheduler.chosen_history)

        # 第 2 轮 tick: 应被 chosen_history 拦截，绝不再发起第二次请求
        scheduler.tick()
        self.assertEqual(acc.boya_client.select_call_count, 1)

    def test_self_selected_course_auto_sign(self):
        acc = DummyBoyaAccount()
        now = datetime.now()
        start = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        end = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

        # 模拟学生自己在手机端选的课（queryChosenCourse 仅返回基础信息，缺少 signPointList）
        acc.boya_selected_courses = [{
            "id": 5555,
            "courseName": "中国古典诗词意境鉴赏",
            "courseSignConfig": "{}",
            "signStatus": 0,
        }]

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

        now = datetime.now()
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

        scheduler = BoyaScheduler(get_accounts_func=lambda: [acc], add_log_func=lambda level, msg, **k: logs.append(msg))
        scheduler.tick()

        # 严正断言：必须仅抢选支持线上打卡的 10020，绝不抢选 10018！
        self.assertIn(10020, acc.boya_client.selected_ids, "支持线上自主打卡的课程必须成功抢选")
        self.assertNotIn(10018, acc.boya_client.selected_ids, "现场刷卡考勤课程绝不可被自动代抢，防止旷课违约！")
        
        # 验证心跳日志明确指出安全排除了非线上打卡课程
        heartbeat_logs = [l for l in logs if "博雅抢课守护中" in l]
        self.assertTrue(any("非线上打卡安全排除" in l for l in heartbeat_logs), "守护日志必须透明汇报非线上打卡课程安全排除态势")

    def test_offline_course_opt_in_guard(self):
        """验证高级模式显式允许线下课程时的回退路径"""
        acc = DummyBoyaAccount()
        acc.boya_auto_select = True
        acc.boya_require_auto_sign = False
        acc.boya_allow_offline = True

        now = datetime.now()
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

        self.assertIn(10018, acc.boya_client.selected_ids, "用户显式开启线下选课时方允许代抢")

if __name__ == "__main__":
    unittest.main()
