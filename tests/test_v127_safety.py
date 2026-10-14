"""Independent contracts for delayed, malformed and concurrent school responses."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
from core import operations
from core.domain import autonomous, semester, within_semester, trusted_url, course_id, CHINA
from core.iclass import IclassClient
from core.boya_client import BoyaClient, BoyaApiError
from core.boya_crypto import encrypt_local_secret, decrypt_local_secret

class Contracts(unittest.TestCase):
    def test_unknown_points_and_windows_are_not_auto_candidates(self):
        for raw in ({"signPointList": [{}]}, {"signPointList": [{"lat": 39, "lng": 116, "radius": "NaN"}]}, {"signPointList": [{"lat": 39, "lng": 116, "radius": 20}]}):
            self.assertFalse(autonomous({"courseSignConfig": raw}, require_windows=True))

    def test_official_semester_includes_last_calendar_day(self):
        info = {"semesterStartDate": "2026-09-01", "semesterEndDate": "2027-01-31"}
        self.assertEqual(semester({"data": {"semester": [info]}}, datetime(2027, 1, 31, 23)), info)
        self.assertFalse(within_semester({}, info))
        with self.assertRaises(ValueError):
            semester({"data": {"semester": [info]}}, datetime(2027, 8, 30))

    def test_redirects_refuse_lookalikes_plaintext_and_userinfo(self):
        for url in ("https://sso.buaa.edu.cn.attacker.test/login", "http://sso.buaa.edu.cn/login", "https://a@sso.buaa.edu.cn/login", "https://sso.buaa.edu.cn:8347/login"):
            with self.assertRaises(ValueError):
                trusted_url(url)
        self.assertEqual(trusted_url("https://iclass.buaa.edu.cn:8347/app/"), "https://iclass.buaa.edu.cn:8347/app/")

    def test_invalid_id_never_truncates_to_another_course(self):
        for value in (True, 1.7, "1;attack", -1, "١٠٠١", "１００１"):
            self.assertIsNone(course_id({"id": value}))

    def test_gateway_cannot_hide_an_untrusted_inner_auth_host(self):
        from core.webvpn import to_webvpn_url
        for inner in ("https://attacker.test/login", "http://sso.buaa.edu.cn/login"):
            with self.assertRaises(ValueError):
                trusted_url(to_webvpn_url(inner))
        official = to_webvpn_url("https://iclass.buaa.edu.cn:8347/app/")
        self.assertEqual(trusted_url(official), official)

    def test_protected_vault_roundtrip_and_failure_never_plaintext(self):
        secret = "synthetic-test-secret"
        stored = encrypt_local_secret(secret)
        self.assertNotIn(secret, stored)
        self.assertEqual(decrypt_local_secret(stored), secret)
        with patch("core.vault.encrypt", side_effect=OSError("synthetic failure")):
            with self.assertRaises(OSError):
                encrypt_local_secret(secret)

    def test_persistent_claims_survive_other_connections(self):
        with tempfile.TemporaryDirectory() as root:
            a = operations.OperationLedger(Path(root)/"operations.sqlite")
            b = operations.OperationLedger(Path(root)/"operations.sqlite")
            try:
                self.assertTrue(a.claim("synthetic-key"))
                with self.assertRaises(operations.OperationBusy):
                    b.claim("synthetic-key")
                a.finish("synthetic-key", "success")
                self.assertFalse(b.claim("synthetic-key"))
            finally:
                a.db.close()
                b.db.close()

    def test_long_running_cleanup_preserves_unresolved_writes(self):
        import time
        ledger = operations.OperationLedger()
        try:
            ledger.claim("old-uncertain",group="fixture-group")
            ledger.finish("old-uncertain","uncertain")
            ledger.claim("old-failed");ledger.finish("old-failed","failed")
            ledger.db.execute("UPDATE operations SET updated=?",(time.time()-181*86400,));ledger.db.commit()
            ledger._last_prune -= 86401
            with self.assertRaises(operations.OperationBusy):
                ledger.claim("changed-window",group="fixture-group")
            self.assertIsNotNone(ledger.read("old-uncertain"))
            self.assertIsNone(ledger.read("old-failed"))
        finally:ledger.db.close()

class RegularWrites(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous = operations.ledger
        operations.ledger = operations.OperationLedger()
        self.current = datetime(2026, 10, 14, 8, 59, 50)
        self.posts = []
        self.timestamp = str(int(self.current.replace(tzinfo=CHINA).timestamp()*1000))
        self.delay = 0
        self.failure = False
        self.timeout = False
        self.client = IclassClient()
        self.client.operation_user = "fixture-account"
        self.client.user_id, self.client.session_id = "fixture-id", "fixture-session"
        self.client.clock = lambda: self.current
        self.classes = [{"courseSchedId": "1001", "classBeginTime": "2026-10-14 09:00:00", "signStatus": 0}]
        async def classes():
            return list(self.classes)
        self.client.get_today_classes = classes
        def transport(request):
            if request.method == "GET":
                self.current += timedelta(seconds=self.delay)
                return httpx.Response(200, json={"timestamp": self.timestamp})
            self.posts.append(request)
            if self.timeout:
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(200, json={"STATUS": "failed" if self.failure else "0", "ERRMSG": "synthetic rejection" if self.failure else "", "result": {"stuSignStatus": "0" if self.failure else "1"}})
        self.client._client = httpx.AsyncClient(transport=httpx.MockTransport(transport), trust_env=False)

    async def asyncTearDown(self):
        await self.client.close()
        operations.ledger.db.close()
        operations.ledger = self.previous

    async def test_timestamp_delay_crossing_start_sends_no_post(self):
        self.delay = 15
        success, _ = await self.client.perform_signin("1001")
        self.assertFalse(success)
        self.assertEqual(len(self.posts), 0)

    async def test_missing_timestamp_sends_no_post(self):
        self.timestamp = None
        success, _ = await self.client.perform_signin("1001")
        self.assertFalse(success)
        self.assertEqual(len(self.posts), 0)

    async def test_unowned_course_sends_no_post(self):
        success, _ = await self.client.perform_signin("9999")
        self.assertFalse(success)
        self.assertEqual(len(self.posts), 0)

    async def test_raw_fractional_and_boolean_school_status_never_authorizes_post(self):
        raw = {"STATUS":"0","result":[dict(self.classes[0])]}
        def transport(request):
            if "get_stu_course_sched" in request.url.path:
                return httpx.Response(200,json=raw)
            self.posts.append(request)
            return httpx.Response(500)
        await self.client._client.aclose()
        self.client._client=httpx.AsyncClient(transport=httpx.MockTransport(transport))
        self.client.get_today_classes=lambda:IclassClient.get_classes(self.client,self.current.date())
        for value in (0.8,0.0,True,False,"٠",None):
            raw["result"][0]["signStatus"]=value
            self.assertIsNone((await self.client.get_today_classes())[0]["signStatus"])
            self.assertFalse((await self.client.perform_signin("1001"))[0])
        self.assertEqual(self.posts,[])

    async def test_manual_auto_race_sends_one_post(self):
        results = await asyncio.gather(self.client.perform_signin("1001"), self.client.perform_signin("1001", guard=lambda: True))
        self.assertTrue(all(x[0] for x in results))
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.posts[0].url.path, "/app/course/stu_scan_sign.action")

    async def test_three_attempt_budget_counts_actual_posts(self):
        self.failure = True
        for _ in range(5):
            success, _ = await self.client.perform_signin("1001")
            self.assertFalse(success)
        self.assertEqual(len(self.posts), 3)

    async def test_connection_failure_before_send_preserves_actual_budget(self):
        real_post = self.client._client.post
        async def offline(*args, **kwargs):
            raise httpx.ConnectError("synthetic connection failure")
        self.client._client.post = offline
        for _ in range(4):
            self.assertFalse((await self.client.perform_signin("1001"))[0])
        self.assertEqual(self.client.actual_sign_posts, 0)
        self.client._client.post = real_post
        self.assertTrue((await self.client.perform_signin("1001"))[0])
        self.assertEqual(len(self.posts), 1)

    async def test_timeout_blocks_replay_until_official_confirmation(self):
        self.timeout = True
        with self.assertRaises(httpx.ReadTimeout):
            await self.client.perform_signin("1001")
        self.timeout = False
        success, message = await self.client.perform_signin("1001")
        self.assertFalse(success)
        self.assertIn("官方", message)
        self.assertEqual(len(self.posts), 1)
        self.classes[0]["signStatus"] = 1
        self.assertTrue((await self.client.perform_signin("1001"))[0])
        self.assertEqual(len(self.posts), 1)

    async def test_stop_after_reads_blocks_post(self):
        success, _ = await self.client.perform_signin("1001", guard=lambda: False)
        self.assertFalse(success)
        self.assertEqual(len(self.posts), 0)

    async def test_wrong_device_clock_cannot_authorize_school_closed_window(self):
        self.timestamp = str(int((self.current+timedelta(minutes=2)).replace(tzinfo=CHINA).timestamp()*1000))
        success, _ = await self.client.perform_signin("1001")
        self.assertFalse(success)
        self.assertEqual(self.posts, [])

if __name__ == "__main__":
    unittest.main()
