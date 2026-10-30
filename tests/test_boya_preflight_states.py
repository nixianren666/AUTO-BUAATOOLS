"""Expected no-write decisions must not conceal unknown data or school failures."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from datetime import timedelta
from core import operations
from core.domain import now
from core.boya_actions import perform_boya_action,BoyaPreflightStop
from core.boya_client import BoyaApiError
from core.boya_scheduler import BoyaScheduler
from boya_fixture import FixtureBoyaClient,FixtureCrypto,valid_course

class PreflightStates(unittest.TestCase):
 def setUp(self):
  self.ledger=operations.OperationLedger();self.addCleanup(self.ledger.db.close)
  for target,value in [('core.operations.ledger',self.ledger),('core.boya_client.BykcCrypto',FixtureCrypto)]:
   p=patch(target,value);p.start();self.addCleanup(p.stop)
  self.acc=SimpleNamespace(username='synthetic-preflight',name='synthetic',removed=False,maintenance=False,auth_epoch=0,
   boya_auto_select=True,boya_auto_sign=False,boya_all_courses=[valid_course(901)],boya_selected_courses=[],boya_pending_courses={},campus='北京',boya_health={})
  self.acc.boya_client=FixtureBoyaClient(self.acc);self.addCleanup(self.acc.boya_client.close)
  self.logs=[];self.worker=BoyaScheduler(lambda:[self.acc],lambda level,message,**kw:self.logs.append((level,message,kw)),ordinary_courses=lambda *a:[])
 def check(self,fresh):
  with patch.object(self.acc.boya_client,'query_courses',return_value=fresh):self.worker._check_auto_select(self.acc,now())
 def assert_normal_no_post(self):
  self.assertEqual(self.acc.boya_client.select_call_count,0)
  self.assertEqual(len(self.logs),1);self.assertEqual(self.logs[0][0],'info');self.assertIs(self.logs[0][2]['notify'],False)
  self.assertEqual(self.ledger.db.execute('SELECT count(*) FROM operations').fetchone()[0],0)
 def test_full_capacity_race_is_local_normal_stop_without_claim_or_post(self):
  self.check([dict(valid_course(901),courseCurrentCount=20)]);self.assert_normal_no_post()
 def test_official_window_already_ended_after_cached_candidate_is_normal(self):
  self.check([dict(valid_course(901),courseSelectEndDate=(now()-timedelta(seconds=1)).isoformat())]);self.assert_normal_no_post()
 def test_official_window_moved_into_future_is_normal(self):
  self.check([dict(valid_course(901),courseSelectStartDate=(now()+timedelta(minutes=10)).isoformat())]);self.assert_normal_no_post()
 def test_unknown_inconsistent_or_boolean_capacity_still_warns_without_post(self):
  for changes in ({'courseMaxCount':None},{'courseCurrentCount':True},{'courseCurrentCount':21},{'courseMaxCount':0}):
   with self.subTest(changes=changes):
    self.logs.clear();self.worker._warnings.clear();self.acc.boya_all_courses=[valid_course(901)]
    self.check([dict(valid_course(901),**changes)])
    self.assertEqual(self.logs[0][0],'warning');self.assertNotIn('notify',self.logs[0][2]);self.assertEqual(self.acc.boya_client.select_call_count,0)
 def test_missing_or_reversed_window_is_still_a_data_warning(self):
  for changes in ({'courseSelectEndDate':None},{'courseSelectStartDate':(now()+timedelta(days=1)).isoformat()}):
   self.logs.clear();self.worker._warnings.clear();self.acc.boya_all_courses=[valid_course(901)]
   self.check([dict(valid_course(901),**changes)])
   self.assertEqual(self.logs[0][0],'warning');self.assertEqual(self.acc.boya_client.select_call_count,0)
 def test_actual_school_rejection_with_same_code_is_not_silenced(self):
  with patch.object(self.acc.boya_client,'select_course',side_effect=BoyaApiError('unavailable','synthetic actual school rejection')) as post:
   self.check([valid_course(901)])
  post.assert_called_once_with(901)
  self.assertEqual(self.logs[0][0],'warning');self.assertNotIn('notify',self.logs[0][2])
 def test_explicit_manual_full_course_reports_unavailable_without_post(self):
  with patch.object(self.acc.boya_client,'query_courses',return_value=[dict(valid_course(901),courseCurrentCount=20)]):
   with self.assertRaises(BoyaPreflightStop) as error:perform_boya_action(self.acc,'select',901)
  self.assertEqual(error.exception.code,'unavailable');self.assertEqual(self.acc.boya_client.select_call_count,0)
 def test_full_candidate_does_not_stop_another_safe_candidate(self):
  self.acc.boya_all_courses=[valid_course(901),valid_course(902)]
  self.check([dict(valid_course(901),courseCurrentCount=20),valid_course(902)])
  self.assertEqual(self.acc.boya_client.selected_ids,[902]);self.assertEqual(self.acc.boya_client.select_call_count,1)
  self.assertTrue(any(level=='info' and kw.get('notify') is False for level,_,kw in self.logs))
  self.assertFalse(any(level=='warning' for level,_,_ in self.logs))
 def test_known_cached_overlap_skips_all_action_reads_without_disabling_sync(self):
  self.acc.boya_selected_courses=[valid_course(800,'劳育')]
  with patch.object(self.acc.boya_client,'query_chosen_courses') as selected,patch.object(self.acc.boya_client,'query_courses') as pool:
   self.worker._check_auto_select(self.acc,now())
  selected.assert_not_called();pool.assert_not_called();self.assert_normal_no_post()
 def test_removing_conflicting_reservation_allows_fresh_preflight_next_round(self):
  self.acc.boya_pending_courses={800:valid_course(800,'劳育')}
  self.worker._check_auto_select(self.acc,now());self.assertEqual(self.acc.boya_client.select_call_count,0)
  self.acc.boya_pending_courses={};self.worker._check_auto_select(self.acc,now())
  self.assertEqual(self.acc.boya_client.selected_ids,[901])
 def test_cached_permission_never_bypasses_new_official_conflict(self):
  original=self.acc.boya_client.query_chosen_courses
  with patch.object(self.acc.boya_client,'query_chosen_courses',return_value=[valid_course(800,'劳育')]):
   self.worker._check_auto_select(self.acc,now())
  self.assertEqual(self.acc.boya_client.select_call_count,0)
  self.assertEqual(self.logs[0][0],'warning') # A fresh conflict still reaches the existing conservative preflight.
