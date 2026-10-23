import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from server.management import install as management
from server.wechat import install as wechat
from tests.test_wechat_notifications import FakeProtocol


class WechatAPIBoundary(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'TESTING':'1','BUAA_CONFIG_FILE':str(Path(self.directory.name)/'config.json'),
            'BUAA_ADMIN_PASSWORD':'synthetic-admin-password','BUAA_RUNTIME_MODE':'headless'})
        self.env.start();self.app=FastAPI();management(self.app)
        self.engine=wechat(self.app,Path(self.directory.name)/'config.json',{'A':SimpleNamespace(removed=False),'B':SimpleNamespace(removed=False)})
        self.engine.protocol=FakeProtocol();self.client=TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None);self.env.stop();self.directory.cleanup()

    def login(self):
        csrf=self.client.post('/api/session',json={'password':'synthetic-admin-password'}).json()['csrf']
        self.client.headers['X-BUAA-CSRF']=csrf

    def test_anonymous_status_and_qr_private_and_csrf_required_for_binding(self):
        self.assertEqual(self.client.get('/api/wechat/status?username=A').status_code,401)
        self.assertEqual(self.client.get('/api/wechat/qrcode?username=A&binding_id='+'a'*32).status_code,401)
        self.client.post('/api/session',json={'password':'synthetic-admin-password'})
        self.assertEqual(self.client.post('/api/wechat/bind',json={'username':'A'}).status_code,403)

    def test_explicit_account_required_and_qr_cannot_be_read_from_another_account(self):
        self.login()
        self.assertEqual(self.client.get('/api/wechat/status').status_code,422)
        self.assertEqual(self.client.get('/api/wechat/status?username=unknown').status_code,404)
        result=self.client.post('/api/wechat/bind',json={'username':'A'}).json()
        self.assertEqual(self.client.get('/api/wechat/status?username=B').json()['bound'],False)
        query='&binding_id='+result['binding_id']
        self.assertEqual(self.client.get('/api/wechat/qrcode?username=B'+query).status_code,409)
        qr=self.client.get('/api/wechat/qrcode?username=A'+query)
        self.assertEqual(qr.status_code,200);self.assertTrue(qr.content.startswith(b'\x89PNG'))
        self.assertEqual(qr.headers['cache-control'],'no-store')
        self.assertEqual(self.client.post('/api/wechat/bind/status',json={'username':'B','binding_id':result['binding_id']}).status_code,409)

    def test_test_notification_requires_binding_and_strict_settings(self):
        self.login()
        self.assertEqual(self.client.post('/api/wechat/test',json={'username':'A'}).status_code,409)
        self.assertEqual(self.client.post('/api/wechat/settings',json={'username':'A','enabled':1,'important_only':True}).status_code,422)
        self.assertFalse(self.engine.protocol.sent)

    def test_pairing_digits_require_explicit_owner_and_strict_manual_input(self):
        self.login()
        pending=self.client.post('/api/wechat/bind',json={'username':'A'}).json()
        calls=[]
        async def status(qr,base,verify_code=None):
            calls.append(verify_code)
            return {'status':'need_verifycode' if not verify_code else 'scaned'}
        self.engine.protocol.qr_status=status
        body={'username':'A','binding_id':pending['binding_id']}
        self.assertEqual(self.client.post('/api/wechat/bind/status',json=body).json()['status'],'need_verifycode')
        for invalid in ('','wrong',123456,'1'*17):
            self.assertEqual(self.client.post('/api/wechat/bind/status',json=dict(body,verify_code=invalid)).status_code,422)
        self.assertEqual(self.client.post('/api/wechat/bind/status',json=dict(body,username='B',verify_code='123456')).status_code,409)
        self.assertEqual(self.client.post('/api/wechat/bind/status',json=dict(body,verify_code='123456')).json()['status'],'scaned')
        self.assertEqual(calls,[None,'123456'])
        self.assertNotIn('123456',str(self.engine.pending))


if __name__=='__main__':unittest.main()
