"""Synthetic signing keys, clocks and local databases; no production private key."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from core.td_license import TDLicense,canonical,month_after,validate_request,verify_code,TZ


class LicenseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.private=Ed25519PrivateKey.generate();pub=self.private.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw).hex()
        self.keys={'test-key':pub};self.now=datetime(2026,1,31,8,12,tzinfo=TZ).timestamp()
        self.aes=AESGCM(AESGCM.generate_key(bit_length=256));self.path=Path(self.temp.name)/'auth.sqlite'
        def seal(s):
            nonce=secrets.token_bytes(12);return base64.b64encode(nonce+self.aes.encrypt(nonce,s.encode(),b'test')).decode()
        def open_(s):
            raw=base64.b64decode(s);return self.aes.decrypt(raw[:12],raw[12:],b'test').decode()
        self.kwargs={'clock':lambda:self.now,'anchor':lambda:'synthetic-machine','keys':self.keys,'protect':seal,'unprotect':open_}
        self.auth=TDLicense(self.path,**self.kwargs);self.addCleanup(lambda:self.auth.close())

    def code(self,request,**overrides):
        p={**validate_request(request,self.keys),'id':secrets.token_hex(16),'issued':int(self.now),'months':1,**overrides};raw=canonical(p)
        return 'TDL1.'+base64.urlsafe_b64encode(raw).decode().rstrip('=')+'.'+base64.urlsafe_b64encode(self.private.sign(b'TD-LICENSE/v1\0'+raw)).decode().rstrip('=')

    def test_first_activation_natural_month_and_consumed_code(self):
        self.assertFalse(self.auth.status('90101')['active']);req=self.auth.request('90101');self.assertEqual(req,self.auth.request('90101'))
        code=self.code(req);state=self.auth.activate('90101',code)
        self.assertTrue(state['active']);self.assertEqual(state['expires_epoch'],datetime(2026,2,28,8,12,tzinfo=TZ).timestamp())
        self.now+=500
        with self.assertRaisesRegex(ValueError,'核销'):self.auth.activate('90101',code)
        self.assertEqual(self.auth.status('90101')['expires_epoch'],state['expires_epoch'])
        with self.assertRaises(ValueError):self.auth.request('90101')

    def test_expiry_renewal_has_new_nonce_and_never_reuses_old_code(self):
        req=self.auth.request('90101');code=self.code(req);end=self.auth.activate('90101',code)['expires_epoch'];self.now=end
        self.assertFalse(self.auth.status('90101')['active']);req2=self.auth.request('90101');self.assertNotEqual(req,req2)
        with self.assertRaises(ValueError):self.auth.activate('90101',code)
        self.assertTrue(self.auth.activate('90101',self.code(req2))['active'])

    def test_renewal_window_exact_boundary_and_remaining_time_preserved(self):
        old=self.code(self.auth.request('90101'));end=self.auth.activate('90101',old)['expires_epoch']
        self.now=end-86401;self.assertFalse(self.auth.status('90101')['renewable'])
        with self.assertRaisesRegex(ValueError,'24小时'):self.auth.request('90101')
        self.now=end-86400;self.assertTrue(self.auth.status('90101')['active']);self.assertTrue(self.auth.status('90101')['renewable'])
        request=self.auth.request('90101');new=self.code(request);result=self.auth.activate('90101',new)
        self.assertTrue(result['active']);self.assertEqual(result['expires_epoch'],month_after(end))
        self.assertFalse(result['renewable'])
        for code in [old,new]:
            with self.assertRaisesRegex(ValueError,'核销'):self.auth.activate('90101',code)
        with self.assertRaisesRegex(ValueError,'24小时'):self.auth.request('90101')

    def test_renewal_activation_before_window_is_denied_even_with_pending_request(self):
        end=self.auth.activate('90101',self.code(self.auth.request('90101')))['expires_epoch']
        self.now=end-86400;code=self.code(self.auth.request('90101'));self.now-=1
        with self.assertRaisesRegex(ValueError,'24小时'):self.auth.activate('90101',code)
        self.assertEqual(self.auth.status('90101')['expires_epoch'],end)
        self.now+=1;self.assertTrue(self.auth.activate('90101',code)['active'])

    def test_late_renewal_starts_at_actual_activation_not_past_expiry(self):
        end=self.auth.activate('90101',self.code(self.auth.request('90101')))['expires_epoch'];self.now=end+172800
        result=self.auth.activate('90101',self.code(self.auth.request('90101')))
        self.assertEqual(result['expires_epoch'],month_after(self.now))

    def test_each_account_requires_its_own_code_and_keeps_independent_term(self):
        first=self.code(self.auth.request('90101'));end=self.auth.activate('90101',first)['expires_epoch']
        self.assertFalse(self.auth.status('90102')['active'])
        with self.assertRaises(ValueError):self.auth.activate('90102',first)
        second=self.code(self.auth.request('90102'));self.assertTrue(self.auth.activate('90102',second)['active'])
        self.assertEqual(self.auth.status('90101')['expires_epoch'],end)

    def test_renewal_survives_restart_and_old_codes_remain_consumed(self):
        first=self.code(self.auth.request('90101'));end=self.auth.activate('90101',first)['expires_epoch'];self.now=end-3600
        second=self.code(self.auth.request('90101'));new_end=self.auth.activate('90101',second)['expires_epoch']
        self.auth.close();self.auth=TDLicense(self.path,**self.kwargs)
        self.assertTrue(self.auth.status('90101')['active']);self.assertEqual(self.auth.status('90101')['expires_epoch'],new_end)
        for code in [first,second]:
            with self.assertRaisesRegex(ValueError,'核销'):self.auth.activate('90101',code)

    def test_existing_legacy_record_and_invalid_renewal_period(self):
        self.auth.activate('90101',self.code(self.auth.request('90101')))
        with self.auth.state() as (s,now):s['accounts'][self.auth.binding(s,'90101')].pop('period_start')
        self.assertTrue(self.auth.status('90101')['active'])
        with self.auth.state() as (s,now):s['accounts'][self.auth.binding(s,'90101')]['period_start']=now+86401
        self.assertFalse(self.auth.status('90101')['active'])
        with self.assertRaises(ValueError):self.auth.request('90101')

    def test_binding_and_wrong_challenge_preserve_pending_request(self):
        first=self.auth.request('90101');second=self.auth.request('90102');code=self.code(first)
        with self.assertRaises(ValueError):self.auth.activate('90102',code)
        with self.assertRaises(ValueError):self.auth.activate('90101',self.code(second))
        self.assertTrue(self.auth.activate('90101',code)['active']);self.assertFalse(self.auth.status('90102')['active'])

    def test_invalid_signature_product_months_and_payload_never_activate(self):
        request=self.auth.request('90101')
        for change in ({'months':2},{'months':True},{'product':'other'},{'kid':[]},{'extra':'field'},{'issued':False}):
            with self.assertRaises(ValueError):self.auth.activate('90101',self.code(request,**change))
        code=self.code(request);parts=code.split('.');raw=bytearray(base64.urlsafe_b64decode(parts[2]+'='*(-len(parts[2])%4)));raw[0]^=1;parts[2]=base64.urlsafe_b64encode(raw).decode().rstrip('=')
        with self.assertRaises(ValueError):self.auth.activate('90101','.'.join(parts))
        for bad in ['',None,{},'TDL1.'+'x'*5000,'TDL1.@@@@.aa','TDL1.e30.aa']:
            with self.assertRaises(ValueError):verify_code(bad,self.keys)
        self.assertFalse(self.auth.status('90101')['active'])

    def test_restart_preserves_first_activation_and_expiry(self):
        original=self.auth.activate('90101',self.code(self.auth.request('90101')));self.auth.close()
        self.auth=TDLicense(self.path,**self.kwargs);self.now+=60
        self.assertEqual(self.auth.status('90101')['expires_epoch'],original['expires_epoch'])

    def test_clock_rollback_and_forward_expiry_fail_closed_without_reset(self):
        code=self.code(self.auth.request('90101'));state=self.auth.activate('90101',code);original=self.now;self.now-=301
        self.assertFalse(self.auth.status('90101')['active'])
        with self.assertRaises(ValueError):self.auth.request('90102')
        self.now=original;self.assertTrue(self.auth.status('90101')['active']);self.now=state['expires_epoch'];self.assertFalse(self.auth.status('90101')['active'])

    def test_copied_machine_or_corrupt_database_cannot_authorize(self):
        self.auth.activate('90101',self.code(self.auth.request('90101')))
        other=TDLicense(self.path,**{**self.kwargs,'anchor':lambda:'other-machine'});self.addCleanup(other.close)
        self.assertFalse(other.status('90101')['active'])
        with self.assertRaises(ValueError):other.request('90101')
        self.auth.db.execute("UPDATE authorization SET data='corrupted'");self.auth.db.commit()
        self.assertFalse(self.auth.status('90101')['active'])
        with self.assertRaises(ValueError):self.auth.request('90101')
        self.assertEqual(self.auth.db.execute('SELECT data FROM authorization').fetchone()[0],'corrupted')

    def test_concurrent_activation_consumes_code_once(self):
        code=self.code(self.auth.request('90101'))
        def activate(_):
            try:return self.auth.activate('90101',code)['active']
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(activate,range(8)))
        self.assertEqual(sum(results),1)

    def test_natural_month_leap_year_and_year_boundary(self):
        for a,b in [('2028-01-31T12:00:00+08:00','2028-02-29T12:00:00+08:00'),('2026-12-31T12:00:00+08:00','2027-01-31T12:00:00+08:00')]:
            self.assertEqual(month_after(datetime.fromisoformat(a).timestamp()),datetime.fromisoformat(b).timestamp())
    def test_stopped_wall_clock_is_detected_using_monotonic_time(self):
        elapsed=[0];self.auth.close();self.auth=TDLicense(self.path,**self.kwargs,monotonic=lambda:elapsed[0])
        self.auth.activate('90101',self.code(self.auth.request('90101')));elapsed[0]=301
        self.assertFalse(self.auth.status('90101')['active']);self.now+=301;self.assertTrue(self.auth.status('90101')['active'])

    def test_request_exports_no_plain_student_or_device_identifier(self):
        request=self.auth.request('90101');p=validate_request(request,self.keys)
        self.assertEqual(set(p),{'v','product','kid','binding','nonce'});self.assertNotIn('90101',json.dumps(p));self.assertNotIn('synthetic-machine',json.dumps(p))
        with self.assertRaises(ValueError):self.auth.request('fixture-account-1')
