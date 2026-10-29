import asyncio,datetime,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from core import operations
from core import regular_course_policy as policy
from core.scheduler import SigninScheduler

NOW=datetime.datetime(2026,10,30,9)
def lesson(sched='101',subject='901',date=NOW):
    return {'courseSchedId':sched,'courseId':subject,'courseName':'同名合成课程','classBeginTime':(date+datetime.timedelta(minutes=5)).isoformat(),'classEndTime':(date+datetime.timedelta(hours=1)).isoformat(),'signStatus':0}
def account(name='fixture-regular-A'):
    return SimpleNamespace(username=name,name='synthetic',boya_statistics={'semesterInfo':{'semesterStartDate':'2026-08-31','semesterEndDate':'2027-01-03'}},regular_pause_failsafe={},removed=False,maintenance=False,auth_epoch=0,auto_checkin=True)

class PolicyContracts(unittest.TestCase):
    def setUp(self):
        self.d=tempfile.TemporaryDirectory();self.path=Path(self.d.name)/'operations.sqlite';self.old=operations.ledger;self.store=operations.OperationLedger(self.path);operations.ledger=self.store;self.acc=account()
    def tearDown(self):
        operations.ledger=self.old;self.store.db.close();self.d.cleanup()
    def test_same_subject_future_lesson_and_other_student_or_same_name_do_not_mix(self):
        policy.set_pause(self.acc,lesson(),True,NOW)
        self.assertFalse(policy.allowed(self.acc,lesson('102','901',NOW+datetime.timedelta(days=7)),NOW))
        self.assertTrue(policy.allowed(self.acc,lesson('103','902'),NOW));self.assertTrue(policy.allowed(account('fixture-regular-B'),lesson(),NOW))
    def test_actual_reopen_and_new_account_object_preserve_pause(self):
        policy.set_pause(self.acc,lesson(),True,NOW);self.store.db.close();self.store=operations.OperationLedger(self.path);operations.ledger=self.store
        self.assertFalse(policy.allowed(account(),lesson(),NOW))
    def test_verified_semester_end_does_not_pause_next_term(self):
        policy.set_pause(self.acc,lesson(),True,NOW)
        future=datetime.datetime(2027,3,1,9);self.assertTrue(policy.allowed(self.acc,lesson(date=future),future))
    def test_unknown_semester_is_conservative_until_verified_new_term(self):
        self.acc.boya_statistics={};policy.set_pause(self.acc,lesson(),True,NOW)
        future=datetime.datetime(2027,3,1,9);self.assertFalse(policy.allowed(self.acc,lesson(date=future),future))
        self.acc.boya_statistics={'semesterInfo':{'semesterStartDate':'2027-02-20','semesterEndDate':'2027-07-01'}}
        self.assertTrue(policy.allowed(self.acc,lesson(date=future),future))
    def test_pause_or_resume_never_resets_old_write_claims(self):
        self.store.claim('unchanged-budget');self.store.finish('unchanged-budget','uncertain');before=self.store.read('unchanged-budget')
        policy.set_pause(self.acc,lesson(),True,NOW);policy.set_pause(self.acc,lesson(),False,NOW)
        self.assertEqual(self.store.read('unchanged-budget'),before);self.assertTrue(policy.allowed(self.acc,lesson(),NOW))
    def test_disk_failure_pauses_in_process_and_failed_resume_cannot_release(self):
        with patch.object(self.store,'set_regular_course_policy',side_effect=OSError('synthetic full')):
            with self.assertRaises(ValueError):policy.set_pause(self.acc,lesson(),True,NOW)
            self.assertTrue(policy.status(self.acc,lesson(),NOW)['storage_error'])
            with self.assertRaises(ValueError):policy.set_pause(self.acc,lesson(),False,NOW)
            self.assertFalse(policy.allowed(self.acc,lesson(),NOW))
    def test_missing_identity_never_guesses_by_name_or_releases_existing_pause(self):
        unknown=lesson();unknown.pop('courseId');self.assertFalse(policy.status(self.acc,unknown,NOW)['supported'])
        self.assertTrue(policy.allowed(self.acc,unknown,NOW))
        with self.assertRaises(ValueError):policy.set_pause(self.acc,unknown,True,NOW)
        policy.set_pause(self.acc,lesson(),True,NOW);self.assertFalse(policy.allowed(self.acc,unknown,NOW))
        unreliable=lesson();unreliable['courseIdentityKnown']=False;self.assertFalse(policy.status(self.acc,unreliable,NOW)['supported'])
    def test_corrupt_record_never_silently_enables_automatic_attendance(self):
        self.store.set_regular_course_policy(self.acc.username,'901',{'version':1,'created':'invalid'})
        state=policy.status(self.acc,lesson(),NOW);self.assertTrue(state['paused']);self.assertTrue(state['storage_error'])

class SchedulerPolicyContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old=operations.ledger;self.store=operations.OperationLedger();operations.ledger=self.store
    async def asyncTearDown(self):operations.ledger=self.old;self.store.db.close()
    async def test_paused_course_not_planned_other_course_and_student_still_submit(self):
        class Client:
            actual_sign_posts=0
            def __init__(self,rows):self.rows=rows;self.calls=[]
            def is_authenticated(self):return True
            async def get_today_classes(self):return self.rows
            async def perform_signin(self,cid,guard=None):
                if guard and not guard():return False,'暂停'
                self.actual_sign_posts+=1;self.calls.append(cid);return True,'accepted'
        a,b=account(),account('fixture-regular-B');rows=[lesson(),lesson('102','902')];a.client=Client(rows);b.client=Client([lesson()])
        policy.set_pause(a,rows[0],True,NOW)
        scheduler=SigninScheduler(lambda:[{'username':x.username,'name':x.name,'account':x,'client':x.client} for x in [a,b]])
        scheduler.clock=lambda:NOW
        for x in [a,b]:
            for c in x.client.rows:scheduler.planned_targets[(x.username,c['courseSchedId'],NOW.date().isoformat())]=NOW-datetime.timedelta(seconds=1)
        scheduler.retry_counts[(a.username,'101',NOW.date().isoformat())]=2
        await scheduler.tick();self.assertEqual(a.client.calls,['102']);self.assertEqual(b.client.calls,['101'])
        self.assertEqual(scheduler.retry_counts[(a.username,'101',NOW.date().isoformat())],2)
        self.assertNotIn((a.username,'101',NOW.date().isoformat()),scheduler.planned_targets)
    async def test_final_guard_observes_pause_inserted_after_scheduling(self):
        a=account();row=lesson();posts=[]
        class Client:
            actual_sign_posts=0
            def is_authenticated(self):return True
            async def get_today_classes(self):return [row]
            async def perform_signin(self,cid,guard=None):
                policy.set_pause(a,row,True,NOW)
                if guard():posts.append(cid)
                return False,'task stopped before request'
        a.client=Client();scheduler=SigninScheduler(lambda:[{'username':a.username,'account':a,'client':a.client}]);scheduler.clock=lambda:NOW
        key=(a.username,'101',NOW.date().isoformat());scheduler.planned_targets[key]=NOW-datetime.timedelta(seconds=1)
        await scheduler.tick();self.assertEqual(posts,[]);self.assertEqual(scheduler.retry_counts[key],0)

class RoutePolicyContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import server.app as app
        self.app=app;self.old=operations.ledger;self.store=operations.OperationLedger();operations.ledger=self.store
        self.a=account();self.b=account('fixture-regular-B')
        for x in [self.a,self.b]:x.last_classes=[lesson(),lesson('102','901')];x.password='';x.client=SimpleNamespace()
        self.accounts=patch.object(app,'accounts',{self.a.username:self.a,self.b.username:self.b});self.accounts.start()
    async def asyncTearDown(self):self.accounts.stop();operations.ledger=self.old;self.store.db.close()
    async def test_explicit_student_and_all_lessons_decorated_without_school_request(self):
        req=self.app.RegularCoursePolicyRequest(username=self.a.username,course_sched_id='101',paused=True)
        result=await self.app.update_regular_course_policy(req)
        self.assertTrue(all(c['auto_course']['paused'] for c in result['classes']))
        other=await self.app.get_regular_course_policy(self.b.username);self.assertFalse(any(c['auto_course']['paused'] for c in other['classes']))
    async def test_failure_response_truthfully_returns_in_process_pause(self):
        req=self.app.RegularCoursePolicyRequest(username=self.a.username,course_sched_id='101',paused=True)
        with patch.object(self.store,'set_regular_course_policy',side_effect=OSError('synthetic disk full')):
            response=await self.app.update_regular_course_policy(req)
        self.assertEqual(response.status_code,503)
        self.assertFalse(policy.allowed(self.a,lesson()))
    async def test_invalid_boolean_and_unknown_lesson_cannot_modify_policy(self):
        from pydantic import ValidationError
        from fastapi import HTTPException
        with self.assertRaises(ValidationError):self.app.RegularCoursePolicyRequest(username=self.a.username,course_sched_id='101',paused='false')
        with self.assertRaises(HTTPException):await self.app.update_regular_course_policy(self.app.RegularCoursePolicyRequest(username=self.a.username,course_sched_id='999',paused=True))
        self.assertIsNone(self.store.regular_course_policy(self.a.username,'901'))
    async def test_manual_signin_keeps_explicit_control_when_course_is_paused(self):
        a=self.a;policy.set_pause(a,lesson(),True)
        class Client:
            calls=[]
            def is_authenticated(self):return True
            async def perform_signin(self,cid,guard=None):
                if guard and not guard():return False,'stopped'
                self.calls.append(cid);return True,'synthetic accepted'
            async def get_today_classes(self):return a.last_classes
        a.client=Client()
        result=await self.app.perform_signin(self.app.SigninRequest(username=a.username,course_id='101'))
        self.assertTrue(result['success']);self.assertEqual(a.client.calls,['101']);self.assertFalse(policy.allowed(a,lesson()))
