"""Long-lived notification faults; no UI, real credentials, messages or network."""
import asyncio,copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from core.wechat import WechatNotifications
from core.wechat_protocol import WechatProtocol,WechatError,BASE_URL
from tests.test_wechat_notifications import FakeProtocol

class ErrorDiagnostics(unittest.IsolatedAsyncioTestCase):
 async def test_server_longpoll_budget_is_bounded_and_per_binding(self):
  seen=[]
  p=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(lambda r:(seen.append(r.extensions['timeout']['read']) or httpx.Response(200,json={'msgs':[]})))))
  try:
   for hint in [60000,True,999999999,None]:await p.updates({'base':BASE_URL,'token':'synthetic','poll_timeout_ms':hint})
   self.assertEqual(seen,[63,38,38,38])
  finally:await p.close()
 async def test_numeric_business_error_kept_without_provider_secret(self):
  p=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'ret':-2,'errmsg':'private-context-and-token'}))))
  try:
   with self.assertRaises(WechatError) as caught:await p.updates({'base':BASE_URL,'token':'private','cursor':''})
   self.assertEqual(caught.exception.code,-2);self.assertEqual(caught.exception.kind,'business');self.assertNotIn('private',str(caught.exception))
  finally:await p.close()
 async def test_session_code_not_hidden_by_generic_ret(self):
  p=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'ret':-1,'errcode':-14}))))
  try:
   with self.assertRaises(WechatError) as caught:await p.qrcode()
   self.assertEqual(caught.exception.code,-14)
  finally:await p.close()
 async def test_http_failure_distinguished_from_uncertain_transport(self):
  for response,kind,code in [(httpx.Response(429),'http',429),(httpx.Response(200,text='not-json'),'payload',None)]:
   p=WechatProtocol(httpx.AsyncClient(transport=httpx.MockTransport(lambda r:response)))
   try:
    with self.assertRaises(WechatError) as caught:await p.qrcode()
    self.assertEqual((caught.exception.kind,caught.exception.code),(kind,code))
   finally:await p.close()

class Longevity(unittest.IsolatedAsyncioTestCase):
 async def test_successive_simulated_days_without_ui_expire_old_messages_and_keep_owners(self):
  import time
  from types import SimpleNamespace
  elapsed=[time.monotonic()];wall=[time.time()]
  # Replace this module's clock object, never asyncio's process-wide clock.
  clock=SimpleNamespace(monotonic=lambda:elapsed[0],time=lambda:wall[0])
  with patch('core.wechat.time',clock):
   for u in ['A','B']:self.e.launch(u)
   self.e.drain_task=asyncio.create_task(self.e.drain())
   for day in range(3):
    for u in ['A','B']:
     self.e.offer({'username':u,'category':'td' if day%2 else 'boya','level':'success','message':f'day-{day}-owner-{u}','time':'09:00:00'})
    await self.until(lambda:len(self.p.sent)==(day+1)*2)
    elapsed[0]+=86400;wall[0]+=86400
   self.e.bindings['A']['paused_until']=wall[0]+3600
   stale=await self.e.test('A');await self.e.test('B')
   await self.until(lambda:len(self.p.sent)==7)
   elapsed[0]+=601;wall[0]+=601
   await self.until(lambda:any(x['id']==stale['test_id'] and x['state']=='expired' for x in self.e.status('A')['recent']))
   self.e.bindings['A']['paused_until']=0
   await self.e.test('A');await self.until(lambda:len(self.p.sent)==8)
   self.assertEqual([x[0]['peer'] for x in self.p.sent].count('peer-A'),4)
   self.assertEqual([x[0]['peer'] for x in self.p.sent].count('peer-B'),4)
   self.assertNotIn(stale['test_id'],[x[2][-6:] for x in self.p.sent])
   for binding,text,_ in self.p.sent[:6]:
    self.assertIn('owner-[本人]',text)
    self.assertNotIn('owner-'+('B' if binding['peer']=='peer-A' else 'A'),text)

 async def test_start_is_idempotent_and_same_instance_restart_never_replays_old_queue(self):
  await self.e.save(self.e.bindings);await self.e.test('A');await self.e.stop();await self.e.start()
  await asyncio.sleep(.05);self.assertEqual(self.p.sent,[])
  drain=self.e.drain_task;workers=list(self.e.tasks['A']);await self.e.start()
  self.assertIs(self.e.drain_task,drain);self.assertEqual(self.e.tasks['A'],workers)
  await self.e.test('A');await self.until(lambda:len(self.p.sent)==1)
 async def test_server_poll_hint_is_independent_for_background_accounts(self):
  observed={'A':[],'B':[]}
  async def updates(binding):
   u=binding['peer'][-1];observed[u].append(binding.get('poll_timeout_ms'))
   return {'msgs':[],'longpolling_timeout_ms':60000 if u=='A' else 2000}
  self.p.updates=updates
  for u in ['A','B']:self.e.launch(u)
  await self.until(lambda:len(observed['A'])>=2 and len(observed['B'])>=2)
  self.assertEqual(observed['A'][:2],[None,60000]);self.assertEqual(observed['B'][:2],[None,2000])
 async def test_real_account_switch_route_and_log_pipeline_keep_background_students(self):
  from types import SimpleNamespace
  import server.app as app
  states={u:app.AccountState(u) for u in ['A','B']}
  for binding in self.e.bindings.values():binding['important_only']=True
  with patch.object(app,'accounts',states),patch.object(app,'active_username','A'),patch.object(app,'wechat_notifications',self.e),patch.object(app,'sync_config'),patch.object(app,'logs_list',[]):
   for u in ['A','B']:self.e.launch(u)
   self.e.drain_task=asyncio.create_task(self.e.drain())
   await app.switch_account(SimpleNamespace(username='B'))
   for category in ['regular','boya','td']:
    for u in ['A','B']:app.add_log('success',category+'-background-'+u,username=u,category=category)
   await self.until(lambda:len(self.p.sent)==6)
   self.assertEqual(app.active_username,'B')
   for binding,text,_ in self.p.sent:
    owner=binding['peer'][-1];self.assertIn('background-[本人]',text);self.assertNotIn('background-'+('B' if owner=='A' else 'A'),text)
   self.assertEqual([x[0]['peer'] for x in self.p.sent].count('peer-A'),3)
 async def test_disk_recovery_retries_write_even_with_unchanged_empty_poll(self):
  self.e.storage_error=True;self.e.launch('A');await self.e.test('A')
  await self.until(lambda:self.e.status('A')['last_send'])
  self.assertFalse(self.e.storage_error)
 async def asyncSetUp(self):
  self.d=tempfile.TemporaryDirectory();self.p=FakeProtocol();self.e=WechatNotifications(Path(self.d.name)/'.wechat-private',lambda u:u in {'A','B'},self.p)
  self.patches=[patch('core.wechat.vault.encrypt',side_effect=lambda s:'enc:'+s),patch('core.wechat.vault.decrypt',side_effect=lambda s:s.removeprefix('enc:'))]
  for p in self.patches:p.start()
  self.e.bindings={u:{'base':BASE_URL,'token':'t-'+u,'bot':'b-'+u,'peer':'peer-'+u,'generation':('a' if u=='A' else 'b')*32,'context':'c-'+u,'cursor':'','enabled':True,'important_only':False,'paused_until':0} for u in ['A','B']}
 async def asyncTearDown(self):
  await self.e.stop()
  for p in self.patches:p.stop()
  self.d.cleanup()
 async def until(self,fn):
  async with asyncio.timeout(5):
   while not fn():await asyncio.sleep(.02)
 async def test_successful_poll_cannot_mask_outbound_rejection_and_other_student_continues(self):
  original=self.p.send
  async def send(binding,*args):
   if binding['peer']=='peer-A':raise WechatError(-2)
   return await original(binding,*args)
  self.p.send=send
  for u in ['A','B']:self.e.launch(u);await self.e.test(u)
  await self.until(lambda:self.e.status('A')['send_error'] and self.e.status('B')['last_send'])
  await self.until(lambda:not self.e.health['A'].get('error') and self.e.status('A')['last_poll'])
  self.assertTrue(self.e.status('A')['connection_error']);self.assertEqual(self.e.status('A')['send_error_code'],-2)
  self.assertTrue(any(x['state']=='rejected' for x in self.e.status('A')['recent']))
  self.assertFalse(self.e.status('B')['connection_error'])
 async def test_unexpected_send_exception_recovers_next_event_without_replaying_old_one(self):
  calls=[]
  async def send(binding,text,identifier):
   calls.append(identifier)
   if len(calls)==1:raise RuntimeError('synthetic SDK fault')
   return {'ret':0}
  self.p.send=send;self.e.launch('A');await self.e.test('A')
  await self.until(lambda:self.e.status('A')['send_error']);await self.e.test('A')
  await self.until(lambda:self.e.status('A')['last_send'])
  self.assertEqual(len(calls),2);self.assertEqual(len(set(calls)),2);self.assertFalse(self.e.status('A')['send_error'])
 async def test_unexpected_poll_exception_does_not_permanently_stop_receive(self):
  calls=0
  async def updates(binding):
   nonlocal calls;calls+=1
   if calls==1:raise RuntimeError('synthetic SDK fault')
   return {'msgs':[{'from_user_id':binding['peer'],'to_user_id':binding['bot'],'message_type':1,'context_token':'renewed'}]}
  self.p.updates=updates;self.e.launch('A')
  await self.until(lambda:self.e.bindings['A']['context']=='renewed')
  self.assertFalse(self.e.status('A')['worker_error']);self.assertGreater(self.e.status('A')['last_inbound'],0)
 async def test_supervisor_restores_only_dead_worker_with_no_frontend_requests(self):
  self.e.launch('A');self.e.launch('B');oldA=self.e.tasks['A'][0];oldB=self.e.tasks['B'][0]
  oldA.cancel();await asyncio.gather(oldA,return_exceptions=True)
  self.e.drain_task=asyncio.create_task(self.e.drain())
  await self.until(lambda:self.e.tasks['A'][0] is not oldA)
  self.assertIs(self.e.tasks['B'][0],oldB)
  self.e.offer({'username':'A','category':'boya','level':'error','message':'background-A','time':'10:00:00'})
  self.e.offer({'username':'B','category':'td','level':'success','message':'background-B','time':'10:00:00'})
  await self.until(lambda:len(self.p.sent)==2)
  self.assertEqual({x[0]['peer'] for x in self.p.sent},{'peer-A','peer-B'})
 async def test_late_old_generation_expiry_cannot_invalidate_rebinding(self):
  started=asyncio.Event();release=asyncio.Event()
  async def updates(binding):started.set();await release.wait();raise WechatError(-14)
  self.p.updates=updates;task=asyncio.create_task(self.e.poll('A'));await started.wait()
  self.e.bindings['A']=dict(self.e.bindings['A'],generation='c'*32,context='new-context');release.set();await asyncio.wait_for(task,timeout=.5)
  self.assertEqual(self.e.bindings['A']['context'],'new-context');self.assertFalse(self.e.status('A')['session_expired'])
