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

if __name__ == "__main__":
    unittest.main()
