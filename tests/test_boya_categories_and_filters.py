import unittest
from fastapi.testclient import TestClient
from server.app import app, accounts, AccountState

class TestBoyaCategoriesAndFilters(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        csrf = self.client.get("/api/session").json()["csrf"]
        self.client.headers["X-BUAA-CSRF"] = csrf
        accounts.clear()

    def test_unauthenticated_pool_does_not_invent_school_courses(self):
        response=self.client.get("/api/boya/courses")
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data["status"],"unauthenticated")
        self.assertTrue(data["stale"])
        self.assertFalse(data["is_demo"])
        self.assertEqual(data["courses"],[])

    def test_autonomous_configuration_requires_real_points_and_complete_windows(self):
        from server.app import enrich_pool
        from tests.test_v127_boya import fixture_course
        valid=fixture_course()
        invalid={**valid,"id":9002,"courseSignConfig":{"signPointList":[{}]}}
        onsite={**valid,"id":9003,"courseSignConfig":None}
        flags=[row["autonomous_config_valid"] for row in enrich_pool([valid,invalid,onsite])]
        self.assertEqual(flags,[True,False,False])

    def test_unauthenticated_selected_and_statistics_do_not_invent_progress(self):
        data=self.client.get("/api/boya/selected").json()
        self.assertTrue(data["stale"])
        self.assertEqual(data["selected"],[])
        stats=self.client.get("/api/boya/statistics").json()["statistics"]
        self.assertFalse(stats["semester_known"])
        self.assertIsNone(stats["valid_count"])
        self.assertEqual(stats["semester_passed_total"],0)

    def test_checkin_and_delete_account_compatibility(self):
        acc = AccountState(username="23379999", name="测试学生", password="", mode="direct", auto_checkin=True)
        accounts["23379999"] = acc

        res_del = self.client.delete("/api/accounts/23379999")
        self.assertEqual(res_del.status_code, 200)
        self.assertNotIn("23379999", accounts)

if __name__ == "__main__":
    unittest.main()
