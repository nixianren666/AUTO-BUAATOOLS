import unittest
from urllib.parse import parse_qs, urlsplit

import httpx

from core.iclass import IclassClient
from core.webvpn import from_webvpn_url


FORM = '<form id="loginForm"><input name="execution" value="fixture-execution"></form>'
MFA = FORM + '<script>config.mfa = {type:"sms"};</script>'
FIXTURE_USER = "00000001"


class SMSLoginTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self, mode, handler):
        client = IclassClient(mode)
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.close)
        return client

    async def test_explicit_school_sms_direct_and_webvpn_with_single_use(self):
        for mode in ("direct", "webvpn"):
            requests = []

            def handle(request):
                raw = urlsplit(from_webvpn_url(str(request.url)))
                self.assertEqual(request.url.host == "d.buaa.edu.cn", mode == "webvpn")
                requests.append((request.method, raw.path))
                if raw.path == "/token":
                    self.assertEqual(request.content, b'{"username":"00000001"}')
                    return httpx.Response(200, json={"status": "success", "expire_in": 180})
                if raw.path == "/login" and request.method == "POST":
                    data = parse_qs(request.content.decode())
                    self.assertEqual(data["type"], ["username_smstoken"])
                    self.assertEqual(data["password"], ["010203"])
                    return httpx.Response(302, headers={"Location": "https://uc.buaa.edu.cn/"})
                if raw.path == "/login":
                    return httpx.Response(200, text=FORM)
                if raw.path == "/api/uc/status":
                    return httpx.Response(200, json={"code": 0, "data": {"schoolid": FIXTURE_USER}})
                return httpx.Response(200)

            client = self.fixture(mode, handle)
            result = await client.send_sms_code(FIXTURE_USER)
            self.assertEqual(result["status"], "sms_sent")
            ticket = result["sms_challenge"]
            self.assertEqual((await client.verify_sms_code("00000002", ticket, "010203"))["status"], "failed")
            self.assertEqual(len(requests), 2)
            self.assertEqual((await client.verify_sms_code(FIXTURE_USER, ticket, "010203"))["status"], "success")
            self.assertEqual((await client.verify_sms_code(FIXTURE_USER, ticket, "010203"))["status"], "failed")
            self.assertEqual(requests.count(("POST", "/login")), 1)
            self.assertEqual(requests.count(("POST", "/token")), 1)
            self.assertIsNone(client._sms_form)

    async def test_conditional_challenge_never_sends_sms_or_activates_business(self):
        requests = []

        def handle(request):
            requests.append((request.method, request.url.path))
            return httpx.Response(200, text=MFA if request.method == "POST" else FORM)

        client = self.fixture("direct", handle)
        result = await client.login_sso(FIXTURE_USER, "fixture-password")
        self.assertEqual(result["status"], "sms_required")
        self.assertFalse(client.is_authenticated())
        self.assertEqual(requests, [("GET", "/login"), ("POST", "/login")])

    async def test_ambiguous_password_post_never_switches_route(self):
        def handle(request):
            if request.method == "POST":
                raise httpx.ReadTimeout("synthetic timeout")
            return httpx.Response(200, text=FORM)

        client = self.fixture("direct", handle)
        result = await client.login_sso(FIXTURE_USER, "fixture-password")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result.get("retry_other_route"))

    async def test_old_risk_continue_form_never_posts_ignore_and_continue(self):
        for notice in ("账号存在安全风险，请修改密码", "密码过期，账号存在安全风险", "学校要求核对"):
            requests = []

            def handle(request):
                requests.append(request)
                if request.method == "POST":
                    return httpx.Response(200, text=FORM.replace("loginForm", "continueForm") + notice)
                return httpx.Response(200, text=FORM)

            client = self.fixture("direct", handle)
            result = await client.login_sso(FIXTURE_USER, "fixture-password")
            self.assertEqual(result["status"], "verification_required")
            self.assertEqual([request.method for request in requests], ["GET", "POST"])

    async def test_ambiguous_sms_submission_consumes_challenge(self):
        requests = []

        def handle(request):
            requests.append((request.method, request.url.path))
            if request.url.path == "/token":
                return httpx.Response(200, json={"status": "success", "expire_in": 180})
            if request.method == "POST":
                raise httpx.ReadTimeout("synthetic timeout")
            return httpx.Response(200, text=FORM)

        client = self.fixture("direct", handle)
        ticket = (await client.send_sms_code(FIXTURE_USER))["sms_challenge"]
        with self.assertRaises(httpx.ReadTimeout):
            await client.verify_sms_code(FIXTURE_USER, ticket, "010203")
        self.assertEqual((await client.verify_sms_code(FIXTURE_USER, ticket, "010203"))["status"], "failed")
        self.assertEqual(requests.count(("POST", "/login")), 1)
