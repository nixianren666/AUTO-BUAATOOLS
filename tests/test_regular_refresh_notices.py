import copy,datetime,unittest
from types import SimpleNamespace
from unittest.mock import patch
import server.app as app
from test_regular_course_policy import lesson,NOW

class NoticeContracts(unittest.TestCase):
    def setUp(self):
        self.acc=SimpleNamespace(username='fixture-notice-A',name='synthetic');self.logs=[]
        self.p=patch.object(app,'add_log',side_effect=lambda *a,**k:self.logs.append((a,k)));self.p.start()
        self.clock=patch.object(app,'china_now',return_value=NOW);self.clock.start()
    def tearDown(self):self.clock.stop();self.p.stop()
    def test_hundreds_of_unchanged_and_reordered_reads_emit_once(self):
        rows=[lesson(),lesson('102','902')]
        for i in range(500):app.note_regular_refresh(self.acc,list(reversed(rows)) if i%2 else rows)
        self.assertEqual(len(self.logs),1)
    def test_real_changes_same_count_and_attendance_status_are_visible(self):
        rows=[lesson()];app.note_regular_refresh(self.acc,rows)
        for field,value in [('teacherName','synthetic replacement'),('classroom','new room'),('signStatus',1)]:
            rows=copy.deepcopy(rows);rows[0][field]=value;app.note_regular_refresh(self.acc,rows);app.note_regular_refresh(self.acc,rows)
        self.assertEqual(len(self.logs),4);self.assertTrue(all(a[0]=='info' for a,_ in self.logs))
    def test_failure_dedup_recovery_and_later_failure_remain_visible(self):
        for _ in range(30):app.note_regular_refresh(self.acc,error='ReadTimeout')
        app.note_regular_refresh(self.acc,[]);app.note_regular_refresh(self.acc,[])
        app.note_regular_refresh(self.acc,error='ReadTimeout')
        self.assertEqual([a[0] for a,_ in self.logs],['error','info','error']);self.assertIn('恢复',self.logs[1][0][1])
    def test_students_and_new_day_have_independent_first_notice(self):
        app.note_regular_refresh(self.acc,[]);app.note_regular_refresh(SimpleNamespace(username='fixture-notice-B',name='synthetic-B'),[])
        with patch.object(app,'china_now',return_value=NOW+datetime.timedelta(days=1)):app.note_regular_refresh(self.acc,[])
        self.assertEqual(len(self.logs),3)
    def test_ui_only_policy_metadata_and_refresh_timestamps_do_not_spam(self):
        rows=[lesson()];app.note_regular_refresh(self.acc,rows)
        rows[0].update(auto_course={'paused':True},refreshed_at='new timestamp');app.note_regular_refresh(self.acc,rows)
        self.assertEqual(len(self.logs),1)

class ReadCadenceContracts(unittest.IsolatedAsyncioTestCase):
    async def test_read_calls_and_fresh_cache_updates_continue_while_notices_deduplicate(self):
        class Client:
            session_id='synthetic';calls=0
            def is_authenticated(self):return True
            async def get_today_classes(self):self.calls+=1;return [lesson()]
        acc=SimpleNamespace(username='fixture-notice-api',name='synthetic',removed=False,client=Client(),password='',last_classes=[],regular_health={})
        logs=[]
        with patch.object(app,'accounts',{acc.username:acc}),patch.object(app,'add_log',side_effect=lambda *a,**k:logs.append(a)):
            for _ in range(30):
                result=await app.get_today_classes(username=acc.username)
                self.assertEqual(len(result['classes']),1);self.assertEqual(result['status'],'success')
        self.assertEqual(acc.client.calls,30);self.assertEqual(len(logs),1);self.assertFalse(acc.regular_health['stale'])
