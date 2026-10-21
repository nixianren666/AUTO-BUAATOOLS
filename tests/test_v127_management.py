import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.management import install

class ManagementContracts(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"TESTING": "1", "BUAA_ADMIN_PASSWORD": "", "BUAA_ALLOWED_HOSTS": ""})
        self.env.start()
        app = FastAPI()
        install(app)
        @app.post("/api/write")
        def write():
            return {"ok": True}
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def test_no_management_session_denies_mutation(self):
        self.assertEqual(self.client.post("/api/write").status_code, 401)

    def test_cookie_alone_cannot_mutate(self):
        self.client.get("/api/session")
        self.assertEqual(self.client.post("/api/write").status_code, 403)

    def test_same_origin_cookie_and_csrf_can_mutate(self):
        csrf = self.client.get("/api/session").json()["csrf"]
        self.assertEqual(self.client.post("/api/write", headers={"X-BUAA-CSRF": csrf}).status_code, 200)

    def test_cross_site_bootstrap_and_dns_rebinding_denied(self):
        self.assertEqual(self.client.get("/api/session", headers={"Origin": "https://attacker.test"}).status_code, 403)
        self.assertEqual(self.client.get("/api/session", headers={"Host": "attacker.test"}).status_code, 403)
        self.assertEqual(self.client.options("/api/write", headers={"Origin": "https://attacker.test", "Access-Control-Request-Method": "POST"}).status_code, 403)

    def test_remote_management_requires_password(self):
        with patch.dict(os.environ, {"BUAA_ADMIN_PASSWORD": "synthetic-admin-secret"}):
            app = FastAPI()
            install(app)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/session").status_code, 401)
            self.assertEqual(client.post("/api/session", json={"password": "wrong"}).status_code, 401)
            good = client.post("/api/session", json={"password": "synthetic-admin-secret"})
            self.assertEqual(good.status_code, 200)
            self.assertTrue(good.json()["csrf"])

    def test_password_cookie_survives_reload_and_logout_requires_csrf(self):
        with patch.dict(os.environ, {"BUAA_ADMIN_PASSWORD": "synthetic-admin-secret"}):
            app = FastAPI(); install(app)
        with TestClient(app) as client:
            csrf = client.post('/api/session',json={'password':'synthetic-admin-secret'}).json()['csrf']
            self.assertEqual(client.get('/api/session').json()['csrf'],csrf)
            self.assertEqual(client.delete('/api/session').status_code,403)
            self.assertEqual(client.get('/api/session').status_code,200)
            self.assertEqual(client.delete('/api/session',headers={'X-BUAA-CSRF':csrf}).status_code,200)
            self.assertNotIn('buaa_session',client.cookies)
            self.assertEqual(client.get('/api/session').status_code,401)

    def test_password_unicode_malformed_and_rate_limit(self):
        with patch.dict(os.environ, {"BUAA_ADMIN_PASSWORD": "演示管理密码"}):
            app=FastAPI();install(app)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/session',json={'password':123}).status_code,422)
            self.assertEqual(client.post('/api/session',json={'password':'x'*1025}).status_code,422)
            self.assertEqual(client.post('/api/session',json={'password':'演示管理密码'}).status_code,200)
            for i in range(4):self.assertEqual(client.post('/api/session',json={'password':'错误'}).status_code,401)
            rate=client.post('/api/session',json={'password':'演示管理密码'})
            self.assertEqual(rate.status_code,429);self.assertGreater(int(rate.headers['Retry-After']),0)

    def test_expired_cookie_never_grants_access(self):
        with patch.dict(os.environ, {"BUAA_ADMIN_PASSWORD": "synthetic-admin-secret"}):
            app=FastAPI();install(app)
        with TestClient(app) as client,patch('server.management.time.monotonic',return_value=10):
            client.post('/api/session',json={'password':'synthetic-admin-secret'})
            with patch('server.management.time.monotonic',return_value=86411):
                self.assertEqual(client.get('/api/session').status_code,401)

    def test_public_login_body_limit_applies_before_json_and_to_chunked_bodies(self):
        with patch.dict(os.environ, {"BUAA_ADMIN_PASSWORD":"synthetic-admin-secret"}):
            app=FastAPI();install(app)
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/session',content=b' '*16385).status_code,413)
            self.assertEqual(client.post('/api/session',content=iter([b' '*8192,b' '*8193])).status_code,413)
            self.assertEqual(client.post('/api/session',json={'password':'synthetic-admin-secret'}).status_code,200)

    def test_loopback_no_password_reuses_cookie_remote_without_password_denied(self):
        first=self.client.get('/api/session')
        self.assertEqual(self.client.get('/api/session').json()['csrf'],first.json()['csrf'])
        self.client.cookies.clear()
        # The boundary reads actual peers, not untrusted forwarding headers.
        self.assertEqual(self.client.get('/api/session',headers={'X-Forwarded-For':'203.0.113.2'}).status_code,200)
        with TestClient(self.client.app,client=('203.0.113.2',1234)) as remote:
            self.assertEqual(remote.get('/api/session').status_code,401)
            self.assertFalse(remote.get('/api/session').json()['configured'])

if __name__ == "__main__":
    unittest.main()
