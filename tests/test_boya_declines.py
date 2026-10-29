"""Persistent user intent; all school traffic stays in the encrypted fixture."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from core import operations
from core.boya_actions import perform_boya_action
from core.boya_client import BoyaApiError
from boya_fixture import FixtureBoyaClient,FixtureCrypto,valid_course

class DropClient(FixtureBoyaClient):
    def _server(self,request):
        if request.url.path.endswith('/delChosenCourse'):
            crypto=FixtureCrypto();cid=int(crypto.decrypt_response(request.content)['id'])
            self.drop_count+=1
            self.owner.boya_selected_courses=[c for c in self.owner.boya_selected_courses if int(c.get('courseId') or c['id'])!=cid]
            return httpx.Response(200,content=crypto.encrypt_plaintext(json.dumps({'status':'0','data':{}}).encode()))
        return super()._server(request)

class DeclineContracts(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.path=Path(self.folder.name)/'operations.sqlite'
        self.ledger=operations.OperationLedger(self.path);self.previous=operations.ledger;operations.ledger=self.ledger
        self.crypto=patch('core.boya_client.BykcCrypto',FixtureCrypto);self.crypto.start()
        self.acc=SimpleNamespace(username='fixture-decline-A',name='synthetic',removed=False,maintenance=False,auth_epoch=0,boya_all_courses=[valid_course(901)],boya_selected_courses=[],boya_pending_courses={},campus='北京',boya_auto_select=True,boya_auto_sign=True,boya_health={})
        self.client=DropClient(self.acc);self.client.drop_count=0;self.acc.boya_client=self.client
    def tearDown(self):
        self.client.http_client.close();operations.ledger=self.previous;self.ledger.db.close();self.crypto.stop();self.folder.cleanup()
    def auto(self):return perform_boya_action(self.acc,'select',901,automatic=True,ordinary=lambda *args:[])
    def assert_excluded(self):
        with self.assertRaises(BoyaApiError) as error:self.auto()
        self.assertEqual(error.exception.code,'user_declined');self.assertEqual(self.client.select_call_count,0)
    def test_platform_drop_is_persisted_and_never_automatically_regrabbed(self):
        self.acc.boya_selected_courses=[valid_course(901)]
        result=perform_boya_action(self.acc,'drop',901)
        self.assertTrue(result['submitted']);self.assertEqual(self.client.drop_count,1);self.assertEqual(self.acc.boya_selected_courses,[])
        self.assert_excluded()
    def test_external_drop_of_manually_selected_course_is_detected_by_fresh_preflight(self):
        self.acc.boya_selected_courses=[valid_course(901)];self.client.query_chosen_courses()
        self.acc.boya_selected_courses=[];self.assert_excluded()
    def test_external_drop_after_automatic_selection_is_detected(self):
        self.auto();self.assertEqual(self.client.select_call_count,1)
        self.acc.boya_selected_courses=[];self.client.select_call_count=0;self.assert_excluded()
    def test_exclusion_and_snapshot_survive_actual_ledger_reopen(self):
        self.acc.boya_selected_courses=[valid_course(901)];self.client.query_chosen_courses()
        self.ledger.db.close();self.ledger=operations.OperationLedger(self.path);operations.ledger=self.ledger
        self.acc.boya_selected_courses=[];self.assert_excluded()
        self.ledger.db.close();self.ledger=operations.OperationLedger(self.path);operations.ledger=self.ledger;self.assert_excluded()
    def test_other_student_same_course_and_new_capacity_do_not_share_or_clear_intent(self):
        self.ledger.exclude_auto_select(self.acc.username,901)
        self.acc.boya_all_courses[0]['courseCurrentCount']=3;self.assert_excluded()
        self.assertFalse(self.ledger.auto_select_excluded('fixture-decline-B',901))
        other=SimpleNamespace(username='fixture-decline-B',name='synthetic-B',removed=False,boya_all_courses=[valid_course(901)],boya_selected_courses=[],boya_pending_courses={},campus='北京',boya_health={})
        other.boya_client=DropClient(other)
        try:
            perform_boya_action(other,'select',901,automatic=True,ordinary=lambda *a:[])
            self.assertEqual(other.boya_client.selected_ids,[901]);self.assertEqual(self.client.selected_ids,[])
        finally:other.boya_client.http_client.close()
    def test_explicit_manual_selection_allowed_without_reenabling_automatic_regrab(self):
        perform_boya_action(self.acc,'drop',901) # stale or external drop is still explicit intent
        result=perform_boya_action(self.acc,'select',901)
        self.assertTrue(result['submitted']);self.assertEqual(self.client.select_call_count,1)
        self.assertTrue(self.ledger.auto_select_excluded(self.acc.username,901))
    def test_query_scope_change_does_not_invent_an_external_drop(self):
        self.acc.boya_selected_courses=[valid_course(901)];self.client.query_chosen_courses('2026-09-01','2026-12-31')
        self.acc.boya_selected_courses=[];self.client.query_chosen_courses('2026-10-01','2026-10-02')
        self.assertFalse(self.ledger.auto_select_excluded(self.acc.username,901))
    def test_failed_or_malformed_list_never_replaces_successful_snapshot(self):
        self.acc.boya_selected_courses=[valid_course(901)];self.client.query_chosen_courses()
        for reply in ({'data':{}},{'data':{'courseList':[{}]}}):
            with patch.object(self.client,'call',return_value=reply):
                with self.assertRaises(BoyaApiError):self.client.query_chosen_courses(*self.client.calendar_range)
        self.assertFalse(self.ledger.auto_select_excluded(self.acc.username,901))
        self.acc.boya_selected_courses=[];self.assert_excluded()
    def test_drop_disk_failure_prevents_school_post(self):
        self.acc.boya_selected_courses=[valid_course(901)]
        with patch.object(self.ledger,'exclude_auto_select',side_effect=sqlite3.OperationalError('synthetic disk full')):
            with self.assertRaises(sqlite3.OperationalError):perform_boya_action(self.acc,'drop',901)
        self.assertEqual(self.client.drop_count,0);self.assertEqual(self.client.select_call_count,0)
    def test_uncertain_drop_never_reenables_automatic_selection(self):
        self.acc.boya_selected_courses=[valid_course(901)]
        with patch.object(self.client,'drop_course',side_effect=httpx.ReadTimeout('synthetic uncertain result')) as dropped:
            with self.assertRaises(httpx.ReadTimeout):perform_boya_action(self.acc,'drop',901)
        dropped.assert_called_once_with(901)
        self.acc.boya_selected_courses=[];self.assert_excluded()
    def test_manual_new_choice_after_external_drop_preserves_daily_budget(self):
        self.auto();self.assertEqual(self.client.select_call_count,1)
        self.acc.boya_selected_courses=[];self.client.query_chosen_courses()
        quota=self.ledger.key(self.acc.username,'selection-budget',901,__import__('core.domain',fromlist=['now']).now().date())
        self.ledger.db.execute('UPDATE operations SET updated=0 WHERE key=?',(quota,));self.ledger.db.commit()
        result=perform_boya_action(self.acc,'select',901)
        self.assertTrue(result['submitted']);self.assertEqual(self.client.select_call_count,2)
        self.assertEqual(self.ledger.read(quota)[1],2);self.assertTrue(self.ledger.auto_select_excluded(self.acc.username,901))
    def test_positive_reappearance_does_not_remove_explicit_exclusion(self):
        self.ledger.exclude_auto_select(self.acc.username,901)
        self.acc.boya_selected_courses=[valid_course(901)];self.client.query_chosen_courses()
        self.acc.boya_selected_courses=[];self.assert_excluded()
    def test_final_send_guard_checks_new_intent_even_after_preflight(self):
        original=self.client.select_course
        def racing(cid):
            self.ledger.exclude_auto_select(self.acc.username,cid)
            return original(cid)
        with patch.object(self.client,'select_course',side_effect=racing):
            with self.assertRaises(BoyaApiError) as error:self.auto()
        self.assertEqual(error.exception.code,'user_declined');self.assertEqual(self.client.select_call_count,0)
    def test_excluding_one_course_still_allows_a_different_eligible_course(self):
        from core.boya_scheduler import BoyaScheduler
        self.ledger.exclude_auto_select(self.acc.username,901)
        self.acc.boya_all_courses.append(valid_course(902))
        logs=[];scheduler=BoyaScheduler(lambda:[self.acc],lambda *a,**k:logs.append((a,k)),ordinary_courses=lambda *a:[])
        scheduler._check_auto_select(self.acc,scheduler.clock())
        self.assertEqual(self.client.selected_ids,[902]);self.assertNotIn(901,self.client.selected_ids)
        normal=[kw for args,kw in logs if args[0]=='info'];self.assertTrue(normal);self.assertTrue(all(x['notify'] is False for x in normal))

class NormalNotificationContracts(unittest.TestCase):
    def test_normal_state_keeps_local_log_without_offering_a_wechat_notification(self):
        import server.app as app
        from unittest.mock import Mock
        engine=Mock()
        with patch.object(app,'wechat_notifications',engine),patch.object(app,'logs_list',[]):
            app.add_log('info','正常停止多抢',username='fixture-normal',category='boya',notify=False)
            engine.offer.assert_not_called();self.assertEqual(len(app.logs_list),1)
            app.add_log('warning','网络故障',username='fixture-normal',category='boya')
            engine.offer.assert_called_once()
        from core.wechat import WechatNotifications
        isolated=WechatNotifications(Path('unused-private-test'),lambda u:True,protocol=object())
        isolated.offer({'username':'fixture-normal','notify':False,'level':'info','category':'boya','message':'正常'})
        self.assertTrue(isolated.incoming.empty())
