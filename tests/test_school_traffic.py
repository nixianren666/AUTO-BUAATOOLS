import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from core import operations, school_traffic
from core.boya_client import BoyaClient
from core.iclass import IclassClient


class DurableTrafficTests(unittest.TestCase):
    def test_threads_and_independent_connections_share_cap_after_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "operations.sqlite"
            ledgers = [operations.OperationLedger(path) for _ in range(4)]
            owner = school_traffic.owner_key(" Fixture-Account ")
            self.assertEqual(owner, school_traffic.owner_key("fixture-account"))

            def attempt(index):
                return ledgers[index % len(ledgers)].reserve_school_requests(
                    owner, 1, "", ((60, 4),), ((60, 10),), ()
                )

            try:
                with ThreadPoolExecutor(8) as workers:
                    self.assertEqual(list(workers.map(attempt, range(30))).count(0), 4)
            finally:
                for ledger in ledgers:
                    ledger.db.close()
            reopened = operations.OperationLedger(path)
            try:
                self.assertGreater(reopened.reserve_school_requests(owner, 1, "", ((60, 4),), (), ()), 0)
                reopened.set_school_auth_pause(owner, "sms_required")
                self.assertIsNone(reopened.reserve_school_requests(owner, 1, "", (), (), ()))
                self.assertEqual(reopened.reserve_school_requests(owner, 1, "login", (), (), (), allow_auth_pause=True), 0)
            finally:
                reopened.db.close()

    def test_weighted_td_and_rolling_window(self):
        ledger = operations.OperationLedger()
        self.addCleanup(ledger.db.close)
        args = ("fixture-owner", 2, "", ((60, 3),), (), ())
        with patch("core.operations.time.time", return_value=1000):
            self.assertEqual(ledger.reserve_school_requests(*args), 0)
            self.assertGreater(ledger.reserve_school_requests(*args), 0)
        with patch("core.operations.time.time", return_value=1061):
            self.assertEqual(ledger.reserve_school_requests(*args), 0)

    def test_default_caps_hold_across_multiple_accounts_and_sustained_attempts(self):
        ledger = operations.OperationLedger()
        self.addCleanup(ledger.db.close)
        owners = [school_traffic.owner_key(f"fixture-{index}") for index in range(4)]
        admitted = [0] * len(owners)
        with patch.object(operations, "ledger", ledger), patch("core.operations.time.time") as clock:
            for attempt in range(1300):
                clock.return_value = 100000 + attempt * 30
                for index, owner in enumerate(owners):
                    decision = ledger.reserve_school_requests(
                        owner, 1, "", school_traffic.ACCOUNT_LIMITS, school_traffic.INSTALLATION_LIMITS, ()
                    )
                    admitted[index] += decision == 0
        self.assertEqual(sum(admitted), 1800)
        self.assertTrue(all(0 < count <= 600 for count in admitted))

    def test_installation_cap_scales_above_three_accounts_without_cross_starvation(self):
        ledger = operations.OperationLedger()
        self.addCleanup(ledger.db.close)
        self.addCleanup(school_traffic.set_account_count_provider, None)
        school_traffic.set_account_count_provider(lambda: 3)
        self.assertEqual(school_traffic.installation_limits(), school_traffic.INSTALLATION_LIMITS)
        school_traffic.set_account_count_provider(lambda: 4)
        self.assertEqual(school_traffic.installation_limits(), ((60, 96), (3600, 480), (86400, 2400)))
        users = [f"multi-student-{idx}" for idx in range(4)]
        admitted = [0] * len(users)
        with patch.object(operations, "ledger", ledger), patch("core.operations.time.time") as clock:
            for batch in range(600):
                # Monotonic timestamps within a single 24h window: <=20 req/min/user (80<=96 global),
                # <=100 req/hr/user (400<=480 global), and 600 req/user total (2400<=2400 global).
                clock.return_value = 200000 + (batch // 100) * 3605 + ((batch % 100) // 20) * 65 + (batch % 20) * 2
                for idx, user in enumerate(users):
                    try:
                        school_traffic.reserve(user)
                        admitted[idx] += 1
                    except school_traffic.SchoolTrafficPaused:
                        pass
            # After all 4 reach 600/24h (2400 total), extra attempts on any account are blocked.
            with self.assertRaises(school_traffic.SchoolTrafficPaused):
                school_traffic.reserve(users[0])
        self.assertEqual(admitted, [600, 600, 600, 600])

    def test_ensure_headroom_blocks_insufficient_budget_without_consuming_slots(self):
        ledger = operations.OperationLedger()
        self.addCleanup(ledger.db.close)
        self.addCleanup(school_traffic.set_account_count_provider, None)
        school_traffic.set_account_count_provider(lambda: 1)
        with patch.object(operations, "ledger", ledger), patch("core.operations.time.time", return_value=300000):
            for _ in range(20):
                school_traffic.reserve("headroom-student")
            before_count = ledger.db.execute("SELECT COALESCE(SUM(cost),0) FROM school_requests").fetchone()[0]
            self.assertEqual(before_count, 20)
            with self.assertRaises(school_traffic.SchoolTrafficPaused) as err:
                school_traffic.ensure_headroom("headroom-student", 12)
            self.assertGreater(err.exception.retry_after, 0)
            after_count = ledger.db.execute("SELECT COALESCE(SUM(cost),0) FROM school_requests").fetchone()[0]
            self.assertEqual(after_count, 20)
            # Smaller request still fits cleanly because preflight did not burn a slot.
            school_traffic.reserve("headroom-student")



class SharedTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = operations.OperationLedger()
        self.addCleanup(self.ledger.db.close)
        switch = patch.object(operations, "ledger", self.ledger)
        switch.start()
        self.addCleanup(switch.stop)
        self.regular = IclassClient()
        self.boya = BoyaClient()
        self.regular.operation_user = "fixture-student"
        self.boya.operation_user = "fixture-student"
        self.addAsyncCleanup(self.regular.close)
        self.addCleanup(self.boya.close)

    async def test_regular_and_boya_share_budget_at_actual_dispatch(self):
        sent = []

        def handle(request):
            sent.append(request.method)
            return httpx.Response(200)

        # Keep the production hooks while substituting only the network transport.
        original_regular = self.regular.client
        await original_regular.aclose()
        self.regular._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handle), event_hooks=original_regular.event_hooks,
        )
        original_boya = self.boya.http_client
        original_boya.close()
        self.boya.http_client = httpx.Client(
            transport=httpx.MockTransport(handle), event_hooks=original_boya.event_hooks,
        )
        with patch.object(school_traffic, "ACCOUNT_LIMITS", ((60, 2),)):
            await self.regular.client.get("https://iclass.buaa.edu.cn/")
            await asyncio.to_thread(self.boya.http_client.get, "https://bykc.buaa.edu.cn/")
            with self.assertRaises(school_traffic.SchoolTrafficPaused):
                await self.regular.client.get("https://sso.buaa.edu.cn/login")
        self.assertEqual(sent, ["GET", "GET"])

    async def test_server_retry_after_blocks_other_client_before_dispatch(self):
        response = httpx.Response(429, headers={"Retry-After": "600"})
        await self.regular._after_response(response)
        with self.assertRaises(school_traffic.SchoolTrafficPaused) as error:
            self.boya._before_request(httpx.Request("GET", "https://bykc.buaa.edu.cn/"))
        self.assertGreaterEqual(error.exception.retry_after, 599)
        self.boya.operation_user = "fixture-other"
        self.boya._before_request(httpx.Request("GET", "https://bykc.buaa.edu.cn/"))

    async def test_final_write_guard_is_checked_after_reserving_budget(self):
        scope = self.regular.final_write_guard.set(lambda: False)
        try:
            with self.assertRaises(school_traffic.SchoolTrafficPaused):
                await self.regular._before_request(httpx.Request("POST", "https://iclass.buaa.edu.cn:8347/app/course/stu_scan_sign.action"))
        finally:
            self.regular.final_write_guard.reset(scope)
