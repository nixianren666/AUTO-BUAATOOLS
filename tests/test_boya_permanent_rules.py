import unittest
from unittest.mock import patch
from core.boya_auto_rules import permanently_excluded
from core.boya_scheduler import is_auto_select_candidate
from core.boya_actions import perform_boya_action
from core.boya_client import BoyaApiError
from core.domain import now
import test_boya_declines as decline_fixtures

class SeriesRuleContracts(unittest.TestCase):
    def test_series_punctuation_new_ids_and_whitespace_cannot_bypass(self):
        for name in ['《“耕趣农场”劳动课》系列课程','耕趣农场劳动课（二）','耕 趣 农 场：秋季实践','耕\u200b趣农场劳动课']:
            self.assertTrue(permanently_excluded({'courseName':name}))
        self.assertFalse(permanently_excluded({'courseName':'其他农场劳动课'}));self.assertFalse(permanently_excluded({'courseName':'普通劳育实践'}))

class SeriesActionContracts(unittest.TestCase):
    setUp=decline_fixtures.DeclineContracts.setUp
    tearDown=decline_fixtures.DeclineContracts.tearDown
    auto=decline_fixtures.DeclineContracts.auto
    def test_series_candidate_and_automatic_final_guard_block_but_manual_choice_remains(self):
        course=self.acc.boya_all_courses[0];course['courseName']='《“耕趣农场”劳动课》系列课程'
        self.assertFalse(is_auto_select_candidate(course,now()))
        with self.assertRaises(BoyaApiError) as caught:self.auto()
        self.assertEqual(caught.exception.code,'permanently_excluded');self.assertEqual(self.client.select_call_count,0)
        self.assertTrue(perform_boya_action(self.acc,'select',901)['submitted']);self.assertEqual(self.client.select_call_count,1)
    def test_title_changed_between_preflight_and_actual_post_still_blocks(self):
        original=self.client.select_course
        def changed(cid):
            # The live preflight course object is checked again by the client's guard.
            self.acc.boya_all_courses[0]['courseName']='耕趣农场劳动课'
            return original(cid)
        with patch.object(self.client,'query_courses',return_value=self.acc.boya_all_courses),patch.object(self.client,'select_course',side_effect=changed):
            with self.assertRaises(BoyaApiError) as caught:self.auto()
        self.assertEqual(caught.exception.code,'permanently_excluded');self.assertEqual(self.client.select_call_count,0)
