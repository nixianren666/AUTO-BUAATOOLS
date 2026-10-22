"""TD integration: synthetic identities/media only; no campus network writes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.td_client import TDClient, TDRejected, TDUncertain, DEVICES
from core.td_store import TDStore, owner_key
from core.td_scheduler import TDEngine, TZ
from server.management import install as install_management
from server.td_routes import install


def jpeg(color='navy'):
    stream = io.BytesIO(); Image.new('RGB', (120, 90), color).save(stream, 'JPEG'); return stream.getvalue()


class FakeLicense:
    active=True
    expires_epoch=4102444799
    def status(self,user):return {'active':self.active,'expires_epoch':self.expires_epoch,'expires_at':'2099-12-31T23:59:59+08:00','reason':'' if self.active else 'TD未激活或已到期'}
    def close(self):pass


class FakeClient:
    def __init__(self): self.calls = []; self.count = None; self.error = None
    def check(self, user, device, stamp, guard):
        if not guard(): raise TDUncertain()
        self.calls.append(('check', user, device, stamp))
        if self.error: raise self.error
        return self.count
    def photo(self, device, stamp, photo, guard):
        if not guard(): raise TDUncertain()
        self.calls.append(('photo', device, stamp, photo))


class TDStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = TDStore(Path(self.temp.name)/'private'); self.addCleanup(self.store.db.close)
        self.now = datetime(2026, 10, 19, 8, 0, tzinfo=TZ)
        self.user = '90101'  # Deliberately synthetic, not a real student identifier.
        self.accounts = {self.user: SimpleNamespace(removed=False)}
        self.client = FakeClient(); self.logs=[];self.license=FakeLicense()
        self.engine = TDEngine(self.store,self.accounts.get,lambda *a,**kw:self.logs.append((a,kw)),self.client,lambda:self.now,licensing=self.license,schedule_delay=lambda maximum:0)
        self.settings=dict(campus='学院路',semester_start='2026-09-01',semester_end='2027-01-31',start='2026-10-01',end='2026-12-31',target=32,daily_limit=3,confirmed=True,weekdays=list(range(7)),closed_dates=[])
        self.store.configure(self.user,self.settings)
        self.images=[self.store.add_image(self.user,jpeg(color))['id'] for color in ['navy','purple','teal']]
        self.groups=[self.store.create_group(self.user,self.images[i],self.images[(i+1)%3],f'Synthetic group {i}',True)['id'] for i in range(3)]
        self.engine.toggle(self.user,True)
    def job(self): return self.store.job(owner_key(self.user),self.now.date().isoformat())
    def advance_due(self): self.now=datetime.fromtimestamp(self.job()['due']+.05,TZ)
    def run_pair(self): self.engine.tick(self.user); self.advance_due(); self.engine.tick(self.user)

    def test_pair_uses_distinct_images_and_same_phase_timestamp(self):
        self.run_pair(); self.assertEqual(self.job()['completed'],1)
        calls=self.client.calls; self.assertEqual(len(calls),4)
        self.assertEqual(calls[0][3],calls[1][2]); self.assertEqual(calls[2][3],calls[3][2])
        self.assertNotEqual(calls[1][3],calls[3][3])
    def test_unlicensed_and_expired_stop_both_paths_without_claiming_budget(self):
        self.license.active=False;self.engine.tick(self.user)
        self.assertFalse(self.store.profile(owner_key(self.user))['enabled']);self.assertEqual(self.client.calls,[]);self.assertEqual(self.job()['attempted'],0)
        with self.assertRaises(ValueError):self.engine.toggle(self.user,True)
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
    def test_near_license_expiry_blocks_new_entry_but_preserves_existing_exit(self):
        self.license.expires_epoch=self.now.timestamp()+429;self.engine.tick(self.user);self.assertEqual(self.client.calls,[])
        self.license.expires_epoch=self.now.timestamp()+1600;self.engine.tick(self.user);self.advance_due();self.license.expires_epoch=self.now.timestamp()+10
        self.engine.tick(self.user);self.assertEqual(self.job()['completed'],1)
    def test_expiry_between_entry_and_exit_never_resends_or_refunds(self):
        self.engine.tick(self.user);self.advance_due();self.license.active=False;self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),2);self.assertEqual(self.job()['attempted'],1);self.assertEqual(self.job()['state'],'waiting_exit')
    def test_license_rechecked_immediately_before_photo_write(self):
        check=self.client.check
        def expire(*args):
            result=check(*args);self.license.active=False;return result
        self.client.check=expire;self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),1);self.assertEqual(self.job()['state'],'uncertain');self.assertEqual(self.job()['attempted'],1)
    def test_three_round_shared_budget_no_fourth_entry(self):
        for _ in range(3):
            self.run_pair(); self.advance_due()
        self.engine.tick(self.user)
        self.assertEqual(self.job()['attempted'],3); self.assertEqual(len(self.client.calls),12)
    def test_restart_pending_does_not_replay(self):
        with self.store.transaction():
            self.store.save_job(owner_key(self.user),self.now.date().isoformat(),dict(state='sending_entry',attempted=1,completed=0,entry_at=self.now.timestamp()))
        self.engine.tick(self.user); self.assertEqual(self.client.calls,[])
    def test_waiting_exit_resumes_from_persisted_state(self):
        self.engine.tick(self.user); self.advance_due()
        other=TDStore(self.store.root); self.addCleanup(other.db.close)
        engine=TDEngine(other,self.accounts.get,lambda *a,**kw:None,self.client,lambda:self.now,licensing=self.license,schedule_delay=lambda maximum:0)
        engine.tick(self.user); self.assertEqual(self.job()['completed'],1); self.assertEqual(len(self.client.calls),4)
    def test_photo_failure_stops_without_count_or_success(self):
        self.client.count=12
        self.client.photo=lambda *args: (_ for _ in ()).throw(TDUncertain())
        self.engine.tick(self.user); self.engine.tick(self.user)
        self.assertEqual(self.job()['state'],'uncertain'); self.assertEqual(len(self.client.calls),1)
        self.assertIsNone(self.engine.status(self.user)['progress']['count'])
    def test_explicit_failure_consumes_budget_and_stops(self):
        self.client.error=TDRejected(); self.engine.tick(self.user)
        self.assertEqual(self.job()['attempted'],1); self.assertEqual(self.job()['state'],'rejected')
        self.assertFalse(self.engine.status(self.user)['settings']['enabled'])
    def test_timeout_does_not_upload_or_replay(self):
        self.client.error=TimeoutError(); self.engine.tick(self.user); self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),1); self.assertEqual(self.job()['state'],'uncertain')
    def test_expired_exit_fails_closed(self):
        self.engine.tick(self.user); self.now+=timedelta(seconds=420); self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),2); self.assertEqual(self.job()['state'],'uncertain')
    def test_pause_does_not_send_exit(self):
        self.engine.tick(self.user); self.engine.toggle(self.user,False); self.advance_due(); self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),2)
    def test_resume_still_valid_exit(self):
        self.engine.tick(self.user); self.engine.toggle(self.user,False); self.advance_due(); self.engine.toggle(self.user,True); self.engine.tick(self.user)
        self.assertEqual(self.job()['completed'],1)
    def test_cross_day_cannot_pair_old_exit_or_silently_start(self):
        self.engine.tick(self.user); self.now+=timedelta(days=1); self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),2); self.assertFalse(self.engine.status(self.user)['settings']['enabled'])
    def test_entry_not_started_near_window_close(self):
        self.now=self.now.replace(hour=9,minute=56); self.engine.tick(self.user); self.assertEqual(self.client.calls,[])
    def test_outside_activity_or_window_no_write(self):
        for time in [self.now.replace(hour=10),self.now.replace(month=9)]:
            self.now=time; self.engine.tick(self.user)
        self.assertEqual(self.client.calls,[])
    def test_removed_account_guard_blocks_writes(self):
        self.accounts[self.user].removed=True; self.engine.tick(self.user); self.assertEqual(self.client.calls,[])
    def test_remove_during_check_prevents_photo(self):
        original=self.client.check
        def remove(*args):
            result=original(*args); self.accounts[self.user].removed=True; return result
        self.client.check=remove; self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),1); self.assertEqual(self.job()['state'],'uncertain')
    def test_shutdown_prevents_writes(self):
        self.engine.stopping=True; self.engine.tick(self.user); self.assertEqual(self.client.calls,[])
    def test_server_target_reached_stops_future_round_not_pair(self):
        self.client.count=32; self.run_pair(); self.advance_due(); self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),4); self.assertEqual(self.job()['completed'],1)
    def test_manual_target_stops_new_writes_without_claiming_official_result(self):
        self.engine.record_count(self.user,32); self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),0); self.assertEqual(self.engine.status(self.user)['progress']['count_source'],'manual')
    def test_count_unknown_not_zero_and_status_performs_no_network(self):
        for _ in range(3): self.assertIsNone(self.engine.status(self.user)['progress']['count'])
        self.assertEqual(self.client.calls,[])
    def test_new_period_clears_prior_count_and_pauses(self):
        self.engine.record_count(self.user,32)
        self.store.configure(self.user,{**self.settings,'semester_start':'2026-09-02'})
        state=self.engine.status(self.user)
        self.assertIsNone(state['progress']['count']); self.assertFalse(state['settings']['enabled'])
    def test_cannot_change_rules_during_pair(self):
        self.engine.tick(self.user)
        with self.assertRaises(ValueError): self.store.configure(self.user,{**self.settings,'campus':'沙河'})
    def test_resolve_does_not_refund_budget_or_add_success(self):
        self.client.error=TimeoutError(); self.engine.tick(self.user)
        with self.assertRaises(ValueError): self.engine.resolve(self.user,True)
        self.now+=timedelta(seconds=431); self.engine.resolve(self.user,True)
        self.assertEqual(self.job()['attempted'],1); self.assertEqual(self.job()['completed'],0)
        self.assertFalse(self.engine.status(self.user)['settings']['enabled'])
    def test_concurrent_engines_claim_once(self):
        other=TDStore(self.store.root); self.addCleanup(other.db.close)
        engine=TDEngine(other,self.accounts.get,lambda *a,**kw:None,self.client,lambda:self.now,licensing=self.license,schedule_delay=lambda maximum:0)
        with ThreadPoolExecutor(2) as pool: list(pool.map(lambda e:e.tick(self.user),[self.engine,engine]))
        self.assertEqual(self.job()['attempted'],1); self.assertEqual(len(self.client.calls),2)
    def test_media_isolation_and_path_traversal(self):
        for owner,image in [('90102',self.images[0]),(self.user,'../state.sqlite')]:
            with self.assertRaises(ValueError): self.store.read_image(owner,image)
    def test_duplicate_image_has_one_record(self):
        result=self.store.add_image(self.user,jpeg('navy'))
        self.assertTrue(result['duplicate']); self.assertEqual(len(self.engine.status(self.user)['images']),3)
    def test_html_and_invalid_images_rejected(self):
        for payload in [b'<html>bad</html>',b'',b'x'*(8*1024*1024+1)]:
            with self.assertRaises(ValueError): self.store.add_image(self.user,payload)
    def test_metadata_removed(self):
        image=Image.new('RGB',(30,30),'red'); exif=Image.Exif(); exif[0x010e]='synthetic-private-metadata'
        stream=io.BytesIO();image.save(stream,'JPEG',exif=exif)
        image_id=self.store.add_image(self.user,stream.getvalue())['id']
        result=self.store.read_image(self.user,image_id)
        self.assertNotIn(b'synthetic-private-metadata',result)
        self.assertFalse(Image.open(io.BytesIO(result)).getexif())
    def test_busy_images_cannot_be_deleted(self):
        self.engine.tick(self.user)
        with self.assertRaises(ValueError): self.store.delete_images(self.user,[self.job()['entry_image']])
    def test_batch_delete_validates_every_id_before_deleting(self):
        with self.assertRaises(ValueError): self.store.delete_images(self.user,[self.images[0],'0'*32])
        self.assertTrue(self.store.read_image(self.user,self.images[0]))
    def test_batch_file_lock_rolls_back_database_and_prior_files(self):
        with self.store.transaction():self.store.db.execute('DELETE FROM photo_groups')
        rename = Path.rename
        calls = []
        def locked(path, target):
            calls.append(path)
            if len(calls) == 3:
                raise PermissionError('synthetic file lock')
            return rename(path,target)
        with patch.object(Path,'rename',locked):
            with self.assertRaises(PermissionError): self.store.delete_images(self.user,self.images[:2])
        for image in self.images: self.assertTrue(self.store.read_image(self.user,image))
        self.assertEqual(len(self.engine.status(self.user)['images']),3)
    def test_batch_cleanup_lock_is_reported_without_publicly_serving_trash(self):
        with self.store.transaction():self.store.db.execute('DELETE FROM photo_groups')
        unlink = Path.unlink
        def locked(path,*args,**kwargs):
            if '.delete-' in path.name: raise PermissionError('synthetic cleanup lock')
            return unlink(path,*args,**kwargs)
        with patch.object(Path,'unlink',locked):
            result=self.store.delete_images(self.user,[self.images[0]])
        self.assertEqual(result['cleanup_pending'],2)
        with self.assertRaises(ValueError): self.store.read_image(self.user,self.images[0])
    def test_next_round_avoids_last_group_when_multiple_available(self):
        self.run_pair(); last=self.job()['group_id']; self.advance_due(); self.engine.tick(self.user)
        self.assertNotEqual(last,self.job()['group_id'])
    def test_no_photo_directory_contains_student_identifier(self):
        self.assertFalse((self.store.root/self.user).exists())
        self.assertTrue((self.store.root/owner_key(self.user)).is_dir())
    def test_confirmed_dates_and_limit_required(self):
        for overrides in [dict(confirmed=False),dict(daily_limit=4),dict(end='2026-09-01')]:
            with self.assertRaises(ValueError): self.store.configure(self.user,{**self.settings,**overrides})
    def test_round_freezes_group_and_roles(self):
        self.engine.tick(self.user);job=dict(self.job())
        group=next(g for g in self.store.groups(owner_key(self.user)) if g['id']==job['group_id'])
        self.assertEqual((job['entry_image'],job['exit_image']),(group['entry_image'],group['exit_image']))
        self.advance_due();self.engine.tick(self.user)
        self.assertEqual(self.job()['group_id'],group['id'])
    def test_legacy_loose_images_cannot_enable_new_rounds(self):
        self.engine.toggle(self.user,False)
        with self.store.transaction():self.store.db.execute('DELETE FROM photo_groups')
        with self.assertRaises(ValueError):self.engine.toggle(self.user,True)
        self.assertEqual(len(self.store.images(owner_key(self.user))),3)
    def test_group_import_is_complete_before_visibility(self):
        before=len(self.store.groups(owner_key(self.user)))
        with self.assertRaises(ValueError):self.store.import_group(self.user,jpeg('red'),b'not an image','Pair',True)
        self.assertEqual(len(self.store.groups(owner_key(self.user))),before)
        self.assertEqual(len(self.store.images(owner_key(self.user))),3)
    def test_group_requires_attire_confirmation_and_owned_images(self):
        with self.assertRaises(ValueError):self.store.create_group(self.user,*self.images[:2],'Pair',False)
        with self.assertRaises(ValueError):self.store.create_group('90102',*self.images[:2],'Pair',True)
    def test_same_photo_may_fill_both_roles(self):
        result=self.store.create_group(self.user,self.images[0],self.images[0],'Same photo',True)
        self.assertIn(result['id'],[g['id'] for g in self.store.groups(owner_key(self.user))])
    def test_duplicate_pair_does_not_create_extra_group(self):
        result=self.store.create_group(self.user,*self.images[:2],'Duplicate',True)
        self.assertTrue(result['duplicate']);self.assertEqual(len(self.store.groups(owner_key(self.user))),3)
    def test_busy_group_and_referenced_photos_cannot_be_deleted(self):
        self.engine.tick(self.user)
        with self.assertRaises(ValueError):self.store.delete_groups(self.user,[self.job()['group_id']])
        with self.assertRaises(ValueError):self.store.delete_images(self.user,[self.images[0]])
    def test_group_delete_keeps_photos_referenced_by_other_groups(self):
        self.store.delete_groups(self.user,[self.groups[0]])
        self.assertEqual(len(self.store.groups(owner_key(self.user))),2)
        for image in self.images:self.assertTrue(self.store.read_image(self.user,image))
    def test_activity_must_fit_semester_boundaries(self):
        for overrides in [dict(start='2026-08-31'),dict(end='2027-02-01'),dict(semester_end='2026-08-01')]:
            with self.assertRaises(ValueError):self.engine.configure(self.user,{**self.settings,**overrides})
    def test_cached_official_calendar_cannot_be_overridden(self):
        self.accounts[self.user].boya_client=SimpleNamespace(semester_info={'semesterStartDate':'2026-09-01','semesterEndDate':'2027-01-20'})
        with self.assertRaises(ValueError):self.engine.configure(self.user,self.settings)
        self.engine.tick(self.user);self.assertEqual(self.client.calls,[])
    def test_editing_activity_preserves_same_semester_count_and_day_budget(self):
        self.engine.record_count(self.user,12);self.run_pair()
        with self.assertRaises(ValueError):self.engine.configure(self.user,{**self.settings,'start':'2026-10-02'})
        self.engine.toggle(self.user,False)
        self.engine.configure(self.user,{**self.settings,'start':'2026-10-02'})
        self.assertEqual(self.job()['attempted'],1)
        self.assertEqual(self.engine.status(self.user)['progress']['count'],12)
    def test_new_official_term_hides_old_count_without_erasing_history(self):
        self.engine.record_count(self.user,12)
        self.accounts[self.user].boya_client=SimpleNamespace(semester_info={'semesterStartDate':'2027-02-01','semesterEndDate':'2027-07-01'})
        status=self.engine.status(self.user)
        self.assertFalse(status['rules_valid'])
        self.assertEqual(status['progress'],dict(count=None,count_source='out_of_scope',count_at=None))
        self.assertEqual(self.store.profile(owner_key(self.user))['count'],12)
        self.engine.tick(self.user);self.assertEqual(self.client.calls,[])
    def test_expired_term_count_stays_hidden_across_restart(self):
        self.engine.record_count(self.user,12);self.now=datetime(2027,3,1,8,tzinfo=TZ)
        other=TDStore(self.store.root);self.addCleanup(other.db.close)
        engine=TDEngine(other,self.accounts.get,lambda *a,**k:None,self.client,lambda:self.now,licensing=self.license,schedule_delay=lambda maximum:0)
        self.assertIsNone(engine.status(self.user)['progress']['count'])
        self.assertEqual(other.profile(owner_key(self.user))['count'],12)
    def test_current_term_count_survives_activity_end_and_same_calendar(self):
        self.engine.record_count(self.user,12)
        self.accounts[self.user].boya_client=SimpleNamespace(semester_info={'semesterStartDate':'2026-09-01','semesterEndDate':'2027-01-31'})
        self.now=datetime(2027,1,1,8,tzinfo=TZ)
        self.assertEqual(self.engine.status(self.user)['progress']['count'],12)
        self.engine.tick(self.user);self.assertEqual(self.client.calls,[])
    def test_negative_or_unknown_reply_never_advances_to_photo(self):
        for message in ['未刷卡成功','本次未刷卡成功','不是刷卡成功','刷卡成功但状态未知','示例：刷卡成功']:
            with self.subTest(message=message):
                protocol=TDClient();writes=[]
                protocol.request=lambda *args:{'status':'success','srvresp':message}
                protocol.photo=lambda *args:writes.append(True)
                self.engine.client=protocol;self.engine.tick(self.user)
                self.assertIn(self.job()['state'],('rejected','uncertain'))
                self.assertEqual(writes,[]);self.assertEqual(self.job()['attempted'],1)
                self.engine.tick(self.user);self.assertEqual(self.job()['attempted'],1)
                # A new fixture day is explicitly isolated; no budget is reset.
                self.now+=timedelta(days=1);self.engine.toggle(self.user,False)
                self.now+=timedelta(seconds=431);self.engine.resolve(self.user,True)
                self.engine.toggle(self.user,True)
    def test_tampered_daily_limit_cannot_send(self):
        with self.store.transaction():
            p=self.store.profile(owner_key(self.user));p['daily_limit']=99;self.store.save_profile(owner_key(self.user),p)
        self.engine.tick(self.user);self.assertEqual(self.client.calls,[])


    def test_manual_pair_paused_shared_budget_and_fixed_group(self):
        self.engine.toggle(self.user,False)
        self.assertTrue(self.engine.status(self.user)['manual']['allowed'])
        self.engine.manual(self.user,'entry',True)
        frozen=dict(self.job());self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),2)
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        with self.assertRaises(ValueError):self.engine.manual(self.user,'exit',True)
        self.advance_due();self.engine.manual(self.user,'exit',True)
        self.assertEqual(self.job()['completed'],1);self.assertEqual(self.job()['attempted'],1)
        self.assertEqual(self.client.calls[3][3],self.store.read_image(self.user,frozen['exit_image']))
        self.assertFalse(self.engine.status(self.user)['settings']['enabled'])

    def test_batch_manual_one_start_completes_three_pairs_and_stops(self):
        self.engine.toggle(self.user,False)
        self.assertTrue(self.engine.start_batch(self.user,True)['queued'])
        self.assertEqual(self.client.calls,[])
        for _ in range(6):
            self.engine.tick(self.user)
            self.advance_due()
        self.assertEqual((self.job()['attempted'],self.job()['completed']),(3,3))
        self.assertFalse(self.job()['batch_active'])
        self.assertFalse(self.engine.status(self.user)['settings']['enabled'])
        self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),12)
        with self.assertRaises(ValueError):self.engine.start_batch(self.user,True)

    def test_batch_parallel_starts_are_one_persisted_queue(self):
        self.engine.toggle(self.user,False)
        def start(_):
            try:self.engine.start_batch(self.user,True);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(start,range(8)))
        self.assertEqual(sum(results),1);self.assertEqual(self.job()['attempted'],0)
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        with self.assertRaises(ValueError):self.engine.toggle(self.user,True)

    def test_batch_manual_existing_budget_only_finishes_remaining_rounds(self):
        self.run_pair();self.engine.toggle(self.user,False)
        self.engine.start_batch(self.user,True)
        self.engine.tick(self.user);self.assertEqual(self.job()['attempted'],1)
        self.advance_due()
        for _ in range(4):self.engine.tick(self.user);self.advance_due()
        self.assertEqual((self.job()['attempted'],self.job()['completed']),(3,3))
        self.assertEqual(len(self.client.calls),12)

    def test_batch_pause_and_resume_pending_exit_never_repeats_entry(self):
        self.engine.toggle(self.user,False);self.engine.start_batch(self.user,True);self.engine.tick(self.user)
        self.engine.toggle(self.user,False);self.advance_due();self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),2)
        self.engine.start_batch(self.user,True);self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),4);self.assertEqual(self.job()['completed'],1)

    def test_batch_failure_and_restart_never_replay_pending_write(self):
        self.engine.toggle(self.user,False);self.engine.start_batch(self.user,True)
        self.client.error=TimeoutError();self.engine.tick(self.user)
        other=TDStore(self.store.root);self.addCleanup(other.db.close)
        engine=TDEngine(other,self.accounts.get,lambda *a,**kw:None,self.client,lambda:self.now,licensing=self.license,schedule_delay=lambda maximum:0)
        engine.tick(self.user)
        with self.assertRaises(ValueError):engine.start_batch(self.user,True)
        self.assertEqual(len(self.client.calls),1);self.assertEqual(self.job()['attempted'],1)
        self.assertFalse(self.job()['batch_active'])

    def test_batch_restart_preserves_due_and_pair_without_new_click(self):
        self.engine.toggle(self.user,False);self.engine.start_batch(self.user,True);self.engine.tick(self.user)
        before=dict(self.job());other=TDStore(self.store.root);self.addCleanup(other.db.close)
        engine=TDEngine(other,self.accounts.get,lambda *a,**kw:None,self.client,lambda:self.now,licensing=self.license,schedule_delay=lambda maximum:0)
        engine.tick(self.user);self.assertEqual(self.job(),before);self.assertEqual(len(self.client.calls),2)
        self.advance_due();engine.tick(self.user)
        self.assertEqual(self.job()['completed'],1);self.assertEqual(len(self.client.calls),4)

    def test_batch_auto_randomizes_only_first_start_then_uses_pair_intervals(self):
        calls=[]
        self.engine.schedule_delay=lambda maximum:(calls.append(maximum) or 60)
        self.engine.tick(self.user)
        self.assertEqual(len(calls),1);self.assertEqual(self.client.calls,[])
        self.assertEqual(self.job()['due'],self.now.timestamp()+60)
        self.engine.tick(self.user);self.assertEqual(len(calls),1)
        self.advance_due()
        for _ in range(6):self.engine.tick(self.user);self.advance_due()
        self.assertEqual(len(calls),1);self.assertEqual(self.job()['completed'],3)

    def test_batch_requires_full_remaining_window_and_license_margin(self):
        self.engine.toggle(self.user,False);self.now=self.now.replace(hour=9,minute=50)
        with self.assertRaises(ValueError):self.engine.start_batch(self.user,True)
        self.assertFalse(self.engine.status(self.user)['batch']['allowed'])
        self.now=self.now.replace(hour=8,minute=0);self.license.expires_epoch=self.now.timestamp()+1000
        with self.assertRaises(ValueError):self.engine.start_batch(self.user,True)
        self.assertEqual(self.client.calls,[]);self.assertEqual(self.job()['attempted'],0)

    def test_batch_closed_window_or_new_day_never_sends_late_queue(self):
        self.engine.toggle(self.user,False);self.engine.start_batch(self.user,True);self.engine.tick(self.user)
        self.now=self.now.replace(hour=11,minute=35);self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),2);self.assertFalse(self.job()['batch_active'])
        self.assertEqual(self.job()['state'],'uncertain')
        self.now+=timedelta(days=1);self.engine.tick(self.user)
        self.assertEqual(self.job()['attempted'],0);self.assertEqual(len(self.client.calls),2)

    def test_batch_status_is_readable_while_sending_and_does_not_trigger_requests(self):
        self.engine.toggle(self.user,False);self.engine.start_batch(self.user,True)
        entered=threading.Event();release=threading.Event();original=self.client.check
        def slow(*args):
            entered.set();release.wait(3);return original(*args)
        self.client.check=slow
        with ThreadPoolExecutor(max_workers=2) as pool:
            future=pool.submit(self.engine.tick,self.user)
            self.assertTrue(entered.wait(1))
            try:
                status=pool.submit(self.engine.status,self.user).result(timeout=1)
                self.assertEqual(status['task']['state'],'sending_entry');self.assertFalse(status['batch']['allowed'])
            finally:release.set()
            future.result(timeout=2)
        self.assertEqual(len(self.client.calls),2)

    def test_batch_old_process_sending_state_is_uncertain_not_in_progress(self):
        with self.store.transaction():
            self.store.save_job(owner_key(self.user),self.now.date().isoformat(),dict(state='sending_entry',attempted=1,completed=0,
                due=0,entry_at=self.now.timestamp(),batch_active=True,batch_mode='manual',batch_window_end=self.now.timestamp()+3600,sender_process='synthetic-prior-process'))
        self.assertEqual(self.engine.status(self.user)['task']['state'],'uncertain')
        self.engine.tick(self.user)
        self.assertEqual(self.job()['state'],'uncertain');self.assertFalse(self.job()['batch_active'])
        self.assertEqual(self.job()['attempted'],1);self.assertEqual(self.client.calls,[])
    def test_manual_rejects_auto_enabled_unconfirmed_or_wrong_phase(self):
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        self.engine.toggle(self.user,False)
        for phase,confirmed in [('entry',False),('exit',True)]:
            with self.assertRaises(ValueError):self.engine.manual(self.user,phase,confirmed)
        self.assertEqual(self.client.calls,[])
    def test_manual_three_round_budget_also_blocks_automatic(self):
        self.engine.toggle(self.user,False)
        for _ in range(3):
            self.engine.manual(self.user,'entry',True);self.advance_due();self.engine.manual(self.user,'exit',True);self.advance_due()
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        self.engine.toggle(self.user,True);self.engine.tick(self.user)
        self.assertEqual(len(self.client.calls),12);self.assertEqual(self.job()['attempted'],3)
    def test_manual_failure_no_replay_and_restart_shared(self):
        self.engine.toggle(self.user,False);self.client.error=TimeoutError()
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        other=TDStore(self.store.root);self.addCleanup(other.db.close)
        engine=TDEngine(other,self.accounts.get,lambda *a,**kw:None,self.client,lambda:self.now,licensing=self.license,schedule_delay=lambda maximum:0)
        with self.assertRaises(ValueError):engine.manual(self.user,'entry',True)
        self.assertEqual(len(self.client.calls),1);self.assertEqual(self.job()['attempted'],1)
    def test_manual_concurrent_entry_only_one_claim(self):
        self.engine.toggle(self.user,False)
        def submit(_):
            try:self.engine.manual(self.user,'entry',True);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:result=list(pool.map(submit,range(8)))
        self.assertEqual(sum(result),1);self.assertEqual(len(self.client.calls),2);self.assertEqual(self.job()['attempted'],1)
    def test_manual_due_deadline_and_closing_guards(self):
        self.engine.toggle(self.user,False);self.now=self.now.replace(hour=9,minute=53)
        with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        self.now=self.now.replace(hour=8,minute=0);self.engine.manual(self.user,'entry',True)
        self.now+=timedelta(seconds=420)
        with self.assertRaises(ValueError):self.engine.manual(self.user,'exit',True)
        self.assertEqual(len(self.client.calls),2)
    def test_unconfirmed_open_weekdays_and_closed_dates_fail_closed(self):
        for patch_settings in [{'weekdays':[]},{'weekdays':[True]},{'weekdays':[0,0]},{'weekdays':[7]},{'closed_dates':['2026-13-01']},{'closed_dates':['2027-02-01']}]:
            with self.assertRaises(ValueError):self.engine.configure(self.user,{**self.settings,**patch_settings})
        for patch_settings in [{'weekdays':[1,2,3,4,5,6]},{'closed_dates':['2026-10-19']}]:
            self.engine.configure(self.user,{**self.settings,**patch_settings})
            self.engine.toggle(self.user,True);self.engine.tick(self.user);self.engine.toggle(self.user,False)
            with self.assertRaises(ValueError):self.engine.manual(self.user,'entry',True)
        self.assertEqual(self.client.calls,[])
    def test_opening_window_boundaries_and_explicit_weekend(self):
        from core.td_scheduler import window_end
        for hour,minute,allowed in [(7,29,False),(7,30,True),(10,0,False),(11,29,False),(11,30,True),(14,0,False),(15,29,False),(15,30,True),(20,0,False)]:
            self.assertEqual(window_end(self.now.replace(hour=hour,minute=minute)) is not None,allowed)
        self.engine.configure(self.user,{**self.settings,'weekdays':[5,6]});self.now=self.now.replace(day=24)
        self.assertTrue(self.engine.status(self.user)['manual']['allowed'])
    def test_pending_pair_policy_edit_is_blocked_without_losing_pair(self):
        self.engine.tick(self.user)
        with self.assertRaises(ValueError):self.engine.configure(self.user,{**self.settings,'closed_dates':['2026-10-19']})
        self.assertEqual(self.job()['state'],'waiting_exit');self.assertEqual(self.job()['attempted'],1)


class TDProtocolTests(unittest.TestCase):
    def test_negative_success_substring_and_unknown_not_accepted(self):
        for message in ['未成功','刷卡未成功','不成功','刷卡成功但照片失败','success','处理完成']:
            client=TDClient();client.request=lambda *a:{'status':'success','srvresp':message}
            with self.assertRaises((TDRejected,TDUncertain)): client.check('90101',DEVICES['学院路'][0],1,lambda:True)
    def test_negative_embedded_or_contradictory_success_is_never_accepted(self):
        for message in ['未刷卡成功','本次未刷卡成功','未能打卡成功','不是签到成功','不能签退成功',
                        '刷卡成功状态为否','刷卡成功，未通过','刷卡成功，禁止提交','示例：刷卡成功',
                        '可能刷卡成功','刷卡成功？','刷卡成功, 本学期锻炼次数：12345','刷卡成功, 本学期锻炼次数：-1']:
            with self.subTest(message=message):
                client=TDClient();client.request=lambda *a:{'status':'success','srvresp':message}
                with self.assertRaises((TDRejected,TDUncertain)):client.check('90101',DEVICES['学院路'][0],1,lambda:True)
    def test_supported_positive_reply_forms_and_bounded_counter(self):
        for message,expected in [('刷卡成功',None),(' 签到成功！ ',None),('打卡成功\n本学期锻炼次数: 0',0),
                                 ('签退成功；本学期锻炼次数：12次。',12),('刷卡成功, 本学期锻炼次数：9999',9999)]:
            with self.subTest(message=message):
                client=TDClient();client.request=lambda *a:{'status':'success','srvresp':message}
                self.assertEqual(client.check('90101',DEVICES['学院路'][0],1,lambda:True),expected)
    def test_denied_preflight_does_not_even_create_socket(self):
        created=[]
        def factory(*args):created.append(True);raise AssertionError('Unexpected socket')
        with self.assertRaises(TDUncertain):TDClient(factory).request(80,b'{}',lambda:False)
        self.assertEqual(created,[])
    def test_slow_connect_crossing_guard_never_sends_payload(self):
        allowed=[True];sent=[]
        class Sock:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,value):pass
            def connect(self,target):allowed[0]=False
            def sendall(self,data):sent.append(data)
        with self.assertRaises(TDUncertain):TDClient(lambda *a:Sock()).request(80,b'{}',lambda:allowed[0])
        self.assertEqual(sent,[])
    def test_partial_slow_response_cannot_extend_total_deadline(self):
        clock=[0.0];sent=[]
        class Sock:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def settimeout(self,value):self.timeout=value
            def connect(self,target):pass
            def sendall(self,data):sent.append(data)
            def recv(self,size):clock[0]+=3;return b'\x00'
        with patch('core.td_client.time.monotonic',lambda:clock[0]):
            with self.assertRaises(TDUncertain):TDClient(lambda *a:Sock()).request(80,b'{}',lambda:True)
        self.assertEqual(len(sent),1)
        self.assertLessEqual(clock[0],12)
    def test_photo_negative_or_malformed_acknowledgement_stays_uncertain(self):
        for message in ['未上传成功','本次未接收','不成功','照片无效',{'success':True},False]:
            client=TDClient();client.request=lambda *a:{'status':'success','srvresp':message}
            with self.assertRaises(TDUncertain):client.photo(DEVICES['学院路'][0],1,b'synthetic',lambda:True)
    def test_positive_count_and_identity_only_fields(self):
        client=TDClient(); sent=[]
        def request(kind,body,guard): sent.append(json.loads(body)); return {'status':'success','srvresp':'刷卡成功, 本学期锻炼次数：12'}
        client.request=request
        self.assertEqual(client.check('90101',DEVICES['学院路'][0],1.234,lambda:True),12)
        self.assertEqual(sent[0]['timestamp'],'1234'); self.assertNotIn('password',sent[0])
        self.assertEqual(set(sent[0]),{'cardno','userno','timestamp','type','eventno','ln','sn','schoolno'})
    def test_total_frame_bounds_and_guard(self):
        class Sock:
            def __init__(self,data): self.data=data;self.sent=[]
            def __enter__(self): return self
            def __exit__(self,*a): pass
            def settimeout(self,t): pass
            def connect(self,target): self.target=target
            def sendall(self,data): self.sent.append(data)
            def recv(self,n): data,self.data=self.data[:min(2,n)],self.data[min(2,n):]; return data
        for size,code in [(0,80),(65537,80),(5,100)]:
            sock=Sock(struct.pack('>lB',size,code))
            with self.assertRaises(TDUncertain): TDClient(lambda *a:sock).request(80,b'{}',lambda:True)
        sock=Sock(b'');
        with self.assertRaises(TDUncertain): TDClient(lambda *a:sock).request(80,b'{}',lambda:False)
        self.assertFalse(sock.sent)
        body=b'{"status":"success"}';sock=Sock(struct.pack('>lB',len(body),80)+body)
        self.assertEqual(TDClient(lambda *a:sock).request(80,b'{}',lambda:True)['status'],'success')


class TDAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.accounts={'90101':SimpleNamespace(removed=False),'90102':SimpleNamespace(removed=False)}
        def resolve(user):
            if user not in self.accounts:
                from fastapi import HTTPException
                raise HTTPException(404,'missing')
            return self.accounts[user]
        self.app=FastAPI(); install_management(self.app)
        self.remove=install(self.app,Path(self.temp.name)/'config.json',resolve,self.accounts,lambda *a,**kw:None)
        self.client=TestClient(self.app);self.addCleanup(self.client.close)
        self.client.headers['X-BUAA-CSRF']=self.client.get('/api/session').json()['csrf']
        self.addCleanup(self.close_store)
    def close_store(self):
        engine=self.app.state.td_holder['engine']
        if engine:engine.close()
    def test_management_and_csrf_required_for_private_media(self):
        client=TestClient(self.app);self.addCleanup(client.close)
        self.assertEqual(client.get('/api/td/status?username=90101').status_code,401)
        client.get('/api/session')
        self.assertEqual(client.post('/api/td/toggle?username=90101',json={'enabled':True}).status_code,403)
    def test_batch_strict_confirmation_identity_and_csrf(self):
        for body in ({},{'confirmed':1},{'confirmed':True,'phase':'entry'},{'confirmed':True,'username':'90102'}):
            self.assertEqual(self.client.post('/api/td/batch?username=90101',json=body).status_code,422)
        self.assertEqual(self.client.post('/api/td/batch',json={'confirmed':True}).status_code,422)
        other=TestClient(self.app);self.addCleanup(other.close);other.get('/api/session')
        self.assertEqual(other.post('/api/td/batch?username=90101',json={'confirmed':True}).status_code,403)
        with patch.object(TDClient,'request',side_effect=AssertionError('No real campus traffic')):
            self.assertEqual(self.client.post('/api/td/batch?username=90101',json={'confirmed':True}).status_code,409)
            self.assertEqual(self.client.get('/api/td/status?username=90101').json()['today']['attempted'],0)
    def test_status_route_does_not_wait_for_the_network_operation_lock(self):
        self.client.get('/api/td/status?username=90101')
        engine=self.app.state.td_holder['engine'];entered=threading.Event();release=threading.Event()
        def hold():
            with engine.account_lock('90101'):
                entered.set();release.wait(3)
        with ThreadPoolExecutor(max_workers=2) as pool:
            blocker=pool.submit(hold);self.assertTrue(entered.wait(1))
            try:self.assertEqual(pool.submit(self.client.get,'/api/td/status?username=90101').result(timeout=1).status_code,200)
            finally:release.set()
            blocker.result(timeout=2)
    def test_batch_api_returns_before_waits_and_background_uses_same_queue(self):
        self.client.get('/api/td/status?username=90101')
        engine=self.app.state.td_holder['engine'];engine.licensing.close();engine.licensing=FakeLicense()
        engine.clock=lambda:datetime(2026,10,19,8,0,tzinfo=TZ)
        engine.client=FakeClient()
        engine.configure('90101',dict(campus='学院路',semester_start='2026-09-01',semester_end='2027-01-31',start='2026-10-01',end='2026-12-31',target=32,daily_limit=3,confirmed=True,weekdays=list(range(7)),closed_dates=[]))
        images=[engine.store.add_image('90101',jpeg(color))['id'] for color in ('navy','teal')]
        engine.store.create_group('90101',*images,'Synthetic lifecycle pair',True)
        with TestClient(self.app) as client:
            client.headers['X-BUAA-CSRF']=client.get('/api/session').json()['csrf']
            started=time.monotonic();response=client.post('/api/td/batch?username=90101',json={'confirmed':True})
            self.assertEqual(response.status_code,200);self.assertTrue(response.json()['queued'])
            self.assertLess(time.monotonic()-started,2,'Queue start must not wait through a 3–4 minute phase')
            deadline=time.monotonic()+7
            while time.monotonic()<deadline:
                state=client.get('/api/td/status?username=90101').json()
                if state['task']['state']=='waiting_exit':break
                time.sleep(.05)
            self.assertEqual(state['task']['state'],'waiting_exit');self.assertEqual(state['today']['attempted'],1)
            self.assertEqual(client.post('/api/td/batch?username=90101',json={'confirmed':True}).status_code,409)
            self.assertEqual(client.post('/api/td/toggle?username=90101',json={'enabled':False}).status_code,200)
            self.assertEqual(len(engine.client.calls),2)
    def test_offline_license_request_scope_strict_payload_and_default_deny(self):
        user='?username=90101'
        first=self.client.post('/api/td/license/request'+user,json={})
        self.assertEqual(first.status_code,200);self.assertTrue(first.json()['request'].startswith('TDR1.'))
        self.assertEqual(first.json(),self.client.post('/api/td/license/request'+user,json={}).json())
        other=self.client.post('/api/td/license/request?username=90102',json={}).json();self.assertNotEqual(first.json(),other)
        self.assertEqual(self.client.post('/api/td/license/request'+user,json={'username':'90102'}).status_code,422)
        self.assertEqual(self.client.post('/api/td/license/activate'+user,json={'code':1}).status_code,422)
        self.assertEqual(self.client.post('/api/td/license/activate'+user,json={'code':'TDL1.'+'invalid'*20}).status_code,409)
        state=self.client.get('/api/td/status'+user).json();self.assertFalse(state['license']['active']);self.assertFalse(state['manual']['allowed'])
        self.assertEqual(self.client.post('/api/td/toggle'+user,json={'enabled':True}).status_code,409)
        self.assertEqual(self.client.post('/api/td/manual'+user,json={'phase':'entry','confirmed':True}).status_code,409)
    def test_unknown_or_missing_explicit_account_no_fallback(self):
        self.assertEqual(self.client.get('/api/td/status?username=missing').status_code,404)
        self.assertEqual(self.client.get('/api/td/status').status_code,422)
    def test_license_entrance_is_scoped_local_read_without_gallery_or_school(self):
        self.client.get('/api/td/status?username=90101')
        engine=self.app.state.td_holder['engine']
        with patch.object(engine,'status',side_effect=AssertionError('no full TD state')),patch.object(TDClient,'request',side_effect=AssertionError('no school writes')):
            result=self.client.get('/api/td/license/status?username=90101')
            self.assertEqual(result.status_code,200);self.assertEqual(set(result.json()),{'license'});self.assertFalse(result.json()['license']['active'])
        self.assertEqual(self.client.get('/api/td/license/status').status_code,422)
        self.assertEqual(self.client.get('/api/td/license/status?username=missing').status_code,404)
        unauth=TestClient(self.app);self.addCleanup(unauth.close)
        self.assertEqual(unauth.get('/api/td/license/status?username=90101').status_code,401)
    def test_raw_upload_and_cross_account_media_isolation(self):
        response=self.client.post('/api/td/images?username=90101',content=jpeg(),headers={'Content-Type':'image/jpeg'})
        self.assertEqual(response.status_code,200)
        image=response.json()['id']
        self.assertEqual(self.client.get(f'/api/td/images/{image}?username=90102').status_code,409)
        result=self.client.get(f'/api/td/images/{image}?username=90101')
        self.assertEqual(result.headers['content-type'],'image/jpeg');self.assertEqual(result.headers['cache-control'],'no-store')
    def test_active_content_and_oversized_upload_rejected(self):
        self.assertEqual(self.client.post('/api/td/images?username=90101',content=b'<html>',headers={'Content-Type':'text/html'}).status_code,415)
        self.assertEqual(self.client.post('/api/td/images?username=90101',content=b'x'*(8*1024*1024+1),headers={'Content-Type':'image/jpeg'}).status_code,413)
    def test_strict_boolean_limit_and_unknown_fields(self):
        for body in [{'enabled':'true'},{'enabled':1},{'enabled':False,'username':'90102'}]:
            self.assertEqual(self.client.post('/api/td/toggle?username=90101',json=body).status_code,422)
    def group_upload(self, entry, exit_image, **overrides):
        meta={'entry_size':len(entry),'exit_size':len(exit_image),'name':'Synthetic pair','confirmed':True}
        meta.update(overrides)
        encoded=json.dumps(meta).encode()
        return self.client.post('/api/td/groups?username=90101',content=struct.pack('>I',len(encoded))+encoded+entry+exit_image,headers={'Content-Type':'application/octet-stream'})
    def test_pair_upload_is_single_group_and_roles_owned(self):
        result=self.group_upload(jpeg(),jpeg())
        self.assertEqual(result.status_code,200)
        state=self.client.get('/api/td/status?username=90101').json()
        self.assertEqual(len(state['groups']),1)
        group=state['groups'][0]
        self.assertEqual(group['entry_image'],group['exit_image'])
        self.assertEqual(self.client.get('/api/td/status?username=90102').json()['groups'],[])
    def test_pair_invalid_exit_and_confirmation_leave_no_partial_media(self):
        for entry,exit_image,extra in [(jpeg(),b'broken',{}),(jpeg(),jpeg(),{'confirmed':False})]:
            self.assertNotEqual(self.group_upload(entry,exit_image,**extra).status_code,200)
            state=self.client.get('/api/td/status?username=90101').json()
            self.assertEqual(state['images'],[]);self.assertEqual(state['groups'],[])
    def test_pair_binary_frame_length_and_strict_metadata(self):
        for content in [b'xx',struct.pack('>I',2049),struct.pack('>I',2)+b'{}']:
            self.assertEqual(self.client.post('/api/td/groups?username=90101',content=content,headers={'Content-Type':'application/octet-stream'}).status_code,422)
        self.assertEqual(self.group_upload(jpeg(),jpeg(),entry_size=True).status_code,422)
        self.assertEqual(self.group_upload(jpeg(),jpeg(),exit_size=1).status_code,422)
    def test_empty_state_read_is_not_school_write(self):
        with patch.object(TDClient,'request',side_effect=AssertionError('no network')):
            state=self.client.get('/api/td/status?username=90101').json()
            self.assertIsNone(state['progress']['count']);self.assertFalse(state['settings']['enabled'])
    def test_remove_turns_off_persisted_td(self):
        self.client.get('/api/td/status?username=90101')
        engine=self.app.state.td_holder['engine']
        with engine.store.transaction():
            p=engine.store.profile(owner_key('90101'));p['enabled']=True;engine.store.save_profile(owner_key('90101'),p)
        self.accounts['90101'].removed=True;asyncio.run(self.remove('90101'))
        self.assertFalse(engine.store.profile(owner_key('90101'))['enabled'])
    def test_corrupt_td_storage_does_not_prevent_application_start(self):
        private=Path(self.temp.name)/'config.td-private';private.mkdir();(private/'state.sqlite').write_bytes(b'synthetic-invalid-sqlite')
        with TestClient(self.app) as client:
            self.assertEqual(client.get('/api/health').status_code,200)
        self.assertEqual((private/'state.sqlite').read_bytes(),b'synthetic-invalid-sqlite')
    def test_corrupt_license_storage_is_preserved_and_reports_unavailable(self):
        private=Path(self.temp.name)/'config.td-private';private.mkdir();path=private/'authorization.sqlite';path.write_bytes(b'broken-license-fixture')
        for _ in range(2):self.assertEqual(self.client.get('/api/td/status?username=90101').status_code,503)
        self.assertEqual(path.read_bytes(),b'broken-license-fixture')
    def test_corrupt_td_storage_returns_unavailable_without_reset(self):
        private=Path(self.temp.name)/'config.td-private';private.mkdir();(private/'state.sqlite').write_bytes(b'synthetic-invalid-sqlite')
        self.assertEqual(self.client.get('/api/td/status?username=90101').status_code,503)
        self.assertEqual((private/'state.sqlite').read_bytes(),b'synthetic-invalid-sqlite')


    def test_manual_strict_payload_csrf_and_explicit_account(self):
        for body in [{'phase':'entry','confirmed':1},{'phase':'both','confirmed':True},{'phase':'exit','confirmed':True,'username':'90102'}]:
            self.assertEqual(self.client.post('/api/td/manual?username=90101',json=body).status_code,422)
        self.assertEqual(self.client.post('/api/td/manual',json={'phase':'entry','confirmed':True}).status_code,422)
        client=TestClient(self.app);self.addCleanup(client.close);client.get('/api/session')
        self.assertEqual(client.post('/api/td/manual?username=90101',json={'phase':'entry','confirmed':True}).status_code,403)
        with patch.object(TDClient,'request',side_effect=AssertionError('no school write')):
            self.assertEqual(self.client.post('/api/td/manual?username=90101',json={'phase':'entry','confirmed':True}).status_code,409)
            self.assertEqual(self.client.get('/api/td/status?username=90101').json()['today']['attempted'],0)
