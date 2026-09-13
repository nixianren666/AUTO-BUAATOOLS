import unittest
from fastapi.testclient import TestClient
from server.app import app, accounts, AccountState

class TestBoyaCategoriesAndFilters(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        accounts.clear()

    def test_demo_courses_strictly_have_four_categories(self):
        valid_cats = {"美育", "劳育", "安全健康", "德育"}
        res = self.client.get("/api/boya/courses")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        courses = data.get("courses", [])
        self.assertGreater(len(courses), 0)

        categories_found = set()
        for c in courses:
            cat = c.get("courseKind") or c.get("courseType")
            self.assertIn(cat, valid_cats, f"Course {c.get('courseName')} has invalid category {cat}")
            categories_found.add(cat)

        self.assertEqual(categories_found, valid_cats)

    def test_autonomous_sign_detection_in_pool(self):
        res = self.client.get("/api/boya/courses")
        courses = res.json().get("courses", [])
        auto_courses = [c for c in courses if "signPointList" in str(c.get("courseSignConfig", "")) and len(c.get("courseSignConfig", "")) > 10]
        manual_courses = [c for c in courses if not c.get("courseSignConfig")]

        self.assertGreater(len(auto_courses), 0)
        self.assertGreater(len(manual_courses), 0)

    def test_demo_selected_and_statistics(self):
        res_sel = self.client.get("/api/boya/selected")
        self.assertEqual(res_sel.status_code, 200)
        sel = res_sel.json().get("selected", [])
        self.assertGreater(len(sel), 0)

        res_stats = self.client.get("/api/boya/statistics")
        self.assertEqual(res_stats.status_code, 200)
        stats = res_stats.json().get("statistics", {})
        self.assertIn("art_courses_count", stats)
        self.assertIn("labor_courses_count", stats)
        self.assertIn("security_courses_count", stats)
        self.assertIn("moral_courses_count", stats)

    def test_checkin_and_delete_account_compatibility(self):
        acc = AccountState(username="23379999", name="测试学生", password="", mode="direct", auto_checkin=True)
        accounts["23379999"] = acc

        res_del = self.client.delete("/api/accounts/23379999")
        self.assertEqual(res_del.status_code, 200)
        self.assertNotIn("23379999", accounts)

if __name__ == "__main__":
    unittest.main()
