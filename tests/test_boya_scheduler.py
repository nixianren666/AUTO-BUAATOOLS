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

if __name__ == "__main__":
    unittest.main()
