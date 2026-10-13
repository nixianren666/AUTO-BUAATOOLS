import json
import threading
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from core import operations
from core.domain import now, autonomous
from core.boya_client import BoyaClient, BoyaApiError
from core.boya_actions import perform_boya_action, merge_selected
from core.boya_scheduler import is_auto_select_candidate, BoyaScheduler

def fixture_course(cid=1001):
    current = now()
    fmt = lambda d: d.isoformat(sep=" ", timespec="seconds")
    return {"id": cid, "courseId": cid, "courseName": "synthetic-course", "courseKind": "美育", "coursePosition": "北京", "courseCurrentCount": 1, "courseMaxCount": 20, "courseSelectStartDate": fmt(current-timedelta(hours=1)), "courseSelectEndDate": fmt(current+timedelta(hours=1)), "courseStartDate": fmt(current+timedelta(hours=2)), "courseEndDate": fmt(current+timedelta(hours=3)), "checkin": 0, "pass": None, "courseSignConfig": {"signPointList": [{"lat": 39, "lng": 116, "radius": 20}], "signStartDate": fmt(current-timedelta(minutes=1)), "signEndDate": fmt(current+timedelta(minutes=2)), "signOutStartDate": fmt(current+timedelta(hours=2)), "signOutEndDate": fmt(current+timedelta(hours=4))}}

class FakeCrypto:
    def encrypt_request(self, payload):
        return SimpleNamespace(body=json.dumps(payload).encode(), headers={})
    def decrypt_response(self, body):
        return json.loads(body)

class BoyaContracts(unittest.TestCase):
    def setUp(self):
        self.previous = operations.ledger
        operations.ledger = operations.OperationLedger()
        self.course = fixture_course()
        current = now()
        self.client = BoyaClient(token="synthetic-token")
        self.client.operation_user = "fixture-account"
        self.client.semester_info = {"semesterStartDate": (current-timedelta(days=30)).isoformat(), "semesterEndDate": (current+timedelta(days=30)).isoformat(), "semesterName": "synthetic-semester"}
        self.selected = []
        self.client.query_chosen_courses = lambda: list(self.selected)
        self.client.query_courses = lambda **kwargs: [self.course]
        self.acc = SimpleNamespace(username="fixture-account", name="synthetic-user", removed=False, boya_client=self.client, boya_all_courses=[self.course], boya_selected_courses=[], boya_pending_courses={}, campus="北京", boya_auto_select=True, boya_auto_sign=True, boya_health={}, password="")
        self.posts = []
        self.reply = {"status": "0", "data": {}}
        self.http_status = 200
        self.after_post = None
        def transport(request):
            self.posts.append(request)
            if self.after_post:
                self.after_post()
            return httpx.Response(self.http_status, json=self.reply)
        self.client.http_client.close()
        self.client.http_client = httpx.Client(transport=httpx.MockTransport(transport))
        self.crypto = patch("core.boya_client.BykcCrypto", FakeCrypto)
        self.crypto.start()

    def tearDown(self):
        self.crypto.stop()
        self.client.close()
        operations.ledger.db.close()
        operations.ledger = self.previous

    def test_same_title_other_id_never_supplies_config(self):
        raw = {"id": 9999, "courseName": self.course["courseName"]}
        self.assertNotIn("courseSignConfig", merge_selected(raw, [self.course]))

    def test_capacity_and_missing_windows_fail_closed(self):
        self.assertTrue(is_auto_select_candidate(self.course, now()))
        for value in (None, "bad", -1, True, float("nan")):
            course = {**self.course, "courseCurrentCount": value}
            self.assertFalse(is_auto_select_candidate(course, now()))
        self.course["courseSignConfig"].pop("signOutEndDate")
        self.assertFalse(is_auto_select_candidate(self.course, now()))

    def test_unselected_and_invalid_sign_never_post(self):
        for kind in (1, 9):
            with self.assertRaises(BoyaApiError):
                perform_boya_action(self.acc, "sign", 1001, sign_type=kind)
        self.assertEqual(self.posts, [])

    def test_passed_course_never_re_signs(self):
        self.selected = [{**self.course, "pass": 1, "checkin": 1}]
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "sign", 1001)
        self.assertEqual(self.posts, [])

    def test_invalid_location_does_not_use_defaults(self):
        self.selected = [{**self.course, "courseSignConfig": {"signPointList": [{}]}}]
        self.acc.boya_all_courses = []
        self.client.query_courses = lambda: []
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "sign", 1001)
        self.assertEqual(self.posts, [])

    def test_http500_and_missing_business_status_are_not_success(self):
        for status, reply in ((500, {"status": "0"}), (200, {"errmsg": "synthetic error"})):
            self.http_status, self.reply = status, reply
            with self.assertRaises((ValueError, httpx.HTTPStatusError)):
                self.client.call("queryChosenCourse")

    def test_registration_id_never_used_for_drop_fallback(self):
        self.selected = [{**self.course, "chosenCourseId": 2002}]
        self.reply = {"status": "rejected", "errmsg": "synthetic permission rejection"}
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "drop", 1001)
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(json.loads(self.posts[0].content), {"id": 1001})

    def test_normal_class_conflict_blocks_auto_select(self):
        ordinary = lambda *args: [{"classBeginTime": self.course["courseStartDate"], "classEndTime": self.course["courseEndDate"]}]
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "select", 1001, automatic=True, ordinary=ordinary)
        self.assertEqual(self.posts, [])

    def test_batch_reservation_blocks_conflicting_second_course(self):
        second = fixture_course(1002)
        second["courseKind"] = "劳育"
        self.client.query_courses = lambda: [self.course, second]
        result = perform_boya_action(self.acc, "select", 1001, automatic=True, ordinary=lambda *args: [])
        self.assertTrue(result["pending_verification"])
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "select", 1002, automatic=True, ordinary=lambda *args: [])
        self.assertEqual(len(self.posts), 1)

    def test_category_target_stops_unneeded_enrollment(self):
        other = fixture_course(1002)
        other["courseStartDate"] = (now()+timedelta(days=1)).isoformat()
        other["courseEndDate"] = (now()+timedelta(days=1,hours=1)).isoformat()
        self.selected = [other]
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "select", 1001, automatic=True, ordinary=lambda *args: [])
        self.assertEqual(self.posts, [])

    def test_stopped_during_preflight_never_posts(self):
        def chosen():
            self.acc.removed = True
            return [self.course]
        self.client.query_chosen_courses = chosen
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "sign", 1001)
        self.assertEqual(self.posts, [])

    def test_pagination_early_end_and_duplicate_page_rejected(self):
        # Exercise actual pagination code, not a fixture method replacement.
        for pages in ([{"content": [{"id": 1}], "totalPages": 2, "totalElements": 2, "last": True}], [{"content": [{"id": 1}], "totalPages": 2, "totalElements": 2}, {"content": [{"id": 1}], "totalPages": 2, "totalElements": 2}]):
            self.client.query_course_page = lambda page, size, pages=pages: {"data": pages[min(page-1,len(pages)-1)]}
            with self.assertRaises(BoyaApiError):
                BoyaClient.query_courses(self.client)

    def test_pagination_without_totals_keeps_reading_full_pages(self):
        self.client.query_course_page = lambda page, size: {"data": {"content": [{"id": i+1+(page-1)*100} for i in range(100 if page <= 4 else (3 if page == 5 else 0))]}}
        self.assertEqual(len(BoyaClient.query_courses(self.client)), 403)

    def test_official_drop_allows_later_explicit_reenrollment(self):
        import time
        stamp = time.time()
        self.after_post = lambda: self.selected.append(dict(self.course))
        self.assertFalse(perform_boya_action(self.acc, "select", 1001)["pending_verification"])
        self.after_post = lambda: self.selected.clear()
        self.assertFalse(perform_boya_action(self.acc, "drop", 1001)["pending_verification"])
        self.after_post = lambda: self.selected.append(dict(self.course))
        with patch("core.boya_client.time.time", return_value=stamp+61):
            self.assertFalse(perform_boya_action(self.acc, "select", 1001)["pending_verification"])
        self.assertEqual(len(self.posts), 3)

    def test_existing_attendance_prevents_drop(self):
        self.selected = [{**self.course, "checkin": 5}]
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc, "drop", 1001)
        self.assertEqual(self.posts, [])

    def test_uncertain_selection_reserves_conflicting_seat_before_next_candidate(self):
        self.http_status = 500
        with self.assertRaises(httpx.HTTPStatusError):
            perform_boya_action(self.acc, "select", 1001, automatic=True, ordinary=lambda *a: [])
        self.assertIn(1001, self.acc.boya_pending_courses)
        self.assertIn(1001, operations.ledger.reservations(self.acc.username))
        other = {**self.course, "id":1002, "courseId":1002, "courseKind":"德育"}
        self.client.query_courses = lambda **kw: [self.course,other]
        self.http_status = 200
        with self.assertRaises(BoyaApiError):
            perform_boya_action(self.acc,"select",1002,automatic=True,ordinary=lambda *a: [])
        self.assertEqual(len(self.posts),1)

if __name__ == "__main__":
    unittest.main()
