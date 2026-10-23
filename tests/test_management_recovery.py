import concurrent.futures
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.management_store import ManagementStore
from server.management import install


class RecoveryContracts(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'TESTING': '1', 'BUAA_RUNTIME_MODE': 'headless',
            'BUAA_CONFIG_FILE': str(Path(self.directory.name)/'config.json'),
            'BUAA_ADMIN_PASSWORD': '', 'BUAA_ALLOWED_HOSTS': ''})
        self.env.start()
        self.store = ManagementStore()
        self.app = FastAPI(); install(self.app)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close(); self.env.stop(); self.directory.cleanup()

    def setup(self):
        result = self.client.post('/api/management/setup', json={'password':'test-password', 'proof':self.store.bootstrap_token()})
        self.assertEqual(result.status_code, 200)
        return result.json()

    def test_first_claim_requires_deployment_secret_and_recovery_is_hashed(self):
        state = self.client.get('/api/session')
        self.assertEqual(state.status_code, 401); self.assertTrue(state.json()['setup_required'])
        bad = self.client.post('/api/management/setup',json={'password':'test-password', 'proof':'wrong'})
        self.assertEqual(bad.status_code, 403)
        data = self.setup(); raw=self.store.path.read_text()
        self.assertNotIn(data['recovery_code'], raw); self.assertNotIn('test-password', raw)
        self.assertEqual(self.client.post('/api/management/setup',json={'password':'other-password','proof':self.store.bootstrap_token()}).status_code,409)
        self.assertEqual(self.client.get('/api/session').json()['csrf'],data['csrf'])

    def test_reset_persists_invalidates_sessions_password_and_recovery(self):
        before = self.setup()
        other=TestClient(self.app)
        other.post('/api/session',json={'password':'test-password'})
        after=self.client.post('/api/management/reset',json={'password':'new-password', 'proof':before['recovery_code']})
        self.assertEqual(after.status_code,200)
        self.assertEqual(other.get('/api/session').status_code,401)
        self.assertFalse(self.store.verify('test-password')); self.assertTrue(ManagementStore().verify('new-password'))
        self.assertEqual(self.client.post('/api/management/reset',json={'password':'third-password','proof':before['recovery_code']}).status_code,401)
        other.close()

    def test_existing_env_password_preserved_until_explicit_authenticated_rotation(self):
        with patch.dict(os.environ, {'BUAA_ADMIN_PASSWORD':'old-env-password'}):
            app=FastAPI();install(app)
        with TestClient(app) as client:
            self.assertFalse(client.get('/api/session').json()['setup_required'])
            csrf=client.post('/api/session',json={'password':'old-env-password'}).json()['csrf']
            body={'password':'new-password','proof':'old-env-password'}
            self.assertEqual(client.post('/api/management/password',json=body).status_code,403)
            changed=client.post('/api/management/password',json=body,headers={'X-BUAA-CSRF':csrf})
            self.assertEqual(changed.status_code,200)
            self.assertTrue(changed.json()['recovery_code'])
            client.cookies.clear()
            self.assertEqual(client.post('/api/session',json={'password':'old-env-password'}).status_code,401)
            self.assertEqual(client.post('/api/session',json={'password':'new-password'}).status_code,200)

    def test_reset_rate_origin_body_limits(self):
        self.assertEqual(self.client.post('/api/management/reset',content=b' '*16385).status_code,413)
        self.assertEqual(self.client.post('/api/management/setup',headers={'Origin':'https://evil.example'},json={}).status_code,403)
        for i in range(5):
            self.assertEqual(self.client.post('/api/management/reset',json={'password':'new-password','proof':'wrong'}).status_code,401)
        self.assertEqual(self.client.post('/api/management/reset',json={'password':'new-password','proof':'wrong'}).status_code,429)

    def test_disk_failure_preserves_credentials_and_corruption_fails_closed(self):
        data=self.setup(); original=self.store.path.read_bytes()
        with patch('core.management_store.os.replace',side_effect=OSError('synthetic full disk')):
            result=self.client.post('/api/management/reset',json={'password':'new-password','proof':data['recovery_code']})
        self.assertEqual(result.status_code,503);self.assertEqual(self.store.path.read_bytes(),original)
        self.store.path.write_text('{}')
        with self.assertRaises(ValueError):install(FastAPI())

    def test_concurrent_first_claim_has_one_winner(self):
        def claim(i):
            try:
                return ManagementStore().set_password('password-'+str(i),first=True)
            except (ValueError,FileExistsError):return None
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(claim,range(2)))
        self.assertEqual(sum(bool(x) for x in results),1)
        self.assertEqual(len(list(Path(self.directory.name).glob('.management-*'))),1)


if __name__=='__main__':unittest.main()
