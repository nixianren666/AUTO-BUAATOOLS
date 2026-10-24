import asyncio
import copy
import datetime as dt
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch,AsyncMock
from core.course_reminders import upcoming
from core.wechat import WechatNotifications
from tests.test_wechat_notifications import FakeProtocol

NOW=dt.datetime(2026,10,26,9,45)
COURSE={'courseSchedId':'101','courseName':'合成课程','teacherName':'合成教师','classBeginTime':'10:00','classEndTime':'11:40','classroomName':'合成教室','signStatus':1}
SEMESTER={'semesterStartDate':'2026-09-07','semesterEndDate':'2027-01-17'}

class ReminderPayload(unittest.TestCase):
    def test_fifteen_minute_window_end_and_signed_courses(self):
        self.assertIsNone(upcoming(COURSE,NOW-dt.timedelta(seconds=1)))
        self.assertIsNotNone(upcoming(COURSE,NOW))
        self.assertIsNotNone(upcoming(COURSE,NOW+dt.timedelta(minutes=14,seconds=59)))
        self.assertIsNone(upcoming(COURSE,NOW+dt.timedelta(minutes=15)))

    def test_course_teacher_times_and_official_calendar_week(self):
        text=upcoming(COURSE,NOW,SEMESTER)['text']
        for word in ('合成课程','合成教师','10:00','11:40','合成教室','第8周','已同步校历'):self.assertIn(word,text)
        self.assertIn('周次待同步',upcoming(COURSE,NOW,{})['text'])
        self.assertIn('周次待同步',upcoming(COURSE,NOW,{'semesterStartDate':'2025-01-01','semesterEndDate':'2025-06-01'})['text'])

    def test_bad_dates_ids_and_unknown_end_never_invent_a_lesson(self):
        for changes in ({'classEndTime':None},{'classEndTime':'09:00'},{'classBeginTime':'2026-10-25 10:00'}, {'courseSchedId':True},{'classBeginTime':'unknown'}):
            self.assertIsNone(upcoming(dict(COURSE,**changes),NOW))
        self.assertNotEqual(upcoming(COURSE,NOW)['key'],upcoming(dict(COURSE,classBeginTime='10:01'),NOW+dt.timedelta(minutes=1))['key'])

class ReminderIsolation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.protocol=FakeProtocol();self.students={'A','B'}
        self.patches=[patch('core.wechat.vault.encrypt',side_effect=lambda x:'encrypted:'+x),patch('core.wechat.vault.decrypt',side_effect=lambda x:x.removeprefix('encrypted:'))]
        for p in self.patches:p.start()
        self.engine=WechatNotifications(Path(self.directory.name)/'.wechat-private',lambda u:u in self.students,self.protocol,course_reader=AsyncMock(return_value={'classes':[COURSE],'semester':SEMESTER}))
        self.engine.clock=lambda:NOW
        self.engine.bindings={u:{'base':'https://ilinkai.weixin.qq.com','token':'token-'+u,'bot':'bot-'+u,'peer':'peer-'+u,'generation':('a' if u=='A' else 'b')*32,'context':'context-'+u,'cursor':'','enabled':True,'important_only':True,'paused_until':0,'course_reminders':True} for u in self.students}

    async def asyncTearDown(self):
        await self.engine.stop()
        for p in self.patches:p.stop()
        self.directory.cleanup()

    async def test_two_students_and_concurrent_ticks_claim_once_each(self):
        await asyncio.gather(self.engine.reminder_tick(),self.engine.reminder_tick())
        for user in self.students:
            self.assertEqual(len(self.engine.queues[user]),1)
            self.assertEqual(len(self.engine.bindings[user]['course_notices']),1)
            self.assertIn('合成课程',self.engine.queues[user][0][2])

    async def test_restarting_and_reenabling_do_not_replay_claimed_reminder(self):
        await self.engine.reminder_tick();saved=self.engine._read()
        self.engine.bindings=saved;self.engine.queues.clear()
        await self.engine.configure('A',False,False,True);await self.engine.configure('A',True,True,True)
        await self.engine.reminder_tick();self.assertFalse(self.engine.queues.get('A'))

    async def test_disk_failure_never_enqueues_unclaimed_message(self):
        with patch.object(self.engine,'_write',side_effect=OSError('disk full')):await self.engine.reminder_tick()
        self.assertFalse(self.engine.queues);self.assertTrue(self.engine.storage_error)

    async def test_old_binding_and_paused_or_unready_never_read_or_send(self):
        for b in self.engine.bindings.values():b.pop('course_reminders')
        await self.engine.reminder_tick();self.engine.course_reader.assert_not_awaited()
        self.assertFalse(self.engine.status('A')['course_reminders'])
        self.engine.bindings['A'].update(course_reminders=True,context='')
        self.engine.bindings['B'].update(course_reminders=True,enabled=False)
        await self.engine.reminder_tick();self.engine.course_reader.assert_not_awaited()

    async def test_slow_or_failed_account_does_not_block_other_enqueue(self):
        gate=asyncio.Event()
        async def reader(user):
            if user=='A':await gate.wait();raise OSError('offline')
            return {'classes':[COURSE],'semester':SEMESTER}
        self.engine.course_reader=reader;task=asyncio.create_task(self.engine.reminder_tick())
        try:
            async with asyncio.timeout(2):
                while not self.engine.queues.get('B'):await asyncio.sleep(.01)
            self.assertFalse(task.done());gate.set();await task
        finally:gate.set();await task

    async def test_late_reader_after_account_removed_cannot_enqueue(self):
        gate=asyncio.Event();started=asyncio.Event()
        async def reader(user):started.set();await gate.wait();return {'classes':[COURSE]}
        self.engine.course_reader=reader;task=asyncio.create_task(self.engine.reminder_tick());await started.wait()
        self.students.clear();gate.set();await task;self.assertFalse(self.engine.queues)

    async def test_queued_reminder_expires_at_start_and_never_calls_provider(self):
        await self.engine.reminder_tick();self.engine.clock=lambda:NOW+dt.timedelta(minutes=15)
        task=asyncio.create_task(self.engine.sender('A'))
        try:
            async with asyncio.timeout(2):
                while not self.engine.results.get('A'):await asyncio.sleep(.01)
            self.assertEqual(self.engine.results['A'][0]['state'],'expired');self.assertFalse(self.protocol.sent)
        finally:task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_disable_reminder_before_send_prevents_provider_call(self):
        await self.engine.reminder_tick();await self.engine.configure('A',True,True,False)
        self.assertFalse(self.engine.queues['A'])
        await self.engine.configure('A',True,True,True);await self.engine.reminder_tick()
        self.assertFalse(self.engine.queues['A']);self.assertFalse(self.protocol.sent)

    async def test_claim_storage_is_encrypted_and_malformed_claims_fail_closed(self):
        await self.engine.reminder_tick();self.assertTrue(self.engine.path.read_text().startswith('encrypted:'))
        self.engine.bindings['A']['course_notices']={'bad':True};self.engine._write(self.engine.bindings)
        with self.assertRaises(ValueError):self.engine._read()

    async def test_storage_growth_is_bounded_before_replacing_existing_bindings(self):
        await self.engine.save(self.engine.bindings);before=self.engine.path.read_bytes()
        with patch('core.wechat.vault.encrypt',return_value='x'*2097153):
            with self.assertRaises(ValueError):await self.engine.configure('A',True,False,False)
        self.assertEqual(self.engine.path.read_bytes(),before);self.assertTrue(self.engine.bindings['A']['course_reminders'])

class ReminderServerFeed(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from server import app as backend
        self.backend=backend;self.previous=backend.accounts.copy();self.accounts=[]
        backend.accounts.clear()
        for user in ('A','B'):
            acc=backend.AccountState(user,auto_checkin=False);self.accounts.append(acc);backend.accounts[user]=acc
            acc.client.is_authenticated=lambda:True
            acc.client.get_today_classes=AsyncMock(return_value=[copy.deepcopy(COURSE)])
        self.clock=patch.object(backend,'china_now',return_value=NOW);self.clock.start()

    async def asyncTearDown(self):
        for acc in self.accounts:await acc.client.close();acc.boya_client.close()
        self.backend.accounts.clear();self.backend.accounts.update(self.previous);self.clock.stop()

    async def test_inactive_student_reads_without_enabling_attendance_or_global_scheduler(self):
        acc=self.accounts[1];previous_enabled=self.backend.scheduler.enabled
        result=await self.backend.wechat_course_snapshot('B')
        self.assertEqual(result['classes'],[COURSE]);self.assertFalse(acc.auto_checkin)
        self.assertEqual(self.backend.scheduler.enabled,previous_enabled)
        await self.backend.wechat_course_snapshot('B');self.assertEqual(acc.client.get_today_classes.await_count,1)

    async def test_stale_failure_and_human_auth_pause_do_not_use_old_cache_or_reconnect(self):
        acc=self.accounts[0];acc.last_classes=[COURSE];acc.client.get_today_classes.side_effect=OSError('temporary network')
        with patch.object(self.backend,'connect_single_account',new_callable=AsyncMock) as connect:
            self.assertIsNone(await self.backend.wechat_course_snapshot('A'));connect.assert_not_awaited()
            acc.auth_requires_input=True;acc.client.get_today_classes.reset_mock()
            self.assertIsNone(await self.backend.wechat_course_snapshot('A'));acc.client.get_today_classes.assert_not_awaited()

    async def test_epoch_or_student_changed_while_reading_discards_result(self):
        acc=self.accounts[0]
        async def change():acc.auth_epoch+=1;return [COURSE]
        acc.client.get_today_classes.side_effect=change
        self.assertIsNone(await self.backend.wechat_course_snapshot('A'));self.assertFalse(acc.last_classes)

    async def test_midnight_previous_day_cache_is_never_treated_as_todays_courses(self):
        acc=self.accounts[0];acc.last_classes=[dict(COURSE,courseName='昨日缓存')]
        acc.regular_health={'stale':False,'last_success':'2026-10-25T23:59:59'}
        with patch.object(self.backend,'china_now',return_value=dt.datetime(2026,10,26,0,0,1)):
            result=await self.backend.wechat_course_snapshot('A')
        acc.client.get_today_classes.assert_awaited_once();self.assertEqual(result['classes'][0]['courseName'],'合成课程')

if __name__=='__main__':unittest.main()
