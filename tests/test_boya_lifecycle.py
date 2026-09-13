import unittest
import datetime
from server.app import (
    enrich_selected_courses,
    compute_semester_statistics,
)
from core.boya_scheduler import get_course_category, parse_dt


class TestBoyaLifecycleAndSemesterStats(unittest.TestCase):
    def test_category_normalization_security_health(self):
        # 验证旧称“国家安全”或包含安全/健康字样的课程全面规范化为“安全健康”
        self.assertEqual(get_course_category({"courseKind": "国家安全"}), "安全健康")
        self.assertEqual(get_course_category({"courseKind": "安全健康"}), "安全健康")
        self.assertEqual(get_course_category({"courseKind": "网络空间安全"}), "安全健康")
        self.assertEqual(get_course_category({"courseKind": "心理健康与生命安全"}), "安全健康")
        self.assertEqual(get_course_category({"courseKind": "美育"}), "美育")
        self.assertEqual(get_course_category({"courseKind": "劳育"}), "劳育")
        self.assertEqual(get_course_category({"courseKind": "德育"}), "德育")

    def test_course_lifecycle_ended_and_past(self):
        # 模拟 9.13 19:00 开课的晚间讲座
        past_course = {
            "id": 10099,
            "courseName": "原创场景剧《北京一号》",
            "courseKind": "美育",
            "courseStartDate": "2026-09-13",
            "courseStartTime": "19:00",
            "courseEndDate": "2026-09-13",
            "courseEndTime": "21:00",
            "signStatus": 1,
            "signOutStatus": 1,
            "attendanceStatus": "合格",
            "examStatus": "通过",
            "status": "已结课",
        }
        enriched = enrich_selected_courses([past_course], [])
        self.assertEqual(len(enriched), 1)
        c = enriched[0]

        # 断言结课标记与双过判定
        self.assertTrue(c.get("is_ended"))
        self.assertTrue(c["attendance_status"]["passed"])
        self.assertTrue(c["exam_status"]["passed"])
        self.assertTrue(c.get("final_passed"))

    def test_course_upcoming_and_ongoing(self):
        # 模拟未来开课的课程
        future_date = (datetime.datetime.now() + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
        future_course = {
            "id": 10100,
            "courseName": "前沿人工智能与未来航空科技",
            "courseKind": "德育",
            "courseStartDate": future_date,
            "courseStartTime": "14:00",
            "courseEndDate": future_date,
            "courseEndTime": "16:00",
            "signStatus": 0,
            "signOutStatus": 0,
            "status": "进行中",
        }
        enriched = enrich_selected_courses([future_course], [])
        c = enriched[0]
        self.assertFalse(c.get("is_ended"))
        self.assertIsNone(c["attendance_status"]["passed"])
        self.assertFalse(c.get("final_passed"))

    def test_semester_statistics_calculation(self):
        # 模拟学生修读并通过的课程列表
        selected = [
            # 德育 2 门均通过
            {"courseKind": "德育", "final_passed": True},
            {"courseKind": "德育", "final_passed": True},
            # 劳育 1 门通过，1 门待评定（未通过）
            {"courseKind": "劳育", "final_passed": True},
            {"courseKind": "劳育", "final_passed": False},
            # 美育 1 门通过
            {"courseKind": "美育", "final_passed": True},
            # 安全健康 1 门通过
            {"courseKind": "安全健康", "final_passed": True},
        ]

        stats = compute_semester_statistics(selected)
        self.assertEqual(stats["moral_completed"], 2)
        self.assertEqual(stats["moral_required"], 2)
        self.assertEqual(stats["moral_effective"], 2)

        self.assertEqual(stats["labor_completed"], 1)
        self.assertEqual(stats["labor_required"], 2)
        self.assertEqual(stats["labor_effective"], 1)

        self.assertEqual(stats["art_completed"], 1)
        self.assertEqual(stats["art_required"], 1)
        self.assertEqual(stats["art_effective"], 1)

        self.assertEqual(stats["security_health_completed"], 1)
        self.assertEqual(stats["security_health_required"], 1)
        self.assertEqual(stats["security_health_effective"], 1)

        # 总计达标门数 = 2(德) + 1(劳) + 1(美) + 1(安全健康) = 5 门
        self.assertEqual(stats["semester_passed_total"], 5)
        self.assertEqual(stats["semester_required_total"], 6)
        # 达标率 = 5 / 6 = 83%
        self.assertEqual(stats["semester_compliance_rate"], 83)


if __name__ == "__main__":
    unittest.main()
