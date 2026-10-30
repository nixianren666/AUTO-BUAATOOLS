"""Durable reminder outcomes and independent bounded sending; synthetic only."""
import asyncio,copy,datetime as dt,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from core.wechat import WechatNotifications
from core.wechat_protocol import BASE_URL,WechatError
from core.course_reminders import upcoming
from tests.test_course_reminders import NOW,COURSE,SEMESTER
from tests.test_wechat_notifications import FakeProtocol


class DeliveryAudit(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.folder=tempfile.TemporaryDirectory();self.p=FakeProtocol();self.users={'A','B'}
  self.patches=[patch('core.wechat.vault.encrypt',side_effect=lambda s:'enc:'+s),patch('core.wechat.vault.decrypt',side_effect=lambda s:s.removeprefix('enc:'))]
  for p in self.patches:p.start()
  self.e=WechatNotifications(Path(self.folder.name)/'.wechat-private',lambda u:u in self.users,self.p,
   course_reader=AsyncMock(return_value={'classes':[COURSE],'semester':SEMESTER}))
  self.e.clock=lambda:NOW
  self.e.bindings={u:{'base':BASE_URL,'token':'synthetic-token-'+u,'bot':'bot-'+u,'peer':'peer-'+u,
   'generation':('a' if u=='A' else 'b')*32,'context':'context-'+u,'cursor':'','enabled':True,'important_only':True,
   'paused_until':0,'course_reminders':True,'course_notices':{}} for u in self.users}
 async def asyncTearDown(self):
  await self.e.stop()
  for p in self.patches:p.stop()
  self.folder.cleanup()
 async def until(self,condition,timeout=4):
  async with asyncio.timeout(timeout):
   while not condition():await asyncio.sleep(.01)
 def recent(self,u='A'):return self.e.status(u)['reminder_recent'][0]
 async def reject(self,binding,text,identifier):
  self.p.sent.append((copy.deepcopy(binding),text,identifier));raise WechatError(-2)

 async def test_reminder_rejection_is_durable_and_separate_from_successful_course_sync(self):
  self.p.send=self.reject;await self.e.reminder_tick();self.e.launch('A')
  await self.until(lambda:self.recent()['state']=='rejected')
  row=self.recent();self.assertEqual(row['error_code'],-2);self.assertEqual(self.e.status('A')['course_sync'],'ok')
  self.assertTrue(self.e.status('A')['send_error']);self.assertGreater(self.e.status('A')['send_retry_in_seconds'],0)
  saved=self.e._read();self.assertEqual(next(iter(saved['A']['course_deliveries'].values()))['state'],'rejected')
  self.assertEqual(saved['A']['context'],'context-A') # -2 is not presumed session expiry.

 async def test_accepted_is_not_delivery_and_survives_restart_without_replay(self):
  await self.e.reminder_tick();self.e.launch('A');await self.until(lambda:self.recent()['state']=='accepted')
  await self.e.stop();self.users={'A'};await self.e.start();await asyncio.sleep(.05)
  self.assertEqual(self.recent()['state'],'accepted');self.assertEqual(len(self.p.sent),1)
  self.assertNotIn('delivered',str(self.e.status('A')))

 async def test_interrupted_queue_and_inflight_are_not_replayed_after_real_file_reload(self):
  await self.e.reminder_tick()
  updated=copy.deepcopy(self.e.bindings)
  next(iter(updated['B']['course_deliveries'].values()))['state']='sending'
  await self.e.save(updated);await self.e.start();await asyncio.sleep(.05)
  self.assertFalse(self.p.sent)
  for user in self.users:self.assertEqual(self.recent(user)['state'],'not_replayed')
  await self.e.reminder_tick();self.assertFalse(self.p.sent)

 async def test_old_registration_is_never_reported_as_sent(self):
  notice=upcoming(COURSE,NOW);self.e.bindings['A']['course_notices']={notice['key']:notice['expires']}
  self.assertEqual(self.recent()['state'],'registered_only');self.assertNotIn('error_code',self.recent())

 async def test_repeated_automatic_events_back_off_and_new_explicit_test_does_not_replay(self):
  self.e.course_reader=None # This contract counts only runtime-log deliveries.
  self.p.send=self.reject;self.e.launch('A');self.e.drain_task=asyncio.create_task(self.e.drain())
  for index in range(4):self.e.offer({'username':'A','level':'warning','category':'boya','message':'synthetic-'+str(index),'time':'09:45:00'})
  await self.until(lambda:self.e.status('A')['send_error']);await asyncio.sleep(1.1)
  self.assertEqual(len(self.p.sent),1);first=self.p.sent[0][2]
  await self.e.test('A');await self.until(lambda:len(self.p.sent)==2)
  self.assertNotEqual(self.p.sent[1][2],first)
  self.assertTrue(all(row[2]!=first for row in list(self.p.sent)[1:]))

 async def test_new_inbound_message_clears_cooldown_without_clearing_send_failure(self):
  self.e.health['A']={'send_error':True,'send_error_code':-2,'send_retry_at':time.monotonic()+300,'send_failures':4}
  async def updates(binding):
   return {'msgs':[{'from_user_id':binding['peer'],'to_user_id':binding['bot'],'message_type':1,'context_token':'fresh-context'}]}
  self.p.updates=updates;task=asyncio.create_task(self.e.poll('A'))
  try:
   await self.until(lambda:self.e.bindings['A']['context']=='fresh-context')
   self.assertEqual(self.e.status('A')['send_retry_in_seconds'],0);self.assertTrue(self.e.status('A')['send_error'])
   self.assertFalse(self.p.sent)
  finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

 async def test_slow_inflight_student_does_not_block_shared_drain_for_other_student(self):
  self.p.block=asyncio.Event();self.e.launch('A');self.e.launch('B')
  self.e.drain_task=asyncio.create_task(self.e.drain());await self.e.test('A');await self.p.started.wait()
  try:
   self.e.offer({'username':'A','level':'warning','category':'boya','message':'A-extra','time':'09:45:00'})
   self.e.offer({'username':'B','level':'warning','category':'regular','message':'B-independent','time':'09:45:00'})
   await self.until(lambda:any(binding['peer']=='peer-B' for binding,_,_ in self.p.sent))
   self.assertFalse(self.e.tasks['A'][1].done())
  finally:self.p.block.set()

 async def test_reminders_take_priority_over_log_burst_and_queue_eviction_is_recorded(self):
  await self.e.reminder_tick();await self.e.test('A')
  self.assertEqual(len(self.e.queues['A'][0]),6)
  for _ in range(110):await self.e.test('A')
  self.assertEqual(len(self.e.queues['A']),100);self.assertEqual(len(self.e.queues['A'][0]),6)
  self.assertTrue(any(row['state']=='queue_full' for row in self.e.status('A')['recent']))

 async def test_full_reminder_queue_drops_less_urgent_reminder_with_durable_reason(self):
  for index in range(101):
   course=dict(COURSE,courseSchedId=str(1000+index));notice=upcoming(course,NOW)
   await self.e.claim_reminder('A','a'*32,notice)
  self.assertEqual(len(self.e.queues['A']),100)
  rows=self.e.bindings['A']['course_deliveries'];self.assertEqual(sum(row['state']=='queue_full' for row in rows.values()),1)

 async def test_expired_reminder_after_send_cooldown_never_reaches_provider(self):
  await self.e.reminder_tick();self.e.health['A']={'send_retry_at':time.monotonic()+300}
  self.e.clock=lambda:NOW+dt.timedelta(minutes=15);self.e.health['A']['send_retry_at']=0;self.e.launch('A')
  await self.until(lambda:self.recent()['state']=='expired');self.assertFalse(self.p.sent)

 async def test_disable_records_unsent_reminder_and_does_not_replay_on_reenable(self):
  await self.e.reminder_tick();await self.e.configure('A',True,True,False)
  self.assertEqual(self.recent()['state'],'disabled');self.assertFalse(self.e.queues['A'])
  await self.e.configure('A',True,True,True);await self.e.reminder_tick();self.assertFalse(self.e.queues['A'])

 async def test_write_failure_before_send_never_calls_provider_or_loses_storage_warning(self):
  await self.e.reminder_tick()
  with patch.object(self.e,'_write',side_effect=OSError('synthetic disk failure')):
   self.e.launch('A');await self.until(lambda:self.e.storage_error)
  self.assertFalse(self.p.sent);self.assertTrue(self.e.status('A')['storage_error'])

 async def test_late_old_generation_delivery_cannot_replace_new_binding_diagnostics(self):
  await self.e.reminder_tick();entry=self.e.queues['A'][0]
  self.e.bindings['A']=dict(self.e.bindings['A'],generation='c'*32,course_notices={},course_deliveries={})
  await self.e.delivery('A',entry,'accepted');self.assertEqual(self.e.status('A')['reminder_recent'],[])

 async def test_cancellation_during_send_keeps_unknown_inflight_not_accepted(self):
  await self.e.reminder_tick();self.p.block=asyncio.Event();self.e.launch('A');await self.p.started.wait()
  self.assertEqual(self.recent()['state'],'sending');await self.e.stop()
  await self.e.start();await asyncio.sleep(.05);self.assertEqual(self.recent()['state'],'not_replayed')
  self.assertEqual(len(self.p.sent),1)

 async def test_malformed_delivery_record_fails_closed_and_never_exposes_payload(self):
  await self.e.reminder_tick();self.e.bindings['A']['course_deliveries']={'bad':{'state':'accepted'}}
  self.e._write(self.e.bindings)
  with self.assertRaises(ValueError):self.e._read()

 async def test_bad_snapshot_is_unavailable_and_does_not_suppress_other_student(self):
  async def reader(user):return {'classes':'malformed'} if user=='A' else {'classes':[COURSE]}
  self.e.course_reader=reader;await self.e.reminder_tick()
  self.assertEqual(self.e.status('A')['course_sync'],'unavailable');self.assertFalse(self.e.queues.get('A'))
  self.assertEqual(len(self.e.queues['B']),1)

 async def test_supervisor_restarts_dead_reminder_worker_without_frontend(self):
  await self.e.save(self.e.bindings);await self.e.start();old=self.e.reminder_task
  old.cancel();await asyncio.gather(old,return_exceptions=True)
  await self.until(lambda:self.e.reminder_task is not old,timeout=6) # Supervisor interval is five seconds.
  await self.until(lambda:self.e.status('A')['course_sync']=='ok')
  self.assertFalse(self.e.reminder_task.done())

 async def test_terminal_state_replaces_sending_row_without_halving_recent_capacity(self):
  for index in range(25):
   self.e.record('A',str(index),'sending');self.e.record('A',str(index),'accepted')
  self.assertEqual(len(self.e.status('A')['recent']),20)
  self.assertTrue(all(row['state']=='accepted' for row in self.e.status('A')['recent']))

 async def test_context_refreshed_during_metadata_write_is_used_for_actual_send(self):
  await self.e.reminder_tick();original=self.e.delivery
  async def delivery(user,entry,state,*args,**kwargs):
   result=await original(user,entry,state,*args,**kwargs)
   if state=='sending':self.e.bindings[user]['context']='latest-verified-context'
   return result
  with patch.object(self.e,'delivery',side_effect=delivery):
   self.e.launch('A');await self.until(lambda:self.recent()['state']=='accepted')
  self.assertEqual(self.p.sent[0][0]['context'],'latest-verified-context')

 async def test_start_deadline_crossed_during_metadata_write_does_not_send(self):
  await self.e.reminder_tick();original=self.e.delivery
  async def delivery(user,entry,state,*args,**kwargs):
   result=await original(user,entry,state,*args,**kwargs)
   if state=='sending':self.e.clock=lambda:NOW+dt.timedelta(minutes=15)
   return result
  with patch.object(self.e,'delivery',side_effect=delivery):
   self.e.launch('A');await self.until(lambda:self.recent()['state']=='expired')
  self.assertFalse(self.p.sent)

 async def test_accepted_outcome_survives_later_storage_recovery_without_resending(self):
  await self.e.reminder_tick();original=self.e._write
  def write(bindings):
   if any(row['state']=='accepted' for row in bindings['A'].get('course_deliveries',{}).values()):raise OSError('synthetic result disk failure')
   return original(bindings)
  with patch.object(self.e,'_write',side_effect=write):
   task=asyncio.create_task(self.e.sender('A'))
   try:await self.until(lambda:self.e.storage_error and self.recent()['state']=='accepted')
   finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
  await self.e.save(self.e.bindings)
  self.assertFalse(self.e.storage_error)
  self.assertEqual(next(iter(self.e._read()['A']['course_deliveries'].values()))['state'],'accepted')
  self.assertEqual(len(self.p.sent),1)

 async def test_uncertain_transport_result_is_durable_and_never_replayed(self):
  async def unknown(binding,text,identifier):
   self.p.sent.append((binding,text,identifier));raise WechatError(kind='transport')
  self.p.send=unknown;await self.e.reminder_tick();self.e.launch('A')
  await self.until(lambda:self.recent()['state']=='unconfirmed')
  await self.e.stop();self.users={'A'};await self.e.start();await asyncio.sleep(.05)
  self.assertEqual(len(self.p.sent),1);self.assertEqual(self.recent()['state'],'unconfirmed')

 async def test_reminder_claim_capacity_is_reported_instead_of_silently_looking_ready(self):
  expiry=upcoming(COURSE,NOW)['expires']
  self.e.bindings['A']['course_notices']={format(i,'064x'):expiry for i in range(512)}
  await self.e.reminder_tick()
  self.assertEqual(self.e.status('A')['course_sync'],'capacity');self.assertFalse(self.e.queues.get('A'))
  self.assertEqual(len(self.e.queues['B']),1)

 async def test_unrealistic_persisted_expiry_fails_closed_before_status_datetime_conversion(self):
  self.e.bindings['A']['course_notices']={'a'*64:1e200}
  self.e._write(self.e.bindings)
  with self.assertRaises(ValueError):self.e._read()

 async def test_old_runtime_pruning_claims_does_not_break_compatible_upgrade(self):
  await self.e.reminder_tick();updated=copy.deepcopy(self.e.bindings)
  updated['A']['course_notices']={} # v15 does not know the optional delivery map.
  self.e._write(updated);loaded=self.e._read()
  self.assertEqual(loaded['A']['course_deliveries'],{});self.assertTrue(loaded['B']['course_deliveries'])
  self.assertEqual(loaded['A']['token'],updated['A']['token'])
