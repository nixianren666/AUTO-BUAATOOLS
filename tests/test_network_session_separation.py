"""Transient routing failures must not become password submissions or writes."""
import asyncio
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from core.iclass import IclassClient, IclassReadError, IclassSessionExpired
from core.scheduler import SigninScheduler
from core.boya_scheduler import BoyaScheduler
from core.boya_client import BoyaApiError, BoyaSessionExpired
from core.webvpn import to_webvpn_url
from server import app as backend


class ClassroomReadFailures(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = IclassClient()
        self.client.user_id = 'synthetic-user'
        self.client.session_id = 'synthetic-session'
        self.client.user_info = {'schoolid': 'fixture-network-student'}
        self.requests = []

    async def asyncTearDown(self):
        await self.client.close()

    async def transport(self, handler):
        if self.client._client:
            await self.client._client.aclose()
        def respond(request):
            self.requests.append(request)
            return handler(request)
        self.client._client = httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False)

    async def test_transport_failures_keep_existing_identity(self):
        for error in (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError):
            with self.subTest(error=error.__name__):
                def fail(request):
                    raise error('synthetic tunnel interruption')
                await self.transport(fail)
                with self.assertRaises(IclassReadError):
                    await self.client.get_today_classes()
                self.assertEqual(self.client.session_id, 'synthetic-session')
                self.assertEqual(self.client.user_id, 'synthetic-user')
        self.assertTrue(all(r.method == 'GET' for r in self.requests))

    async def test_unknown_responses_do_not_invent_authentication_expiry(self):
        cases = [httpx.Response(503), httpx.Response(403), httpx.Response(200, text='<html>temporary gateway page</html>'),
                 httpx.Response(200, json=[]), httpx.Response(200, json={}),
                 httpx.Response(200, json={'STATUS': 'temporarily-busy', 'ERRMSG': 'synthetic busy'}),
                 httpx.Response(200, json={'STATUS': '0', 'result': None})]
        for response in cases:
            with self.subTest(status=response.status_code, body=response.content[:30]):
                await self.transport(lambda request: response)
                with self.assertRaises(IclassReadError):
                    await self.client.get_today_classes()
                self.assertEqual(self.client.session_id, 'synthetic-session')

    async def test_http_401_stops_before_fallback_port_and_invalidates_session(self):
        await self.transport(lambda r: httpx.Response(401))
        with self.assertRaises(IclassSessionExpired):
            await self.client.get_today_classes()
        self.assertIsNone(self.client.session_id)
        self.assertEqual(len(self.requests), 1)

    async def test_exact_no_schedule_envelope_is_empty_without_reauthentication(self):
        await self.transport(lambda r: httpx.Response(200, json={'STATUS': '2'}))
        self.assertEqual(await self.client.get_today_classes(), [])
        self.assertEqual(self.client.session_id, 'synthetic-session')
        self.assertEqual(self.client.user_id, 'synthetic-user')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].method, 'GET')

    async def test_no_schedule_status_does_not_hide_errors_or_contradictory_data(self):
        for payload in ({'STATUS': '2', 'ERRMSG': 'synthetic unavailable'},
                        {'STATUS': '2', 'result': [{'id': '1001'}]},
                        {'STATUS': '2', 'result': None}, {'STATUS': 2},
                        {'STATUS': '3'}, {'STATUS': '2', 'total': 1}):
            with self.subTest(payload=payload):
                await self.transport(lambda r: httpx.Response(200, json=payload))
                with self.assertRaises(IclassReadError):
                    await self.client.get_today_classes()
                self.assertEqual(self.client.session_id, 'synthetic-session')

    async def test_no_schedule_status_with_explicit_expiry_still_invalidates(self):
        await self.transport(lambda r: httpx.Response(200, json={'STATUS': '2', 'ERRMSG': '会话已失效，请重新登录'}))
        with self.assertRaises(IclassSessionExpired):
            await self.client.get_today_classes()
        self.assertIsNone(self.client.session_id)
        self.assertEqual(len(self.requests), 1)

    async def test_no_schedule_never_authorizes_cached_course_signin(self):
        self.client.operation_user = 'fixture-network-student'
        await self.transport(lambda r: httpx.Response(200, json={'STATUS': '2'}))
        result = await self.client.perform_signin('1001')
        self.assertFalse(result[0])
        self.assertEqual(self.client.actual_sign_posts, 0)
        self.assertTrue(all(r.method == 'GET' for r in self.requests))

    async def test_explicit_official_expiry_is_distinct_from_unknown_status(self):
        await self.transport(lambda r: httpx.Response(200, json={'STATUS': '-1', 'ERRMSG': '会话已失效，请重新登录'}))
        with self.assertRaises(IclassSessionExpired):
            await self.client.get_today_classes()
        self.assertIsNone(self.client.session_id)
        self.assertEqual(len(self.requests), 1)

    async def test_trusted_login_redirect_invalidates_without_following_it(self):
        for mode in ('direct', 'webvpn'):
            self.client.mode = mode
            self.client.user_id, self.client.session_id = 'synthetic-user', 'synthetic-session'
            self.requests.clear()
            target = 'https://sso.buaa.edu.cn/login'
            if mode == 'webvpn':
                target = to_webvpn_url(target)
            await self.transport(lambda r: httpx.Response(302, headers={'Location': target}))
            with self.assertRaises(IclassSessionExpired):
                await self.client.get_today_classes()
            self.assertEqual(len(self.requests), 1)

    async def test_untrusted_redirect_does_not_follow_or_use_credentials(self):
        await self.transport(lambda r: httpx.Response(302, headers={'Location': 'https://untrusted.invalid/login'}))
        with self.assertRaises(IclassReadError):
            await self.client.get_today_classes()
        self.assertEqual(self.client.session_id, 'synthetic-session')
        self.assertTrue(all(r.url.host == 'iclass.buaa.edu.cn' for r in self.requests))

    async def test_read_recovers_after_route_failure_without_reauthentication(self):
        online = False
        def respond(request):
            if not online:
                raise httpx.ConnectError('synthetic route unavailable')
            return httpx.Response(200, json={'STATUS': '0', 'result': []})
        await self.transport(respond)
        with self.assertRaises(IclassReadError):
            await self.client.get_today_classes()
        online = True
        self.assertEqual(await self.client.get_today_classes(), [])
        self.assertEqual(self.client.session_id, 'synthetic-session')
        self.assertEqual(len(self.requests), 3)

    async def test_failed_fresh_read_never_authorizes_a_signin_post(self):
        self.client.operation_user = 'fixture-network-student'
        await self.transport(lambda r: httpx.Response(503))
        with self.assertRaises(IclassReadError):
            await self.client.perform_signin('1001')
        self.assertTrue(all(r.method == 'GET' for r in self.requests))
        self.assertEqual(self.client.actual_sign_posts, 0)

    async def test_bootstrap_failure_does_not_invent_expired_sso(self):
        self.client.user_id = self.client.session_id = None
        await self.transport(lambda r: httpx.Response(503))
        with self.assertRaises(IclassReadError):
            await self.client.get_today_classes()
        self.assertTrue(self.client.user_info)
        self.assertTrue(all(r.method == 'GET' for r in self.requests))


class ReadAndWorkerAuthentication(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.acc = backend.AccountState('fixture-network-student', password='synthetic-password', remember=False, auto_checkin=True)
        self.acc.client.user_id, self.acc.client.session_id = 'synthetic-user', 'synthetic-session'
        self.acc.client.user_info = {'schoolid': self.acc.username}
        self.acc.boya_client.token = 'synthetic-boya-token'
        self.cache = [{'id': '1001', 'courseName': 'synthetic last-success course'}]
        self.acc.last_classes = list(self.cache)
        self.scope = patch.dict(backend.accounts, {self.acc.username: self.acc}, clear=True)
        self.scope.start()

    async def asyncTearDown(self):
        self.scope.stop()
        await self.acc.client.close()
        self.acc.boya_client.close()

    def item(self):
        return {'username': self.acc.username, 'name': 'synthetic student', 'client': self.acc.client, 'account': self.acc}

    async def test_page_transport_and_protocol_failures_keep_cache_and_other_module_auth(self):
        reconnect = AsyncMock(return_value=False)
        for error in (httpx.ReadTimeout('synthetic outage'), IclassReadError('synthetic malformed response')):
            with patch.object(self.acc.client, 'get_today_classes', AsyncMock(side_effect=error)), patch.object(backend, 'connect_single_account', reconnect):
                for _ in range(3):
                    result = await backend.get_today_classes(username=self.acc.username)
                    self.assertTrue(result['stale'])
                    self.assertEqual(
                        [{key: value for key, value in row.items() if key != 'auto_course'}
                         for row in result['classes']], self.cache)
                    self.assertEqual(result['classes'][0]['auto_course'], {
                        'supported': False, 'paused': False,
                        'semester_known': False, 'storage_error': False})
                    self.assertEqual(self.acc.last_classes, self.cache)
                    self.assertTrue(self.acc.regular_health['stale'])
                    self.assertEqual(self.acc.boya_client.token, 'synthetic-boya-token')
        reconnect.assert_not_awaited()

    async def test_explicit_page_expiry_reauthenticates_once_then_reads(self):
        read = AsyncMock(side_effect=[IclassSessionExpired('synthetic expiry'), []])
        reconnect = AsyncMock(return_value=True)
        with patch.object(self.acc.client, 'get_today_classes', read), patch.object(backend, 'connect_single_account', reconnect):
            result = await backend.get_today_classes(username=self.acc.username)
        reconnect.assert_awaited_once_with(self.acc)
        self.assertEqual(result['status'], 'success')
        self.assertFalse(self.acc.regular_health['stale'])

    async def test_successful_read_clears_stale_health_without_password_use(self):
        with patch.object(self.acc.client, 'get_today_classes', AsyncMock(side_effect=[IclassReadError('synthetic offline'), []])), patch.object(backend, 'connect_single_account', AsyncMock()) as reconnect:
            self.assertTrue((await backend.get_today_classes(username=self.acc.username))['stale'])
            self.assertEqual((await backend.get_today_classes(username=self.acc.username))['status'], 'success')
        reconnect.assert_not_awaited()
        self.assertFalse(self.acc.regular_health['stale'])
        self.assertIsNone(self.acc.regular_health['error'])

    async def test_no_schedule_read_replaces_previous_day_cache_and_clears_error(self):
        self.acc.regular_health['stale'] = True
        self.acc.client._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={'STATUS': '2'})), trust_env=False)
        with patch.object(backend, 'connect_single_account', AsyncMock()) as reconnect:
            result = await backend.get_today_classes(username=self.acc.username)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['classes'], [])
        self.assertEqual(self.acc.last_classes, [])
        self.assertFalse(self.acc.regular_health['stale'])
        self.assertEqual(self.acc.boya_client.token, 'synthetic-boya-token')
        reconnect.assert_not_awaited()

    async def test_no_schedule_worker_clears_old_cache_without_signing_or_reauth(self):
        self.acc.client._client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={'STATUS': '2'})), trust_env=False)
        reconnect = AsyncMock()
        scheduler = SigninScheduler(lambda: [], reconnect_account=reconnect)
        with patch.object(self.acc.client, 'perform_signin', AsyncMock()) as signin:
            await scheduler._check_account(self.item(), None)
        reconnect.assert_not_awaited()
        signin.assert_not_awaited()
        self.assertEqual(self.acc.last_classes, [])
        self.assertFalse(self.acc.regular_health['stale'])

    async def test_worker_route_failure_sends_neither_reauthentication_nor_signin(self):
        reconnect = AsyncMock(return_value=False)
        scheduler = SigninScheduler(lambda: [], reconnect_account=reconnect)
        with patch.object(self.acc.client, 'get_today_classes', AsyncMock(side_effect=IclassReadError('synthetic offline'))), patch.object(self.acc.client, 'perform_signin', AsyncMock()) as signin:
            await scheduler._check_account(self.item(), None)
        reconnect.assert_not_awaited()
        signin.assert_not_awaited()
        self.assertEqual(self.acc.last_classes, self.cache)
        self.assertTrue(self.acc.regular_health['stale'])

    async def test_worker_explicit_expiry_still_renews_once(self):
        reconnect = AsyncMock(return_value=True)
        scheduler = SigninScheduler(lambda: [], reconnect_account=reconnect)
        with patch.object(self.acc.client, 'get_today_classes', AsyncMock(side_effect=[IclassSessionExpired('synthetic expiry'), []])):
            await scheduler._check_account(self.item(), None)
        reconnect.assert_awaited_once_with(self.acc)
        self.assertFalse(self.acc.regular_health['stale'])

    async def test_worker_next_tick_recovers_existing_session_after_network_returns(self):
        reconnect = AsyncMock(return_value=True)
        scheduler = SigninScheduler(lambda: [], reconnect_account=reconnect)
        with patch.object(self.acc.client, 'get_today_classes', AsyncMock(side_effect=[IclassReadError('synthetic route change'), []])):
            await scheduler._check_account(self.item(), None)
            await scheduler._check_account(self.item(), None)
        reconnect.assert_not_awaited()
        self.assertFalse(self.acc.regular_health['stale'])

    async def test_boya_cookie_exchange_network_failure_never_falls_through_to_password(self):
        self.acc.boya_client.token = None
        worker = BoyaScheduler(lambda: [], lambda *a, **k: None)
        for error in (httpx.ConnectError('synthetic outage'), httpx.ReadTimeout('synthetic tunnel switch'), ValueError('synthetic malformed cookie response')):
            self.acc.boya_auth_retry_after = 0
            with patch.object(self.acc.boya_client, 'acquire_token', side_effect=error) as acquire, patch.object(self.acc.boya_client, 'login_with_credentials') as login:
                self.assertFalse(worker._renew_session(self.acc))
                self.assertFalse(worker._renew_session(self.acc))
                self.assertEqual(acquire.call_count, 1)
                login.assert_not_called()

    async def test_boya_cookie_exchange_can_recover_after_cooldown(self):
        self.acc.boya_client.token = None
        worker = BoyaScheduler(lambda: [], lambda *a, **k: None)
        def recover():
            self.acc.boya_client.token = 'synthetic-recovered-token'
            return self.acc.boya_client.token
        with patch.object(self.acc.boya_client, 'acquire_token', side_effect=httpx.ConnectError('synthetic outage')), patch.object(self.acc.boya_client, 'login_with_credentials') as login:
            self.assertFalse(worker._renew_session(self.acc))
            login.assert_not_called()
        self.acc.boya_auth_retry_after = time.monotonic() - 1
        with patch.object(self.acc.boya_client, 'acquire_token', side_effect=recover), patch.object(self.acc.boya_client, 'login_with_credentials') as login:
            self.assertTrue(worker._renew_session(self.acc))
            login.assert_not_called()

    async def test_boya_read_outage_preserves_token(self):
        def fail(request):
            raise httpx.ReadTimeout('synthetic network interruption')
        self.acc.boya_client.http_client.close()
        self.acc.boya_client.http_client = httpx.Client(transport=httpx.MockTransport(fail), trust_env=False)
        with self.assertRaises(httpx.ReadTimeout):
            self.acc.boya_client.query_statistics()
        self.assertEqual(self.acc.boya_client.token, 'synthetic-boya-token')

    async def test_worker_bootstrap_network_failure_does_not_submit_password(self):
        self.acc.client.user_id = self.acc.client.session_id = None
        reconnect = AsyncMock(return_value=True)
        scheduler = SigninScheduler(lambda: [], reconnect_account=reconnect)
        with patch.object(self.acc.client, 'login_iclass', AsyncMock(return_value=False)):
            await scheduler._check_account(self.item(), None)
        reconnect.assert_not_awaited()
        self.assertTrue(self.acc.regular_health['stale'])

    async def test_boya_unknown_exchange_result_does_not_submit_password(self):
        worker = BoyaScheduler(lambda: [], lambda *a, **k: None)
        for error in (None, BoyaApiError('cas_error', 'synthetic HTTP service failure'), BoyaApiError('token_acquire_failed', 'synthetic unknown response')):
            self.acc.boya_client.token = None
            self.acc.boya_auth_retry_after = 0
            with patch.object(self.acc.boya_client, 'acquire_token', side_effect=error, return_value=None), patch.object(self.acc.boya_client, 'login_with_credentials') as login:
                self.assertFalse(worker._renew_session(self.acc))
                login.assert_not_called()

    async def test_boya_http_and_generic_login_html_keep_token(self):
        for status, text in ((403, '<html>login temporarily blocked</html>'), (503, '<html><input name="execution" value="synthetic"></html>'), (200, '<html>login gateway unavailable</html>')):
            self.acc.boya_client.http_client.close()
            self.acc.boya_client.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text=text)), trust_env=False)
            with self.assertRaises((httpx.HTTPStatusError, ValueError)):
                self.acc.boya_client.query_statistics()
            self.assertEqual(self.acc.boya_client.token, 'synthetic-boya-token')

    async def test_boya_explicit_expiry_still_invalidates_token(self):
        for status, text in ((401, ''), (200, '<html><input name="execution" value="synthetic"></html>')):
            self.acc.boya_client.token = 'synthetic-boya-token'
            self.acc.boya_client.http_client.close()
            self.acc.boya_client.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text=text)), trust_env=False)
            with self.assertRaises(BoyaSessionExpired):
                self.acc.boya_client.query_statistics()
            self.assertIsNone(self.acc.boya_client.token)

    async def test_boya_actual_cas_form_allows_one_password_renewal(self):
        self.acc.boya_client.token = None
        self.acc.boya_client.http_client.close()
        self.acc.boya_client.http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='<html><input name="execution" value="synthetic"></html>')), trust_env=False)
        worker = BoyaScheduler(lambda: [], lambda *a, **k: None)
        with patch.object(self.acc.boya_client, 'login_with_credentials', return_value=None) as login:
            self.assertFalse(worker._renew_session(self.acc))
            self.assertFalse(worker._renew_session(self.acc))
            login.assert_called_once_with(self.acc.username, self.acc.password)

    async def test_boya_actual_cas_service_error_never_submits_password(self):
        self.acc.boya_client.token = None
        self.acc.boya_client.http_client.close()
        requests = []
        def unavailable(request):
            requests.append(request)
            return httpx.Response(503)
        self.acc.boya_client.http_client = httpx.Client(transport=httpx.MockTransport(unavailable), trust_env=False)
        worker = BoyaScheduler(lambda: [], lambda *a, **k: None)
        with patch.object(self.acc.boya_client, 'login_with_credentials') as login:
            self.assertFalse(worker._renew_session(self.acc))
            login.assert_not_called()
        self.assertTrue(requests)
        self.assertTrue(all(r.method == 'GET' for r in requests))
