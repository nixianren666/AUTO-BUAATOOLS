"""Transport incidents, load bounds and durable uncertain writes; no real network."""
import collections
import asyncio
import sqlite3
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from core import operations
from core.boya_actions import perform_boya_action
from core.boya_client import BoyaApiError
from core.boya_scheduler import BoyaScheduler
from boya_fixture import FixtureBoyaClient, FixtureCrypto, valid_course


class NetworkIncidents(unittest.TestCase):
    def setUp(self):
        self.ledger=operations.OperationLedger()
        self.addCleanup(self.ledger.db.close)
        self.patches=[patch('core.operations.ledger',self.ledger),patch('core.boya_client.BykcCrypto',FixtureCrypto)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.logs=[];self.accounts=[]
        self.scheduler=BoyaScheduler(lambda:self.accounts,lambda level,message,**kw:self.logs.append((level,message,kw)),ordinary_courses=lambda *a:[])
        self.stamp=1000.
        self.monotonic=patch('core.boya_scheduler.time.monotonic',side_effect=lambda:self.stamp)
        self.monotonic.start();self.addCleanup(self.monotonic.stop)
        self.acc,self.calls,self.faults=self.account('synthetic-A')

    def account(self,username):
        acc=SimpleNamespace(username=username,name='synthetic',removed=False,maintenance=False,
            auth_epoch=0,campus='北京',boya_auto_select=True,boya_auto_sign=False,boya_health={},
            boya_all_courses=[valid_course(901),valid_course(902)],boya_selected_courses=[],boya_pending_courses={})
        client=FixtureBoyaClient(acc);acc.boya_client=client;self.addCleanup(client.close)
        counts=collections.Counter();faults={};original=client._server
        def serve(request):
            api=request.url.path.rsplit('/',1)[-1];counts[api]+=1
            fault=faults.get(api)
            if fault:
                if isinstance(fault,int):return httpx.Response(fault,request=request)
                raise fault('synthetic transport failure',request=request)
            return original(request)
        client.http_client.close();client.http_client=httpx.Client(transport=httpx.MockTransport(serve),trust_env=False)
        self.accounts.append(acc)
        return acc,counts,faults

    def warnings(self):return [x for x in self.logs if x[0]=='warning']
    def timeout(self,phase='read'):
        error=httpx.ReadTimeout('synthetic');error.boya_phase=phase;return error
    def choose(self):self.scheduler._check_auto_select(self.acc,self.scheduler.clock())

    def test_satisfied_targets_skip_all_action_reads_but_keep_regular_full_sync(self):
        self.acc.boya_targets={'美育':0};self.choose();self.assertFalse(self.calls)
        self.scheduler.tick();self.assertEqual(self.calls['queryChosenCourse'],1)
        self.assertEqual(self.calls['queryStudentSemesterCourseByPage'],1)
        self.assertEqual(self.calls['choseCourse'],0)
        self.stamp+=61;self.scheduler.tick();self.assertEqual(self.calls['queryChosenCourse'],2)

    def test_selected_and_pending_courses_do_not_trigger_action_preflight(self):
        self.acc.boya_selected_courses=[valid_course(901)]
        self.acc.boya_pending_courses={902:valid_course(902)}
        self.choose();self.assertFalse(self.calls)

    def test_decreased_or_increased_target_rechecked_without_restarting(self):
        self.acc.boya_targets={'美育':0};self.choose();self.assertEqual(self.calls['choseCourse'],0)
        self.acc.boya_targets={'美育':1};self.choose();self.assertEqual(self.calls['choseCourse'],1)
        self.assertEqual(self.acc.boya_client.selected_ids,[901])

    def test_pending_reservation_prevents_next_same_category_after_one_acceptance(self):
        self.choose();self.assertEqual(self.calls['choseCourse'],1)
        self.choose();self.assertEqual(self.calls['choseCourse'],1)

    def test_stale_capacity_cannot_authorize_write(self):
        original=self.acc.boya_client.query_courses
        def fresh():return [dict(c,courseCurrentCount=20) for c in original()]
        with patch.object(self.acc.boya_client,'query_courses',side_effect=fresh):self.choose()
        self.assertEqual(self.calls['choseCourse'],0)

    def test_first_preflight_timeout_stops_remaining_candidates(self):
        self.faults['getAllConfig']=httpx.ReadTimeout;self.choose()
        self.assertEqual(self.calls['getAllConfig'],1);self.assertEqual(self.calls['choseCourse'],0)
        self.assertEqual(len(self.warnings()),1)
        self.assertEqual(self.acc.boya_health['network_phase'],'read')

    def test_many_courses_and_exception_types_share_one_student_incident(self):
        self.scheduler._network_failure(self.acc,self.timeout(),901,'select')
        for cid in range(902,920):self.scheduler._network_failure(self.acc,httpx.ConnectTimeout('synthetic'),cid,'select')
        self.assertEqual(len(self.warnings()),1)
        self.assertTrue(self.acc.boya_health['stale']);self.assertEqual(self.acc.boya_health['next_sync_in_seconds'],300)

    def test_cached_ticks_and_partial_sync_cannot_clear_incident(self):
        self.acc.boya_auto_select=False;self.acc.boya_auto_sign=True
        self.scheduler._network_failure(self.acc,self.timeout())
        self.stamp+=31;self.scheduler.tick()
        self.assertTrue(self.acc.boya_health['stale'])
        self.stamp+=10;self.scheduler.tick();self.assertTrue(self.acc.boya_health['stale'])
        self.stamp+=51;self.faults['queryStudentSemesterCourseByPage']=httpx.ReadTimeout
        self.scheduler.tick();self.assertTrue(self.acc.boya_health['stale'])
        self.assertEqual(len(self.warnings()),1)

    def test_two_complete_syncs_spaced_one_minute_recover_then_new_outage_alerts(self):
        self.acc.boya_auto_select=False;self.acc.boya_auto_sign=True
        self.scheduler._network_failure(self.acc,self.timeout())
        self.stamp+=31;self.scheduler.tick();self.assertTrue(self.acc.boya_health['stale'])
        self.stamp+=61;self.scheduler.tick();self.assertFalse(self.acc.boya_health['stale'])
        self.assertNotIn(self.acc.username,self.scheduler._network)
        self.scheduler._network_failure(self.acc,self.timeout());self.assertEqual(len(self.warnings()),2)

    def test_action_failure_after_successful_sync_is_not_false_recovery(self):
        self.scheduler._network_failure(self.acc,self.timeout())
        for _ in range(4):
            self.stamp+=61
            with patch('core.boya_actions.perform_boya_action',side_effect=self.timeout()):self.scheduler.tick()
        self.assertTrue(self.acc.boya_health['stale']);self.assertEqual(len(self.warnings()),1)

    def test_backoff_stops_requests_and_other_student_keeps_working(self):
        other,counts,faults=self.account('synthetic-B')
        self.faults['getAllConfig']=httpx.ReadTimeout;self.scheduler.tick()
        first=dict(self.calls);self.stamp+=10;self.scheduler.tick()
        self.assertEqual(dict(self.calls),first);self.assertEqual(counts['choseCourse'],1)
        self.assertFalse(other.boya_health['stale']);self.assertEqual(self.warnings()[0][2]['username'],self.acc.username)

    def test_backoff_expires_and_retries_only_read_after_outage(self):
        self.faults['getAllConfig']=httpx.ReadTimeout
        for expected in (30,60,120,240,300,300):
            self.scheduler.tick();self.assertEqual(self.acc.boya_health['next_sync_in_seconds'],expected)
            self.stamp+=expected
        self.assertEqual(self.calls['getAllConfig'],6);self.assertEqual(self.calls['choseCourse'],0)
        self.assertEqual(len(self.warnings()),1)

    def test_read_error_metadata_preserves_type_and_authentication(self):
        self.faults['queryChosenCourse']=httpx.ReadTimeout
        with self.assertRaises(httpx.ReadTimeout) as caught:self.acc.boya_client.query_chosen_courses()
        self.assertEqual(caught.exception.boya_phase,'read');self.assertTrue(self.acc.boya_client.is_authenticated())
        self.assertEqual(self.ledger.db.execute('SELECT COUNT(*) FROM operations').fetchone()[0],0)

    def test_uncertain_actual_post_is_alerted_even_during_existing_read_incident(self):
        self.scheduler._network_failure(self.acc,self.timeout())
        self.faults['choseCourse']=httpx.ReadTimeout;self.choose()
        self.assertEqual(self.calls['choseCourse'],1);self.assertEqual(len(self.warnings()),2)
        self.assertIn('结果待确认',self.warnings()[-1][1]);self.assertIn(901,self.acc.boya_pending_courses)
        self.acc.boya_all_courses[0]['courseCurrentCount']=1;self.choose()
        self.assertEqual(self.calls['choseCourse'],1)
        states=[r[0] for r in self.ledger.db.execute('SELECT state FROM operations')]
        self.assertIn('uncertain',states)

    def test_connection_failure_keeps_original_attempt_rollback(self):
        self.faults['choseCourse']=httpx.ConnectTimeout
        with self.assertRaises(httpx.ConnectTimeout) as caught:perform_boya_action(self.acc,'select',901,ordinary=lambda *a:[])
        self.assertEqual(caught.exception.boya_phase,'not_sent')
        rows=list(self.ledger.db.execute('SELECT state,attempts FROM operations'))
        self.assertEqual(len(rows),2);self.assertTrue(all(row==('failed',0) for row in rows))

    def test_http_error_during_read_and_write_has_distinct_conservative_phases(self):
        self.faults['queryChosenCourse']=503
        with self.assertRaises(httpx.HTTPStatusError) as caught:self.acc.boya_client.query_chosen_courses()
        self.assertEqual(caught.exception.boya_phase,'read')
        self.faults.clear();self.faults['choseCourse']=503
        with self.assertRaises(httpx.HTTPStatusError) as caught:perform_boya_action(self.acc,'select',901,ordinary=lambda *a:[])
        self.assertEqual(caught.exception.boya_phase,'write_uncertain')
        self.assertIn('uncertain',[r[0] for r in self.ledger.db.execute('SELECT state FROM operations')])

    def test_stop_and_remove_do_not_leave_network_incident_for_new_account(self):
        self.scheduler._network_failure(self.acc,self.timeout());self.scheduler.remove_account(self.acc.username)
        self.assertNotIn(self.acc.username,self.scheduler._network)
        self.acc.maintenance=True;self.scheduler.tick();self.assertFalse(self.calls)

    def test_authentication_failure_remains_distinct_and_visible(self):
        self.faults['queryChosenCourse']=401;self.scheduler.tick()
        self.assertFalse(self.acc.boya_client.is_authenticated());self.assertNotIn(self.acc.username,self.scheduler._network)
        self.assertEqual(len(self.warnings()),1);self.assertIn('BoyaSessionExpired',self.warnings()[0][1])

    def test_post_acceptance_read_timeout_keeps_one_pending_alert_and_no_second_post(self):
        original=self.acc.boya_client.select_course
        def accept(cid):
            reply=original(cid);self.faults['queryChosenCourse']=httpx.ReadTimeout;return reply
        with patch.object(self.acc.boya_client,'select_course',side_effect=accept):self.choose()
        self.assertEqual(self.calls['choseCourse'],1);self.assertEqual(len(self.warnings()),1)
        self.assertIn('尚待官方结果核对',self.warnings()[0][1])
        self.assertTrue(self.acc.boya_health['stale']);self.assertIn(901,self.acc.boya_pending_courses)
        self.choose();self.assertEqual(self.calls['choseCourse'],1)
        self.assertIn('success',[r[0] for r in self.ledger.db.execute('SELECT state FROM operations')])

    def test_auto_sign_network_failure_stops_second_phase_and_other_courses(self):
        self.acc.boya_auto_sign=True;self.acc.boya_selected_courses=[valid_course(901),valid_course(902)]
        with patch('core.domain.attendance_allowed',return_value=True),patch('core.boya_actions.perform_boya_action',side_effect=self.timeout()) as action:
            self.scheduler._check_auto_sign(self.acc,self.scheduler.clock())
        self.assertEqual(action.call_count,1);self.assertEqual(len(self.warnings()),1)
        self.assertEqual(self.acc.boya_health['network_phase'],'read')

    def test_open_attendance_window_caps_long_outage_delay_without_new_writes(self):
        self.acc.boya_auto_sign=True;self.acc.boya_selected_courses=[valid_course(901)]
        for _ in range(7):self.scheduler._network_failure(self.acc,self.timeout())
        self.assertEqual(self.acc.boya_health['next_sync_in_seconds'],30)
        self.assertEqual(self.calls['signCourseByUser'],0);self.assertEqual(len(self.warnings()),1)

    def test_read_only_status_preserves_incident_after_manual_health_replacement(self):
        self.scheduler._network_failure(self.acc,self.timeout())
        self.acc.boya_health={'stale':False,'error':None,'last_success':'synthetic-manual-read'}
        self.stamp+=10
        snapshot=self.scheduler.health_snapshot(self.acc)
        self.assertTrue(snapshot['stale']);self.assertEqual(snapshot['error'],'ReadTimeout')
        self.assertEqual(snapshot['next_sync_in_seconds'],20);self.assertFalse(self.calls)
        self.assertFalse(self.acc.boya_health['stale'])

    def test_uncertain_attendance_skips_preflight_across_capacity_changes_and_keeps_visible_status(self):
        course=valid_course(901);self.acc.boya_selected_courses=[course];self.acc.boya_auto_sign=True
        group=self.ledger.key(self.acc.username,'signCourseByUser:1',901,'group')
        key=self.ledger.key(self.acc.username,'signCourseByUser:1',901,'synthetic-window')
        self.ledger.claim(key,group=group);self.ledger.finish(key,'uncertain')
        with patch('core.domain.attendance_allowed',side_effect=lambda c,k,n:k==1),patch('core.boya_actions.perform_boya_action') as action:
            for _ in range(5):self.scheduler._check_auto_sign(self.acc,self.scheduler.clock())
        action.assert_not_called();self.assertFalse(self.calls)
        self.assertTrue(self.scheduler.health_snapshot(self.acc)['pending_verification'])
        self.acc.boya_selected_courses[0]['checkin']=5
        from core.boya_actions import reconcile_official
        reconcile_official(self.acc,self.acc.boya_selected_courses)
        self.assertFalse(self.scheduler.health_snapshot(self.acc)['pending_verification'])
        self.assertEqual(self.ledger.read(key)[0],'success')

    def test_pending_selection_status_is_read_only_and_clears_only_after_official_observation(self):
        self.acc.boya_pending_courses={901:valid_course(901)}
        before=self.ledger.db.total_changes
        self.assertTrue(self.scheduler.health_snapshot(self.acc)['pending_verification'])
        self.assertEqual(self.ledger.db.total_changes,before);self.assertFalse(self.calls)
        from core.boya_actions import reconcile_official
        reconcile_official(self.acc,[valid_course(901)])
        self.assertFalse(self.scheduler.health_snapshot(self.acc)['pending_verification'])

    def test_real_status_api_serializes_pending_and_network_state_without_school_calls(self):
        import server.app as app
        self.acc.boya_targets=None;self.acc.boya_pending_courses={901:valid_course(901)}
        self.scheduler._network_failure(self.acc,self.timeout())
        before=self.ledger.db.total_changes
        with patch.object(app,'accounts',{self.acc.username:self.acc}),patch.object(app,'boya_scheduler',self.scheduler):
            reply=asyncio.run(app.get_boya_status(username=self.acc.username))
        import json
        self.assertIn('ReadTimeout',json.dumps(reply));self.assertTrue(reply['health']['pending_verification'])
        self.assertEqual(self.ledger.db.total_changes,before);self.assertFalse(self.calls)

    def test_persistent_outage_over_a_day_does_not_flood_or_starve_other_student(self):
        other,counts,_=self.account('synthetic-B');other.boya_targets={'美育':0}
        self.faults['getAllConfig']=httpx.ReadTimeout
        for _ in range(288):
            self.scheduler.tick();self.stamp+=300
        self.assertEqual(len(self.warnings()),1)
        self.assertEqual(counts['queryChosenCourse'],288);self.assertEqual(counts['choseCourse'],0)
        self.assertTrue(self.acc.boya_health['stale']);self.assertFalse(other.boya_health['stale'])

    def test_reopened_sqlite_uncertain_attendance_does_not_repeat_preflight_or_write(self):
        self.acc.boya_selected_courses=[valid_course(901)];self.acc.boya_auto_sign=True
        key=self.ledger.key(self.acc.username,'signCourseByUser:1',901,'synthetic-window')
        group=self.ledger.key(self.acc.username,'signCourseByUser:1',901,'group')
        self.ledger.claim(key,group=group);self.ledger.finish(key,'uncertain')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'operations.sqlite'
            disk=sqlite3.connect(path)
            try:self.ledger.db.backup(disk)
            finally:disk.close()
            reopened=operations.OperationLedger(path)
            try:
                with patch('core.operations.ledger',reopened),patch('core.domain.attendance_allowed',side_effect=lambda c,k,n:k==1),patch('core.boya_actions.perform_boya_action') as action:
                    worker=BoyaScheduler(lambda:[self.acc],lambda *a,**k:None)
                    worker._check_auto_sign(self.acc,worker.clock())
                    action.assert_not_called();self.assertTrue(worker.health_snapshot(self.acc)['pending_verification'])
                    self.assertEqual(reopened.read(key)[0],'uncertain')
            finally:reopened.db.close()
        self.assertFalse(self.calls)
