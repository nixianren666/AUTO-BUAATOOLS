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

    def test_health_v120(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["version"], "1.2.0")

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


if __name__ == "__main__":
    unittest.main()
