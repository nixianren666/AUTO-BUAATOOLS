import asyncio
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from core.wechat import WechatNotifications
from core.wechat_protocol import WechatProtocol, WechatError, trusted_base, BASE_URL


class ProtocolContracts(unittest.IsolatedAsyncioTestCase):
    async def test_official_wire_format_and_secret_scope(self):
        seen=[]
        def respond(request):
            seen.append(request)
            return httpx.Response(200,json={'ret':0})
        protocol=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        await protocol.qrcode();await protocol.qr_status('private-qr')
        await protocol.send({'base':BASE_URL,'token':'private-token','peer':'peer-A','context':'context-A'},'hello','fixed-client-id')
        self.assertNotIn('authorization',seen[0].headers)
        self.assertEqual(json.loads(seen[0].content),{'local_token_list':[]})
        self.assertNotIn('authorizationtype',seen[1].headers)
        self.assertNotIn('x-wechat-uin',seen[1].headers)
        self.assertEqual(seen[2].headers['authorization'],'Bearer private-token')
        data=json.loads(seen[2].content)
        self.assertEqual(data['msg']['to_user_id'],'peer-A');self.assertEqual(data['msg']['context_token'],'context-A')
        self.assertEqual(data['msg']['client_id'],'fixed-client-id')
        self.assertEqual(data['base_info']['channel_version'],'2.4.10')
        self.assertTrue(all(r.url.host=='ilinkai.weixin.qq.com' for r in seen))
        await protocol.close()

    async def test_owner_pairing_digits_only_go_to_official_status_query(self):
        seen=[]
        protocol=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request:(seen.append(request) or httpx.Response(200,json={'status':'scaned'})))))
        await protocol.qr_status('synthetic-qr',BASE_URL,'123456')
        self.assertEqual(seen[0].url.params['verify_code'],'123456')
        self.assertEqual(seen[0].url.params['qrcode'],'synthetic-qr')
        self.assertNotIn('authorization',seen[0].headers)
        await protocol.close()

    async def test_untrusted_redirects_and_business_errors_fail_without_leaking_secrets(self):
        for target in ('http://ilinkai.weixin.qq.com','https://ilinkai.weixin.qq.com.evil.example','https://127.0.0.1',
            'https://user@ilinkai.weixin.qq.com','https://ilinkai.weixin.qq.com:444','https://ilinkai.weixin.qq.com/path',
            'https://ilinkai.weixin.qq.com:bad','https://[invalid',None):
            with self.assertRaises(WechatError):trusted_base(target)
        for response in (httpx.Response(302,headers={'Location':'https://evil.example'}),httpx.Response(200,json={'ret':-14,'errmsg':'private-token'}),
            httpx.Response(200,json=[]),httpx.Response(200,text='private-token')):
            p=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(lambda r:response)))
            with self.assertRaises(WechatError) as failure:
                await p.send({'base':BASE_URL,'token':'private-token','peer':'peer-A','context':'context-A'},'hello','id')
            self.assertNotIn('private-token',str(failure.exception));await p.close()

    async def test_optional_ret_success_is_only_submitted_not_delivery(self):
        protocol=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={}))))
        response=await protocol.send({'base':BASE_URL,'token':'private-token','peer':'peer-A','context':'context-A'},'hello','id')
        self.assertNotIn('ret',response)
        await protocol.close()

    async def test_oversize_response_bounded_and_missing_context_never_sends(self):
        requests=[]
        def respond(r):requests.append(r);return httpx.Response(200,content=b'x'*1048577)
        p=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(respond)))
        with self.assertRaises(WechatError):await p.qrcode()
        with self.assertRaises(WechatError):await p.send({},'hi','id')
        self.assertEqual(len(requests),1);await p.close()


class FakeProtocol:
    def __init__(self):
        self.sent=[];self.responses={};self.qr_count=0;self.block=None;self.started=asyncio.Event();self.fail=False
    async def qrcode(self):self.qr_count+=1;return {'qrcode':'qr-'+str(self.qr_count),'qrcode_img_content':'https://official.example/synthetic'}
    async def qr_status(self,qr,base,verify_code=None):return self.responses.get(qr,{'status':'wait'})
    async def updates(self,binding):
        await asyncio.sleep(.03)
        return {'ret':0,'msgs':[]}
    async def send(self,binding,text,identifier):
        self.sent.append((copy.deepcopy(binding),text,identifier));self.started.set()
        if self.block and binding['peer']=='peer-A':await self.block.wait()
        if self.fail:raise WechatError()
        return {'ret':0}
    async def close(self):pass


class NotificationContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'.wechat-private'
        self.protocol=FakeProtocol();self.students={'A','B'}
        self.engine=WechatNotifications(self.path,lambda u:u in self.students,self.protocol)
        # Test crypto is explicitly local and reversible, not a deployment key.
        self.encrypt=patch('core.wechat.vault.encrypt',side_effect=lambda x:'encrypted:'+x);self.encrypt.start()
        self.decrypt=patch('core.wechat.vault.decrypt',side_effect=lambda x:x.removeprefix('encrypted:'));self.decrypt.start()

    async def asyncTearDown(self):
        await self.engine.stop();self.encrypt.stop();self.decrypt.stop();self.directory.cleanup()

    def binding(self,user):
        return {'base':BASE_URL,'token':'token-'+user,'bot':'bot-'+user,'peer':'peer-'+user,'generation':user*32,
            'context':'context-'+user,'cursor':'','enabled':True,'important_only':False,'paused_until':0}

    async def until(self,check):
        async with asyncio.timeout(4):
            while not check():await asyncio.sleep(.03)

    async def test_two_students_isolate_messages_and_global_log_never_forwarded(self):
        self.engine.bindings={u:self.binding(u) for u in ('A','B')}
        for u in self.engine.bindings:self.engine.launch(u)
        self.engine.drain_task=asyncio.create_task(self.engine.drain())
        for u in ('A','B',''):
            self.engine.offer({'username':u,'message':'message-'+u,'level':'error','category':'boya','time':'10:00'})
        await self.until(lambda:len(self.protocol.sent)==2)
        self.assertEqual({s[0]['peer'] for s in self.protocol.sent},{'peer-A','peer-B'})
        self.assertTrue(all(s[1].count('message-')==1 for s in self.protocol.sent))
        self.assertFalse(any(s[1].endswith('message-') for s in self.protocol.sent))

    async def test_one_slow_wechat_does_not_block_other_students_or_log_offer(self):
        self.protocol.block=asyncio.Event()
        self.engine.bindings={u:self.binding(u) for u in ('A','B')}
        for u in self.engine.bindings:self.engine.launch(u);await self.engine.test(u)
        await self.until(lambda:len(self.protocol.sent)==2)
        self.assertTrue(any(r['state']=='accepted' for r in self.engine.status('B')['recent']))
        self.protocol.block.set()

    async def test_ambiguous_send_never_replayed(self):
        self.protocol.fail=True;self.engine.bindings={'A':self.binding('A')};self.engine.launch('A')
        await self.engine.test('A');await self.until(lambda:self.engine.status('A')['recent'][0]['state']=='unconfirmed' if self.engine.status('A')['recent'] else False)
        await asyncio.sleep(1.2);self.assertEqual(len(self.protocol.sent),1)

    async def test_optional_confirmation_is_submitted_and_not_replayed(self):
        async def send(*args):return {}
        self.protocol.send=send;self.engine.bindings={'A':self.binding('A')};self.engine.launch('A')
        await self.engine.test('A')
        await self.until(lambda:any(r['state']=='submitted' for r in self.engine.status('A')['recent']))
        self.assertFalse(any(r['state']=='accepted' for r in self.engine.status('A')['recent']))

    async def test_disable_waits_for_inflight_and_blocks_future_sends(self):
        self.protocol.block=asyncio.Event();self.engine.bindings={'A':self.binding('A')};self.engine.launch('A')
        await self.engine.test('A');await self.protocol.started.wait()
        disabled=asyncio.create_task(self.engine.configure('A',False,False))
        await asyncio.sleep(.05);self.assertFalse(disabled.done())
        self.protocol.block.set();await disabled
        self.assertFalse(self.engine.status('A')['enabled'])
        self.assertEqual(len(self.engine.queues['A']),0)
        with self.assertRaises(ValueError):await self.engine.test('A')

    async def test_qr_generation_and_duplicate_owner_are_enforced(self):
        first=await self.engine.begin('A');second=await self.engine.begin('A')
        with self.assertRaises(ValueError):await self.engine.wait('A',first['binding_id'])
        self.protocol.responses['qr-2']={'status':'confirmed','bot_token':'private-token','ilink_bot_id':'bot-A','ilink_user_id':'peer-A','baseurl':BASE_URL}
        await self.engine.wait('A',second['binding_id']);self.assertTrue(self.engine.status('A')['bound'])
        self.assertFalse(self.engine.status('A')['ready'])
        await self.engine.begin('B');self.protocol.responses['qr-3']=dict(self.protocol.responses['qr-2'])
        with self.assertRaises(ValueError):await self.engine.wait('B',self.engine.pending['B']['id'])
        self.assertFalse(self.engine.status('B')['bound'])
        self.assertNotIn('private-token',json.dumps(self.engine.status('A')))

    async def test_wrong_student_or_deleted_student_cannot_claim_pending_login(self):
        first=await self.engine.begin('A')
        with self.assertRaises(ValueError):await self.engine.wait('B',first['binding_id'])
        self.students.remove('A')
        with self.assertRaises(ValueError):await self.engine.wait('A',first['binding_id'])

    async def test_disk_failure_does_not_enable_binding_or_change_existing(self):
        self.engine.bindings={'A':self.binding('A')};original=copy.deepcopy(self.engine.bindings)
        with patch.object(self.engine,'_write',side_effect=OSError('synthetic full disk')):
            with self.assertRaises(ValueError):await self.engine.configure('A',False,True)
        self.assertEqual(self.engine.bindings,original);self.assertTrue(self.engine.storage_error)

    async def test_context_only_from_bound_peer_and_bot_is_persisted(self):
        self.engine.bindings={'A':self.binding('A')};self.engine.bindings['A']['context']=''
        async def updates(binding):
            return {'msgs':[{'from_user_id':'peer-B','to_user_id':'bot-A','message_type':1,'context_token':'wrong'},
                {'from_user_id':'peer-A','to_user_id':'bot-A','message_type':1,'context_token':'correct'}],'get_updates_buf':'cursor-1'}
        self.protocol.updates=updates;self.engine.launch('A')
        await self.until(lambda:self.engine.bindings['A']['context']=='correct')
        self.assertEqual(self.engine._read()['A']['cursor'],'cursor-1')
        self.assertFalse(self.protocol.sent)

    async def test_session_expiry_pauses_without_cross_account_effect(self):
        self.engine.bindings={u:self.binding(u) for u in ('A','B')}
        async def updates(binding):
            if binding['peer']=='peer-A':raise WechatError(-14)
            return {'msgs':[]}
        self.protocol.updates=updates
        for u in self.engine.bindings:self.engine.launch(u)
        await self.until(lambda:self.engine.status('A')['session_expired'])
        self.assertFalse(self.engine.status('B')['session_expired']);self.assertFalse(self.engine.status('A')['ready'])

    async def test_restart_has_no_historical_outbox_and_keeps_private_binding(self):
        await self.engine.save({'A':self.binding('A')});await self.engine.test('A')
        second=WechatNotifications(self.path,lambda u:False,FakeProtocol())
        await second.start()
        self.assertTrue(second.status('A')['bound']);self.assertEqual(second.status('A')['queued'],0)
        await second.stop()

    async def test_format_redacts_links_identifiers_credentials_and_queue_is_bounded(self):
        entry={'username':'12345678','message':'12345678 token=secret https://private.example/key 密码:secret2 {"password":"hidden value"} Bearer opaque TDL1.opaque','level':'error','category':'td','time':'12:00'}
        text=self.engine.text(entry)
        for secret in ('12345678','secret','private.example','hidden value','opaque'):self.assertNotIn(secret,text)
        self.assertIn('TD',text);self.assertIn('需要处理',text)
        self.engine.bindings={'A':self.binding('A')}
        for i in range(110):await self.engine.test('A')
        self.assertEqual(len(self.engine.queues['A']),100)


if __name__=='__main__':unittest.main()
