"""User-authorized regular lesson window and bounded retry contracts."""
import asyncio
from datetime import datetime,timedelta
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from core import operations
from core.domain import regular_allowed, regular_window, CHINA
from core.regular_policy import MAX_POSTS, minimum_retry_delay
from core.scheduler import SigninScheduler

class RegularWindow(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,10,17,9)
        self.course={'courseSchedId':'1001','classBeginTime':'2026-10-17 09:00:00','classEndTime':'2026-10-17 10:00:00','signStatus':0}

    def test_before_during_and_end_boundaries(self):
        for seconds,expected in [(-601,False),(-600,True),(-1,True),(0,True),(1,True),(3599,True),(3600,True),(3601,False)]:
            with self.subTest(seconds=seconds):self.assertEqual(regular_allowed(self.course,self.start+timedelta(seconds=seconds)),expected)

    def test_unknown_or_reversed_end_never_invents_lesson_duration(self):
        for value in (None,'invalid','2026-10-17 08:00:00'):
            course={**self.course,'classEndTime':value}
            self.assertTrue(regular_allowed(course,self.start-timedelta(seconds=1)))
            self.assertFalse(regular_allowed(course,self.start+timedelta(seconds=1)))

    def test_wrong_day_and_unknown_status_remain_closed(self):
        for status in (1,None,'unknown'):
            self.assertFalse(regular_allowed({**self.course,'signStatus':status},self.start))
        self.assertFalse(regular_allowed(self.course,self.start+timedelta(days=1)))

    def test_offsets_and_time_only_use_same_china_window(self):
        self.assertTrue(regular_allowed({**self.course,'classBeginTime':'2026-10-17T01:00:00Z','classEndTime':'2026-10-17T02:00:00Z'},self.start+timedelta(minutes=30)))
        self.assertEqual(regular_window({**self.course,'classEndTime':'10:00'},self.start)[1],self.start+timedelta(hours=1))

class RetryPersistence(unittest.TestCase):
    def test_reopened_ledger_preserves_preclass_cooling_and_inclass_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'operations.sqlite';clock=100000.
            with patch('core.operations.time.time',lambda:clock):
                for index in range(3):
                    caller=operations.OperationLedger(path)
                    try:
                        caller.claim('regular',limit=MAX_POSTS,retry_delay=lambda n:minimum_retry_delay(n,True))
                        caller.finish('regular','failed')
                    finally:caller.db.close()
                    if index<2:clock+=30
                clock+=60
                caller=operations.OperationLedger(path)
                try:
                    with self.assertRaises(operations.OperationBusy):caller.claim('regular',limit=MAX_POSTS,retry_delay=lambda n:minimum_retry_delay(n,False))
                    self.assertEqual(caller.read('regular')[1],3)
                    clock+=240
                    self.assertTrue(caller.claim('regular',limit=MAX_POSTS,retry_delay=lambda n:minimum_retry_delay(n,False)))
                    self.assertEqual(caller.read('regular')[1],4)
                finally:caller.db.close()

    def test_regular_policy_is_opt_in_and_restart_keeps_cooling_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'operations.sqlite';first=operations.OperationLedger(path);second=operations.OperationLedger(path)
            try:
                clock=100000.
                with patch('core.operations.time.time',lambda:clock):
                    for index in range(MAX_POSTS):
                        if index:clock+=minimum_retry_delay(index)
                        caller=first if index%2==0 else second
                        self.assertTrue(caller.claim('regular',limit=MAX_POSTS,retry_delay=minimum_retry_delay));caller.finish('regular','failed')
                        with self.assertRaises(operations.OperationBusy):second.claim('regular',limit=MAX_POSTS,retry_delay=minimum_retry_delay)
                    clock+=1000
                    with self.assertRaises(operations.OperationBusy):first.claim('regular',limit=MAX_POSTS,retry_delay=minimum_retry_delay)
                    # Boya/generic callers keep their previous three-attempt contract.
                    for _ in range(3):self.assertTrue(first.claim('generic'));first.finish('generic','failed')
                    with self.assertRaises(operations.OperationBusy):second.claim('generic')
            finally:first.db.close();second.db.close()

class SchedulerLessonRetries(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.current=datetime(2026,10,17,8,55)
        self.course={'courseSchedId':'1001','classBeginTime':'2026-10-17 09:00:00','classEndTime':'2026-10-17 10:00:00','signStatus':0}
        self.record=None;self.calls=0;self.logs=[]
        outer=self
        class Client:
            actual_sign_posts=0
            session_id='fixture-session'
            def is_authenticated(self):return True
            async def get_today_classes(self):return [dict(outer.course)]
            def signin_record(self,cid):return outer.record
            async def perform_signin(self,cid,guard=None):
                assert guard is None or guard()
                outer.calls+=1;self.actual_sign_posts+=1
                outer.record=('failed',outer.calls,outer.current.replace(tzinfo=CHINA).timestamp())
                return False,'synthetic explicit rejection'
        self.client=Client();self.item={'username':'fixture-account','client':self.client}
        self.scheduler=SigninScheduler(lambda:[self.item],on_event_log=lambda *args:self.logs.append(args));self.scheduler.clock=lambda:self.current
        self.key=('fixture-account','1001','2026-10-17')

    async def test_first_target_randomized_before_start_and_existing_lesson_starts_now(self):
        with patch('core.scheduler.random.uniform',return_value=100):await self.scheduler.tick()
        self.assertEqual(self.scheduler.planned_targets[self.key],self.current+timedelta(seconds=100));self.assertEqual(self.calls,0)
        self.scheduler.planned_targets.clear();self.current=datetime(2026,10,17,9,5)
        await self.scheduler.tick();self.assertEqual(self.calls,1)

    async def test_failed_preclass_attempt_continues_after_start_without_spam(self):
        self.current=datetime(2026,10,17,8,59,50)
        self.scheduler.planned_targets[self.key]=self.current
        await self.scheduler.tick();self.assertEqual(self.calls,1)
        for _ in range(20):await self.scheduler.tick()
        self.assertEqual(self.calls,1)
        self.current=datetime(2026,10,17,9,1)
        await self.scheduler.tick();self.assertEqual(self.calls,2)

    async def test_manual_failure_replaces_unexecuted_random_initial_target(self):
        self.scheduler.planned_targets[self.key]=self.current+timedelta(minutes=4)
        self.record=('failed',1,self.current.replace(tzinfo=CHINA).timestamp())
        await self.scheduler.tick();self.assertEqual(self.calls,0)
        self.current+=timedelta(seconds=30)
        await self.scheduler.tick();self.assertEqual(self.calls,1)

    async def test_three_then_long_cooling_then_final_three(self):
        with patch('core.scheduler.random.randint',side_effect=lambda lo,hi:lo):
            self.scheduler.planned_targets[self.key]=self.current
            for expected in range(1,7):
                await self.scheduler.tick();self.assertEqual(self.calls,expected)
                if expected<6:
                    delay=minimum_retry_delay(expected,self.current < datetime(2026,10,17,9))
                    self.current+=timedelta(seconds=delay-1);await self.scheduler.tick();self.assertEqual(self.calls,expected)
                    self.current+=timedelta(seconds=1)
            self.current+=timedelta(minutes=20);await self.scheduler.tick();self.assertEqual(self.calls,6)

    async def test_restart_uses_persistent_attempts_not_fresh_six(self):
        self.record=('failed',3,self.current.replace(tzinfo=CHINA).timestamp())
        self.current+=timedelta(seconds=59);await self.scheduler.tick();self.assertEqual(self.calls,0)
        self.current+=timedelta(seconds=1);await self.scheduler.tick();self.assertEqual(self.calls,1)

    async def test_crossing_start_upgrades_group_cooling_without_resetting_budget(self):
        self.current=datetime(2026,10,17,8,59,30)
        self.record=('failed',3,self.current.replace(tzinfo=CHINA).timestamp())
        await self.scheduler.tick()
        self.current+=timedelta(seconds=60)
        await self.scheduler.tick();self.assertEqual(self.calls,0)
        self.current=datetime(2026,10,17,9,4,29)
        await self.scheduler.tick();self.assertEqual(self.calls,0)
        self.current+=timedelta(seconds=1)
        await self.scheduler.tick();self.assertEqual(self.calls,1)

    async def test_inclass_group_requires_five_minutes(self):
        self.current=datetime(2026,10,17,9,5)
        self.record=('failed',3,self.current.replace(tzinfo=CHINA).timestamp())
        self.current+=timedelta(seconds=299)
        await self.scheduler.tick();self.assertEqual(self.calls,0)
        self.current+=timedelta(seconds=1)
        await self.scheduler.tick();self.assertEqual(self.calls,1)

    async def test_uncertain_only_polls_and_reports_once_until_official_confirmation(self):
        self.record=('uncertain',1,self.current.replace(tzinfo=CHINA).timestamp())
        for _ in range(10):await self.scheduler.tick()
        self.assertEqual(self.calls,0);self.assertEqual(len(self.logs),1)
        self.course['signStatus']=1;await self.scheduler.tick();self.assertIn(self.key,self.scheduler.signed_courses);self.assertEqual(self.calls,0)

    async def test_ended_lesson_stops_even_when_retry_target_is_due(self):
        self.current=datetime(2026,10,17,10,0,1);self.scheduler.planned_targets[self.key]=self.current-timedelta(minutes=2)
        for _ in range(10):await self.scheduler.tick()
        self.assertEqual(self.calls,0);self.assertIn(self.key,self.scheduler.window_closed_notified);self.assertEqual(len(self.logs),1)

    async def test_fresh_official_end_metadata_can_recover_from_unknown_end(self):
        self.current=datetime(2026,10,17,9,5);self.course['classEndTime']=None
        await self.scheduler.tick();self.assertEqual(self.calls,0)
        self.course['classEndTime']='2026-10-17 10:00:00'
        await self.scheduler.tick();self.assertEqual(self.calls,1)
        self.assertNotIn(self.key,self.scheduler.window_closed_notified)

    async def test_delayed_preflight_checks_deadline_again(self):
        self.current=datetime(2026,10,17,9,59,59);self.scheduler.planned_targets[self.key]=self.current
        def delayed_record(cid):self.current+=timedelta(seconds=2);return None
        self.client.signin_record=delayed_record
        await self.scheduler.tick();self.assertEqual(self.calls,0)
