"""Synthetic CAS/UC/iClass/BYKC chains. No real accounts or school requests."""
import asyncio
import json
import threading
import unittest
from urllib.parse import parse_qs, quote, urlsplit
from unittest.mock import patch

import httpx

from core.iclass import IclassClient
from core.boya_client import BoyaClient, BoyaApiError
from core.boya_crypto import BykcCrypto
from core.cas_transport import follow_auth_response, follow_auth_response_sync, CasFlowError
from core.webvpn import from_webvpn_url, to_webvpn_url

UC = 'https://uc.buaa.edu.cn/api/login?target=https%3A%2F%2Fuc.buaa.edu.cn%2F%23%2Fuser%2Flogin'
FORM = '<form><input name="execution" value="fixture-execution"><input name="type" value="username_password"></form>'
CAPTCHA = FORM + "<script>config.captcha = {type:'image',id:'fixture-captcha'}</script>"
local_crypto = threading.local()


def crypto_factory():
    local_crypto.current = BykcCrypto()
    return local_crypto.current


class School:
    def __init__(self, mode, preload=False, wrapped=False, fault=None, user='fixture-student'):
        self.mode, self.preload, self.wrapped, self.fault, self.user = mode, preload, wrapped, fault, user
        self.requests = []
        self.password_posts = self.continue_posts = self.captcha_gets = 0
        self.uc_ticket = False
        self.business_reads = []

    def redir(self, target, cookie=None, code=302):
        headers = {'location':target}
        if cookie:
            headers['set-cookie'] = cookie
        return httpx.Response(code, headers=headers)

    def handle(self, req):
        self.requests.append(req)
        assert req.url.scheme == 'https', 'Authentication must never send HTTP'
        assert req.url.host == 'd.buaa.edu.cn' if self.mode == 'webvpn' else req.url.host != 'd.buaa.edu.cn'
        raw = from_webvpn_url(str(req.url)); url = urlsplit(raw); query = parse_qs(url.query)
        if url.hostname == 'sso.buaa.edu.cn':
            if url.path == '/captcha':
                self.captcha_gets += 1
                return httpx.Response(200, content=b'fixture-image', headers={'content-type':'image/png'})
            if req.method == 'POST':
                data = parse_qs(req.content.decode())
                if data.get('_eventId') == ['ignoreAndContinue']:
                    self.continue_posts += 1
                    return self.redir('https://uc.buaa.edu.cn/')
                self.password_posts += 1
                assert data['username'] == [self.user]
                assert data['password'] == ['fixture password ']
                assert data['execution'] == ['fixture-execution']
                if self.fault == 'wrong-password':
                    return httpx.Response(200, text=FORM+'<div id="errorDiv">账号或密码错误</div>')
                if self.fault == 'captcha' and data.get('captcha') != ['fixture-answer']:
                    return httpx.Response(200, text=CAPTCHA+'<div id="errorDiv">验证码错误</div>')
                if self.fault == 'expiry':
                    return httpx.Response(200, text='<form id="continueForm"><input name="execution" value="fixture-expiry"></form>')
                return self.redir('https://uc.buaa.edu.cn/', 'TGC=fixture-sso; Secure; HttpOnly; Path=/')
            if not query.get('service'):
                if self.preload:
                    return self.redir('https://uc.buaa.edu.cn/', 'TGC=fixture-sso; Secure; HttpOnly; Path=/')
                if self.fault == 'captcha':
                    return httpx.Response(200, text=CAPTCHA)
                return httpx.Response(200, text=FORM)
            service = query['service'][0]
            if 'iclass.buaa.edu.cn' in service:
                return self.redir('https://iclass.buaa.edu.cn:8346/?loginName=fixture-login-name')
            if 'bykc.buaa.edu.cn' in service:
                return self.redir('https://bykc.buaa.edu.cn/sscv/cas/login?ticket=fixture-by-ticket')
            assert 'uc.buaa.edu.cn' in service
            return self.redir(UC+'&ticket=fixture-uc-ticket', code=308)
        if url.hostname == 'uc.buaa.edu.cn':
            if url.path in ('', '/'):
                return httpx.Response(404 if self.fault == 'uc-root-404' else 200, text='UC landing')
            if url.path == '/api/login':
                if self.fault == 'loop':
                    return self.redir(raw)
                if self.fault == 'missing-location':
                    return httpx.Response(302)
                if self.fault == 'hostile':
                    return self.redir('https://attacker.test/login?ticket=fixture')
                if self.fault == 'service-down':
                    return httpx.Response(503)
                if query.get('ticket') == ['fixture-uc-ticket']:
                    self.uc_ticket = True
                    path = urlsplit(to_webvpn_url('https://uc.buaa.edu.cn/')).path if self.mode == 'webvpn' else '/'
                    return self.redir('https://uc.buaa.edu.cn/', 'UCSESSION=fixture-uc; Secure; HttpOnly; Path='+path)
                if self.uc_ticket and 'UCSESSION=fixture-uc' in req.headers.get('cookie',''):
                    return self.redir('https://uc.buaa.edu.cn/')
                target = 'http://sso.buaa.edu.cn/login?service='+quote(UC,safe='')
                return self.redir(to_webvpn_url(target) if self.wrapped else target)
            if url.path == '/api/uc/status':
                ok = self.uc_ticket and 'UCSESSION=fixture-uc' in req.headers.get('cookie','')
                identity = '99999999' if self.fault == 'wrong-identity' else self.user
                return httpx.Response(200,json={'code':0,'data':{'name':'模拟学生','schoolid':identity}} if ok else {'code':10600,'data':None})
        if url.hostname == 'iclass.buaa.edu.cn':
            assert self.uc_ticket
            if url.path == '/':
                return self.redir('http://sso.buaa.edu.cn/login?service='+quote(raw,safe=''))
            if url.path == '/esp/auth/signIn':
                assert query.get('loginName') == ['fixture-login-name']
                return httpx.Response(200,json={'meta':{'code':'0'},'data':{'result':{'id':'fixture-user-id','sessionId':'fixture-session'}}})
            if url.path == '/app/course/get_stu_course_sched.action':
                assert req.headers['sessionId'] == 'fixture-session'
                assert query['id'] == ['fixture-user-id']
                self.business_reads.append('iclass-schedule')
                return httpx.Response(200,json={'STATUS':'0','result':[{'id':'101','courseName':'合成课堂','signStatus':0,'classBeginTime':'08:00','classEndTime':'09:00'}]})
        if url.hostname == 'bykc.buaa.edu.cn':
            assert self.uc_ticket
            if url.path in ('/sscv/cas/login','/cas-login'):
                if query.get('ticket'):
                    return self.redir('https://bykc.buaa.edu.cn/cas-login?token=fixture-token-'+self.user)
                return self.redir('http://sso.buaa.edu.cn/login?service='+quote('https://bykc.buaa.edu.cn/sscv/cas/login',safe=''))
            api = url.path.rsplit('/',1)[-1]
            assert req.method == 'POST' and api in {'queryStudentSemesterCourseByPage','getAllConfig','queryChosenCourse','queryStatisticByUserId'}, 'No school business writes are permitted'
            assert req.headers['authtoken'] == 'fixture-token-'+self.user
            self.business_reads.append(api)
            payload = local_crypto.current.decrypt_response(req.content)
            assert isinstance(payload,dict)
            course = {'id':201,'courseStartDate':'2026-10-22 09:00:00','courseEndDate':'2026-10-22 10:00:00','courseName':'合成博雅'}
            data = {'queryStudentSemesterCourseByPage':{'content':[course],'totalPages':1,'totalElements':1,'last':True},
                    'getAllConfig':{'semester':[{'semesterStartDate':'2026-01-01','semesterEndDate':'2026-12-31'}]},
                    'queryChosenCourse':{'courseList':[{'id':301,'courseInfo':course}]},
                    'queryStatisticByUserId':{'userInfo':{'name':'模拟学生'}}}[api]
            return httpx.Response(200,content=local_crypto.current.encrypt_plaintext(json.dumps({'status':'0','data':data}).encode()))
        raise AssertionError('Unexpected synthetic request, no network fallback')


class CompleteAuthentication(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, mode, preload=False, wrapped=False, fault=None):
        school = School(mode,preload,wrapped,fault)
        client = IclassClient(mode)
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(school.handle),follow_redirects=False)
        boya = BoyaClient(mode);boya.http_client.close()
        boya.http_client = httpx.Client(transport=httpx.MockTransport(school.handle),follow_redirects=False)
        boya.operation_user = school.user
        try:
            result = await client.login_sso(school.user,'fixture password ')
            self.assertEqual(result['status'],'success',result)
            self.assertTrue(await client.login_iclass())
            self.assertEqual((await client.get_today_classes())[0]['courseName'],'合成课堂')
            boya.sync_cookies_from(client.client.cookies)
            self.assertEqual(boya.acquire_token(),'fixture-token-'+school.user)
            with patch('core.boya_client.BykcCrypto',side_effect=crypto_factory),patch('core.domain.now',return_value=__import__('datetime').datetime(2026,10,21)):
                self.assertEqual(len(boya.query_courses()),1)
                self.assertEqual(len(boya.query_chosen_courses()),1)
                self.assertEqual(boya.query_statistics()['userInfo']['name'],'模拟学生')
            self.assertEqual(school.password_posts,0 if preload else 1)
            self.assertEqual(school.continue_posts,1 if fault=='expiry' else 0)
            self.assertEqual(set(school.business_reads),{'iclass-schedule','queryStudentSemesterCourseByPage','getAllConfig','queryChosenCourse','queryStatisticByUserId'})
            copied = [c for c in boya.http_client.cookies.jar if c.name == 'UCSESSION'][0]
            self.assertTrue(copied.secure)
            self.assertIn('HttpOnly',copied._rest)
        finally:
            await client.close();boya.close()

    async def test_direct_password_full_business_chain(self):await self.exercise('direct')
    async def test_direct_prelogged_full_business_chain(self):await self.exercise('direct',True)
    async def test_webvpn_password_raw_redirect_full_business_chain(self):await self.exercise('webvpn')
    async def test_webvpn_prelogged_wrapped_redirect_full_business_chain(self):await self.exercise('webvpn',True,True)
    async def test_password_expiry_continue_completes_ticket_exchange(self):await self.exercise('direct',fault='expiry')
    async def test_uc_root_404_is_not_mistaken_for_failed_identity(self):await self.exercise('direct',fault='uc-root-404')

    async def test_failed_new_attempt_clears_old_identity_and_never_reads_business(self):
        for fault in ['wrong-password','loop','missing-location','hostile','service-down','wrong-identity']:
            school=School('direct',fault=fault,user='12345678');client=IclassClient()
            client._client=httpx.AsyncClient(transport=httpx.MockTransport(school.handle))
            client.user_id=client.session_id='old';client.user_info={'schoolid':'old'}
            try:
                try:result=await client.login_sso(school.user,'fixture password ')
                except ValueError:result={'status':'failed'}
                self.assertEqual(result['status'],'failed',fault)
                self.assertFalse(client.is_authenticated(),fault)
                self.assertLessEqual(len(school.requests),14)
                self.assertEqual(school.business_reads,[])
            finally:await client.close()

    async def test_captcha_bound_to_same_page_account_and_mode_then_single_post(self):
        school=School('direct',fault='captcha');client=IclassClient()
        client._client=httpx.AsyncClient(transport=httpx.MockTransport(school.handle))
        try:
            first=await client.login_sso(school.user,'fixture password ')
            self.assertEqual(first['status'],'captcha_required');self.assertEqual(school.password_posts,0)
            wrong=await client.login_sso(school.user,'fixture password ','fixture-answer','wrong-challenge')
            self.assertEqual(wrong['status'],'captcha_required');self.assertEqual(school.password_posts,0)
            failed=await client.login_sso(school.user,'fixture password ','wrong-answer',wrong['captcha_id'])
            self.assertEqual(failed['status'],'captcha_required');self.assertEqual(school.password_posts,1)
            passed=await client.login_sso(school.user,'fixture password ','fixture-answer',failed['captcha_id'])
            self.assertEqual(passed['status'],'success');self.assertEqual(school.password_posts,2)
        finally:await client.close()


class SyncAuthentication(unittest.TestCase):
    def test_boya_standalone_password_renewal_direct_and_webvpn(self):
        for mode in ['direct','webvpn']:
            school=School(mode);boya=BoyaClient(mode);boya.http_client.close()
            boya.http_client=httpx.Client(transport=httpx.MockTransport(school.handle))
            try:
                self.assertEqual(boya.login_with_credentials(school.user,'fixture password '),'fixture-token-'+school.user)
                self.assertEqual(school.password_posts,1)
            finally:boya.close()

    def test_sync_loop_captcha_and_server_error_fail_closed(self):
        for fault in ['loop','missing-location','hostile','service-down','captcha','wrong-password','wrong-identity']:
            school=School('direct',fault=fault,user='12345678');boya=BoyaClient();boya.http_client.close()
            boya.http_client=httpx.Client(transport=httpx.MockTransport(school.handle))
            boya.token='old-token'
            try:
                with self.assertRaises((BoyaApiError,ValueError)):boya.login_with_credentials(school.user,'fixture password ')
                self.assertIsNone(boya.token)
                self.assertLessEqual(len(school.requests),14)
                self.assertEqual(school.business_reads,[])
            finally:boya.close()

    def test_token_is_not_taken_from_another_host_nested_query_or_error_location(self):
        boya=BoyaClient()
        try:
            self.assertIsNone(boya._extract_token('https://uc.buaa.edu.cn/?token=fixture'))
            self.assertIsNone(boya._extract_token('https://bykc.buaa.edu.cn/?service=https://nested.test/?token=fixture'))
            self.assertIsNone(boya._extract_token('https://bykc.buaa.edu.cn/?token=a&token=b'))
            self.assertEqual(boya._extract_token('https://bykc.buaa.edu.cn/#/cas-login?token=fixture'),'fixture')
        finally:boya.close()


class ApiAuthentication(unittest.IsolatedAsyncioTestCase):
    async def test_failed_login_clears_old_token_and_stops_automatic_attempts(self):
        from server import app as backend
        school=School('direct',fault='wrong-password');acc=backend.AccountState(school.user,remember=False,auto_checkin=False)
        acc.client._client=httpx.AsyncClient(transport=httpx.MockTransport(school.handle))
        acc.boya_client.token='old-token';acc.client.user_info={'schoolid':school.user}
        acc.boya_all_courses=[{'id':'historical-fixture'}]
        try:
            with patch.dict(backend.accounts,{school.user:acc},clear=True),patch.object(backend,'sync_config'):
                result=await backend.login(backend.LoginRequest(username=school.user,password='fixture password ',mode='direct',remember=False,auto_checkin=False))
                self.assertEqual(result['status'],'failed')
                self.assertFalse(acc.to_dict()['authenticated']);self.assertIsNone(acc.boya_client.token)
                self.assertTrue(acc.boya_health['stale']);self.assertTrue(acc.auth_requires_input)
                self.assertEqual(acc.boya_all_courses,[{'id':'historical-fixture'}])
                self.assertFalse(await backend.connect_single_account(acc))
                self.assertEqual(school.password_posts,1);self.assertEqual(school.business_reads,[])
        finally:await acc.client.close();acc.boya_client.close()

    async def test_parallel_accounts_have_separate_cookies_and_failure_state(self):
        from server import app as backend
        schools=[School('direct',user='fixture-alpha'),School('webvpn',user='fixture-beta')]
        students=[];original=backend.active_username
        for school in schools:
            acc=backend.AccountState(school.user,mode=school.mode,remember=False,auto_checkin=False)
            acc.client._client=httpx.AsyncClient(transport=httpx.MockTransport(school.handle))
            acc.boya_client.http_client.close();acc.boya_client.http_client=httpx.Client(transport=httpx.MockTransport(school.handle))
            students.append(acc)
        try:
            with patch.dict(backend.accounts,{a.username:a for a in students},clear=True),patch.object(backend,'sync_config'),patch('core.boya_client.BykcCrypto',side_effect=crypto_factory),patch('core.domain.now',return_value=__import__('datetime').datetime(2026,10,21)):
                results=await asyncio.gather(*(backend.login(backend.LoginRequest(username=a.username,password='fixture password ',mode=a.mode,remember=False,auto_checkin=False)) for a in students))
                self.assertTrue(all(r['boya_ready'] and r['iclass_ready'] for r in results))
                for acc in students:self.assertEqual(acc.boya_client.token,'fixture-token-'+acc.username)
                schools[0].fault='wrong-password'
                failed=await backend.login(backend.LoginRequest(username=students[0].username,password='fixture password ',mode='direct',remember=False,auto_checkin=False))
                self.assertEqual(failed['status'],'failed');self.assertIsNone(students[0].boya_client.token)
                self.assertEqual(students[1].boya_client.token,'fixture-token-'+students[1].username)
                self.assertFalse(students[1].auth_requires_input)
        finally:
            backend.active_username=original
            for acc in students:await acc.client.close();acc.boya_client.close()

    async def test_api_login_reports_business_reads_and_reconnect_shares_cooldown(self):
        from server import app as backend
        school=School('webvpn');acc=backend.AccountState(school.user,password='fixture password ',mode='webvpn',remember=False,auto_checkin=False)
        acc.client._client=httpx.AsyncClient(transport=httpx.MockTransport(school.handle))
        acc.boya_client.http_client.close();acc.boya_client.http_client=httpx.Client(transport=httpx.MockTransport(school.handle))
        original=backend.active_username
        try:
            with patch.dict(backend.accounts,{school.user:acc},clear=True),patch.object(backend,'sync_config'),patch('core.boya_client.BykcCrypto',side_effect=crypto_factory),patch('core.domain.now',return_value=__import__('datetime').datetime(2026,10,21)):
                result=await backend.login(backend.LoginRequest(username=school.user,password='fixture password ',mode='webvpn',remember=False,auto_checkin=False))
                self.assertTrue(result['iclass_ready']);self.assertTrue(result['boya_ready'])
                self.assertEqual(acc.last_classes[0]['courseName'],'合成课堂')
                self.assertEqual(len(acc.boya_all_courses),1);self.assertEqual(len(acc.boya_selected_courses),1)
                results=await asyncio.gather(*(backend.connect_single_account(acc) for _ in range(3)))
                self.assertEqual(sum(results),1)
                self.assertFalse(acc.maintenance)
                self.assertFalse(await backend.connect_single_account(acc))
        finally:
            backend.active_username=original
            await acc.client.close();acc.boya_client.close()

    async def test_api_captcha_stops_background_credential_retries(self):
        from server import app as backend
        school=School('direct',fault='captcha');acc=backend.AccountState(school.user,remember=False,auto_checkin=False)
        acc.client._client=httpx.AsyncClient(transport=httpx.MockTransport(school.handle))
        original=backend.active_username
        try:
            with patch.dict(backend.accounts,{school.user:acc},clear=True),patch.object(backend,'sync_config'):
                result=await backend.login(backend.LoginRequest(username=school.user,password='fixture password ',mode='direct',remember=False,auto_checkin=False))
                self.assertEqual(result['status'],'captcha_required');self.assertTrue(acc.auth_requires_input)
                self.assertFalse(await backend.connect_single_account(acc));self.assertEqual(school.password_posts,0)
        finally:
            backend.active_username=original
            await acc.client.close();acc.boya_client.close()
