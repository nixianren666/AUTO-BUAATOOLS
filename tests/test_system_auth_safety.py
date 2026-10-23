"""Read endpoints must not turn refreshes into repeated school authentication."""
import asyncio
import time
import unittest
from unittest.mock import Mock, patch

from core.boya_client import BoyaApiError
from server import app as backend


class ReadAuthenticationSafety(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.acc = backend.AccountState('fixture-refresh-student', remember=False, auto_checkin=False)
        self.acc.client.user_info = {'schoolid': self.acc.username}
        self.acc.boya_all_courses = []
        self.acc.boya_selected_courses = []
        self.acc.boya_statistics = {}
        self.scope = patch.dict(backend.accounts, {self.acc.username: self.acc}, clear=True)
        self.scope.start()

    async def asyncTearDown(self):
        self.scope.stop()
        await self.acc.client.close()
        self.acc.boya_client.close()

    async def test_repeated_page_reads_share_auth_failure_cooldown(self):
        acquire = Mock(side_effect=RuntimeError('synthetic service outage'))
        with patch.object(self.acc.boya_client, 'acquire_token', acquire):
            for _ in range(4):
                result = await backend.get_boya_courses(username=self.acc.username)
                self.assertTrue(result['stale'])
        self.assertEqual(acquire.call_count, 1)

    async def test_explicit_cached_view_does_not_renew_or_wait_on_school_lock(self):
        # Default API authentication contracts below stay intact. The browser
        # now explicitly asks for its view cache, not a school synchronization.
        with patch.object(self.acc.boya_client,'acquire_token') as acquire, patch.object(backend,'account_lock',side_effect=AssertionError('cache must not wait on network lock')):
            data=await backend.get_boya_courses(username=self.acc.username,cached=True)
        self.assertEqual(data['courses'],[])
        self.assertTrue(data['stale']);acquire.assert_not_called()

    async def test_captcha_on_page_read_stops_all_automatic_auth_paths(self):
        acquire = Mock(side_effect=BoyaApiError('captcha_required', 'synthetic challenge'))
        with patch.object(self.acc.boya_client, 'acquire_token', acquire):
            await backend.get_boya_courses(username=self.acc.username)
            await backend.get_boya_courses(username=self.acc.username)
        self.assertTrue(self.acc.auth_requires_input)
        self.assertEqual(acquire.call_count, 1)

    async def test_explicit_refresh_cannot_bypass_manual_input_pause(self):
        self.acc.auth_requires_input = True
        acquire = Mock(side_effect=RuntimeError('must not be called'))
        with patch.object(self.acc.boya_client, 'acquire_token', acquire):
            with self.assertRaises(backend.HTTPException):
                await backend.refresh_boya_data(username=self.acc.username)
        acquire.assert_not_called()

    async def test_parallel_page_reads_coalesce_successful_authentication(self):
        def acquire():
            time.sleep(.05)
            self.acc.boya_client.token = 'synthetic-refresh-token'
            return self.acc.boya_client.token
        with patch.object(self.acc.boya_client, 'acquire_token', side_effect=acquire) as call:
            results = await asyncio.gather(*(backend.get_boya_courses(username=self.acc.username) for _ in range(8)))
        self.assertTrue(all(not result['stale'] for result in results))
        self.assertEqual(call.call_count, 1)

    async def test_removed_or_connecting_identity_never_reacquires_from_page(self):
        for field in ('removed', 'maintenance'):
            setattr(self.acc, field, True)
            with patch.object(self.acc.boya_client, 'acquire_token') as acquire:
                try:
                    await backend.get_boya_courses(username=self.acc.username)
                except backend.HTTPException:
                    pass
                acquire.assert_not_called()
            setattr(self.acc, field, False)

    async def test_retry_only_after_cooldown_and_existing_token_stays_usable(self):
        acquire = Mock(side_effect=RuntimeError('synthetic outage'))
        with patch.object(self.acc.boya_client, 'acquire_token', acquire), patch('core.boya_scheduler.time.monotonic', return_value=1000):
            await backend.get_boya_courses(username=self.acc.username)
            await backend.get_boya_courses(username=self.acc.username)
            self.assertEqual(acquire.call_count, 1)
        with patch.object(self.acc.boya_client, 'acquire_token', acquire), patch('core.boya_scheduler.time.monotonic', return_value=1060):
            await backend.get_boya_courses(username=self.acc.username)
            self.assertEqual(acquire.call_count, 2)
        self.acc.boya_client.token = 'synthetic-recovered-token'
        with patch.object(self.acc.boya_client, 'acquire_token') as acquire:
            result = await backend.get_boya_courses(username=self.acc.username)
            self.assertFalse(result['stale'])
            acquire.assert_not_called()

    async def test_regular_auth_cooldown_also_blocks_cookie_reauthentication(self):
        self.acc.auth_retry_after = time.monotonic() + 60
        with patch.object(self.acc.boya_client, 'acquire_token') as acquire:
            self.assertTrue((await backend.get_boya_courses(username=self.acc.username))['stale'])
            acquire.assert_not_called()
