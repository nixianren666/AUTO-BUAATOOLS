import os
os.environ["TESTING"] = "1"
import unittest
from fastapi.testclient import TestClient
from server.app import app, accounts, AccountState

class TestBoyaApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        accounts.clear()

        acc = AccountState(
            username="23370001",
            name="张三",
            password="",
            mode="direct",
            auto_checkin=True,
            boya_auto_select=True,
            boya_auto_sign=True,
            campus="北京",
        )
        acc.boya_client.token = "mock_valid_boya_token"
        acc.boya_all_courses = [
            {"id": 8801, "courseName": "航空科学前沿", "courseKind": "博雅科技", "coursePosition": "沙河J3"}
        ]
        acc.boya_selected_courses = [
            {"id": 8802, "courseName": "航天艺术与美学", "courseKind": "博雅美育", "chosenCourseId": 9902}
        ]
        acc.boya_statistics = {
            "totalCount": 6,
            "totalCredit": 3.0,
            "requiredCredit": 4.0,
        }
        accounts["23370001"] = acc

    def test_boya_status_and_courses_api(self):
        # 1. Test Boya Status
        res = self.client.get("/api/boya/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["boya_auto_select"])
        self.assertEqual(data["campus"], "北京")
        self.assertEqual(data["courses_count"], 1)
        self.assertEqual(data["selected_count"], 1)

        # 2. Test Boya Selected Courses API
        res = self.client.get("/api/boya/selected")
        self.assertEqual(res.status_code, 200)
        sel = res.json()["selected"]
        self.assertEqual(len(sel), 1)
        self.assertEqual(sel[0]["courseName"], "航天艺术与美学")

        # 3. Test Boya Statistics API
        res = self.client.get("/api/boya/statistics")
        self.assertEqual(res.status_code, 200)
        stats = res.json()["statistics"]
        self.assertEqual(stats["totalCredit"], 3.0)

    def test_boya_toggle_auto_api(self):
        res = self.client.post("/api/boya/toggle_auto", json={
            "username": "23370001",
            "auto_select": False,
            "auto_sign": True,
            "campus": "杭州",
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["boya_auto_select"])
        self.assertTrue(data["boya_auto_sign"])
        self.assertEqual(data["campus"], "杭州")

        acc = accounts["23370001"]
        self.assertFalse(acc.boya_auto_select)
        self.assertEqual(acc.campus, "杭州")

    def test_separated_logs_api(self):
        from server.app import add_log
        add_log("info", "常规打卡成功日志", username="23370001", category="regular")
        add_log("success", "博雅抢课成功日志", username="23370001", category="boya")

        res_reg = self.client.get("/api/logs?category=regular")
        self.assertEqual(res_reg.status_code, 200)
        reg_logs = res_reg.json()["logs"]
        self.assertTrue(any("常规打卡成功" in l["message"] for l in reg_logs))
        self.assertFalse(any("博雅抢课成功" in l["message"] for l in reg_logs))

        res_boya = self.client.get("/api/logs?category=boya")
        self.assertEqual(res_boya.status_code, 200)
        boya_logs = res_boya.json()["logs"]
        self.assertTrue(any("博雅抢课成功" in l["message"] for l in boya_logs))
        self.assertFalse(any("常规打卡成功" in l["message"] for l in boya_logs))

if __name__ == "__main__":
    unittest.main()
