"""
集成测试：FastAPI 端点与静态资源服务测试
"""

import unittest
from fastapi.testclient import TestClient
from server.app import app


class TestApiServer(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_status_endpoint(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("authenticated", data)
        self.assertIn("mode", data)
        self.assertIn("auto_checkin", data)

    def test_mode_switch(self):
        resp = self.client.post("/api/mode", json={"mode": "webvpn"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["mode"], "webvpn")

        resp = self.client.post("/api/mode", json={"mode": "direct"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["mode"], "direct")

    def test_classes_unauthenticated(self):
        resp = self.client.get("/api/classes")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "unauthenticated")

    def test_auto_checkin_toggle(self):
        resp = self.client.post("/api/auto_checkin", json={"enabled": True, "interval": 45})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["interval"], 45)

        resp = self.client.post("/api/auto_checkin", json={"enabled": False})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["enabled"])

    def test_logs_endpoint(self):
        resp = self.client.get("/api/logs")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("logs", resp.json())

    def test_static_index_serving(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("BUAA 课程签到", resp.text)
        self.assertIn("style.css", resp.text)
        self.assertIn("app.js", resp.text)

    def test_health_v122(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["version"], "1.2.2")

    def test_system_autostart(self):
        resp = self.client.get("/api/system/autostart")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("enabled", resp.json())

        resp = self.client.post("/api/system/autostart", json={"enabled": False})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["enabled"])

    def test_system_disclaimer(self):
        resp = self.client.get("/api/system/disclaimer")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("accepted", resp.json())

        resp = self.client.post("/api/system/disclaimer/accept")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["accepted"])

    def test_window_show(self):
        resp = self.client.post("/api/window/show")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_logs_isolation_by_user_and_category(self):
        from server.app import add_log, logs_list
        # 清空测试前的日志
        self.client.post("/api/logs/clear")
        logs_list.clear()

        # 构造各学生与业务分类日志
        add_log("info", "系统守护进程启动成功", username="", category="system")
        add_log("info", "学生1常规签到成功", username="student1", category="regular")
        add_log("info", "学生1抢中博雅课程", username="student1", category="boya")
        add_log("info", "学生2常规课堂待考勤", username="student2", category="regular")
        add_log("info", "学生2已选博雅课程同步", username="student2", category="boya")

        # 1. 学生1 - 总日志 (应当只包含 学生1的日志 + 系统公共日志，绝不包含学生2)
        r_s1_all = self.client.get("/api/logs?username=student1&category=all").json()
        s1_all_msgs = [l["message"] for l in r_s1_all["logs"]]
        self.assertIn("系统守护进程启动成功", s1_all_msgs)
        self.assertIn("学生1常规签到成功", s1_all_msgs)
        self.assertIn("学生1抢中博雅课程", s1_all_msgs)
        self.assertNotIn("学生2常规课堂待考勤", s1_all_msgs)
        self.assertNotIn("学生2已选博雅课程同步", s1_all_msgs)

        # 2. 学生1 - 常规课程 (应当只包含 学生1的常规日志，绝不包含博雅日志)
        r_s1_reg = self.client.get("/api/logs?username=student1&category=regular").json()
        s1_reg_msgs = [l["message"] for l in r_s1_reg["logs"]]
        self.assertIn("学生1常规签到成功", s1_reg_msgs)
        self.assertNotIn("学生1抢中博雅课程", s1_reg_msgs)
        self.assertNotIn("学生2常规课堂待考勤", s1_reg_msgs)

        # 3. 学生1 - 自动博雅 (应当只包含 学生1的博雅日志，绝不包含常规日志)
        r_s1_boya = self.client.get("/api/logs?username=student1&category=boya").json()
        s1_boya_msgs = [l["message"] for l in r_s1_boya["logs"]]
        self.assertIn("学生1抢中博雅课程", s1_boya_msgs)
        self.assertNotIn("学生1常规签到成功", s1_boya_msgs)
        self.assertNotIn("学生2已选博雅课程同步", s1_boya_msgs)

        # 4. 学生2 - 常规与博雅隔离
        r_s2_reg = self.client.get("/api/logs?username=student2&category=regular").json()
        s2_reg_msgs = [l["message"] for l in r_s2_reg["logs"]]
        self.assertIn("学生2常规课堂待考勤", s2_reg_msgs)
        self.assertNotIn("学生1常规签到成功", s2_reg_msgs)

        # 5. 精确清空学生1的博雅日志
        self.client.post("/api/logs/clear?username=student1&category=boya")
        r_s1_boya_after = self.client.get("/api/logs?username=student1&category=boya").json()
        self.assertEqual(len(r_s1_boya_after["logs"]), 0)
        # 常规日志依然健在
        r_s1_reg_after = self.client.get("/api/logs?username=student1&category=regular").json()
        self.assertIn("学生1常规签到成功", [l["message"] for l in r_s1_reg_after["logs"]])


if __name__ == "__main__":
    unittest.main()
