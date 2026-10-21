"""Run with an explicit empty BUAA_CONFIG_FILE; never open a user's profile."""
import asyncio
import os
import unittest
from datetime import timedelta
from unittest.mock import AsyncMock, patch

if not os.environ.get("BUAA_CONFIG_FILE") or os.environ.get("TESTING") != "1":
    raise RuntimeError("v1.2.7 API tests require the isolated test runner")

from fastapi.testclient import TestClient
from server import app as backend
from core.domain import now

class APIContracts(unittest.TestCase):
    def setUp(self):
        backend.boya_scheduler.stop()
        self.worker = patch.object(backend.boya_scheduler, 'start')
        self.worker.start()
        self.addCleanup(self.worker.stop)
        self.previous = dict(backend.accounts)
        self.previous_active = backend.active_username
        backend.accounts.clear()
        self.account = backend.AccountState("fixture-account", remember=False, auto_checkin=False)
        backend.accounts[self.account.username] = self.account
        backend.active_username = self.account.username
        self.client = TestClient(backend.app)
        csrf = self.client.get("/api/session").json()["csrf"]
        self.client.headers["X-BUAA-CSRF"] = csrf

    def tearDown(self):
        self.client.close()
        self.account.boya_client.close()
        if self.account.client._client is not None:
            asyncio.run(self.account.client.close())
        backend.accounts.clear()
        backend.accounts.update(self.previous)
        backend.active_username = self.previous_active

    def test_unknown_explicit_account_does_not_fall_back(self):
        self.account.client.perform_signin = AsyncMock(return_value=(True, "synthetic"))
        response = self.client.post("/api/signin", json={"username": "missing-fixture", "course_id": "1001"})
        self.assertEqual(response.status_code, 404)
        self.account.client.perform_signin.assert_not_called()
        self.assertEqual(self.client.get("/api/classes?username=missing-fixture").status_code, 404)
        old_mode=backend.config.get("default_mode")
        self.assertEqual(self.client.post("/api/mode",json={"username":"missing-fixture","mode":"webvpn"}).status_code,404)
        self.assertEqual(backend.config.get("default_mode"),old_mode)

    def test_invalid_sign_type_or_coordinates_rejected_by_api(self):
        for body in ({"course_id": 1001, "sign_type": 9}, {"course_id": 1001, "sign_type": True}, {"course_id": 1001, "sign_type": 1.0}, {"course_id": -1}, {"course_id": 1001, "lat": 200, "lng": 30}, {"course_id": 1001, "lat": 39}):
            self.assertEqual(self.client.post("/api/boya/sign", json=body).status_code, 422)

    def test_public_health_contains_no_account_identity(self):
        response = self.client.get("/api/health").json()
        self.assertEqual(response["version"], "1.4.10")
        self.assertNotIn("active_username", response)
        self.assertNotIn(self.account.username, str(response))

    def test_offline_account_never_receives_demo_courses_or_fake_success(self):
        for endpoint,field in (("courses","courses"),("selected","selected")):
            data=self.client.get("/api/boya/"+endpoint).json()
            self.assertTrue(data["stale"])
            self.assertFalse(data["is_demo"])
            self.assertEqual(data[field],[])
        data=self.client.get("/api/boya/statistics").json()
        self.assertFalse(data["statistics"]["semester_known"])

    def test_invalid_targets_and_campus_do_not_partially_enable_automation(self):
        for body in ({"auto_select":True,"campus":"unknown"},{"auto_select":True,"targets":{"美育":True}},{"auto_select":True,"targets":{"美育":1}}):
            self.assertEqual(self.client.post("/api/boya/toggle_auto",json=body).status_code,422)
            self.assertFalse(self.account.boya_auto_select)
        targets={"德育":0,"劳育":0,"美育":0,"安全健康":0}
        data=self.client.post("/api/boya/toggle_auto",json={"targets":targets}).json()
        self.assertEqual(data["boya_targets"],targets)

    def test_failed_persistence_cannot_leave_boya_automation_secretly_enabled(self):
        with patch.object(backend,"sync_config",side_effect=OSError("synthetic storage failure")),patch.object(backend.boya_scheduler,"start") as start:
            response=self.client.post("/api/boya/toggle_auto",json={"auto_select":True})
        self.assertEqual(response.status_code,503)
        self.assertFalse(self.account.boya_auto_select)
        start.assert_not_called()

    def test_stop_remains_effective_when_config_cannot_be_saved(self):
        self.account.boya_auto_select=True
        with patch.object(backend,"sync_config",side_effect=OSError("synthetic storage failure")):
            response=self.client.post("/api/boya/toggle_auto",json={"auto_select":False})
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json()["persisted"])
        self.assertFalse(response.json()["boya_auto_select"])
        self.assertFalse(self.account.boya_auto_select)

    def test_failed_persistence_rolls_back_regular_enable(self):
        backend.scheduler.stop()
        with patch.object(backend,"sync_config",side_effect=OSError("synthetic storage failure")):
            response=self.client.post("/api/auto_checkin",json={"enabled":True})
        self.assertEqual(response.status_code,503)
        self.assertFalse(backend.scheduler.enabled)
        for value in (True,5,100,20.5):
            self.assertEqual(self.client.post("/api/auto_checkin",json={"enabled":True,"interval":value}).status_code,422)

    def test_autostart_system_failure_cannot_report_requested_state_as_success(self):
        with patch("core.autostart.set_autostart",return_value=False),patch("core.autostart.get_autostart_status",return_value=False):
            data=self.client.post("/api/system/autostart",json={"enabled":True}).json()
        self.assertEqual(data["status"],"error")
        self.assertFalse(data["enabled"])

    def test_pool_unknowns_remain_unknown_and_official_category_is_preserved(self):
        course={"id":9001,"courseKind":"智育","courseName":"synthetic art title","courseCurrentCount":None,"courseMaxCount":None,"courseSignConfig":{"signPointList":[{}]}}
        data=backend.enrich_pool([course])[0]
        self.assertFalse(data["autonomous_config_valid"])
        self.assertFalse(data["capacity_available"])
        self.assertIsNone(data["capacity_current"])
        self.assertEqual(data["category_key"],"智育")

    def test_signinfo_or_elapsed_time_does_not_invent_pass(self):
        old = (now()-timedelta(days=1)).isoformat()
        course = {"id": 1001, "courseStartDate": old, "courseEndDate": old, "checkin": 5, "pass": None, "signInfo": '{"signIn":null}'}
        data = backend.enrich_selected_courses([course], [])[0]
        self.assertFalse(data["final_passed"])
        self.assertIsNone(data["exam_status"]["passed"])
        self.assertIsNone(data["attendance_status"]["passed"])

    def test_unknown_or_historical_dates_never_count_toward_current_term(self):
        info = {"semesterStartDate": (now()-timedelta(days=10)).isoformat(), "semesterEndDate": (now()+timedelta(days=30)).isoformat()}
        current = {"id": 1001, "courseKind": "美育", "courseStartDate": (now()-timedelta(days=1)).isoformat(), "courseEndDate": (now()-timedelta(hours=1)).isoformat(), "checkin": 1, "pass": 1}
        missing = {"id": 1002, "courseKind": "德育", "checkin": 1, "pass": 1}
        historical = {**current, "id": 1003, "courseKind": "劳育", "courseStartDate": "2020-01-01", "courseEndDate": "2020-01-01"}
        summary = backend.compute_semester_statistics([current, missing, historical], {"semesterInfo": info, "validCount": 99})
        self.assertEqual(summary["semester_passed_total"], 1)
        self.assertEqual(summary["unknown_date_count"], 1)
        self.assertEqual(summary["official_valid_count"], 99)
        unknown = backend.compute_semester_statistics([current], {})
        self.assertFalse(unknown["semester_known"])
        self.assertIsNone(unknown["valid_count"])

if __name__ == "__main__":
    unittest.main()
