"""First-use acceptance must not survive a failed local configuration write."""
import os
import unittest
import json
import pathlib
import tempfile
from unittest.mock import patch

if os.environ.get("TESTING") != "1" or not os.environ.get("BUAA_CONFIG_FILE"):
    raise RuntimeError("Use scripts/test_isolated.py; never open personal configuration")

from fastapi.testclient import TestClient
from server import app as backend


class FirstLoginAcceptance(unittest.TestCase):
    def setUp(self):
        self.previous = dict(backend.config)
        backend.config["disclaimer_accepted"] = False
        backend.config.pop("disclaimer_commitment_version", None)
        backend.config.pop("disclaimer_accepted_at", None)
        self.client = TestClient(backend.app)
        self.client.headers["X-BUAA-CSRF"] = self.client.get("/api/session").json()["csrf"]
        self.payload = dict(agreed=True, commitment=backend.COMMITMENT_TEXT, commitment_version=backend.COMMITMENT_VERSION)

    def tearDown(self):
        self.client.close()
        backend.config.clear()
        backend.config.update(self.previous)

    def test_failed_acceptance_remains_unaccepted(self):
        with patch.object(backend, "save_config", side_effect=OSError("synthetic write failure")):
            response = self.client.post("/api/system/disclaimer/accept", json=self.payload)
        self.assertEqual(response.status_code, 500)
        self.assertFalse(self.client.get("/api/system/disclaimer").json()["accepted"])

    def test_failed_acceptance_can_be_retried(self):
        with patch.object(backend, "save_config", side_effect=OSError("synthetic write failure")):
            self.client.post("/api/system/disclaimer/accept", json=self.payload)
        with patch.object(backend, "save_config", return_value=None) as save:
            response = self.client.post("/api/system/disclaimer/accept", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["accepted"])
        self.assertTrue(self.client.get("/api/system/disclaimer").json()["accepted"])
        save.assert_called_once_with(backend.config)

    def test_repeat_is_idempotent_and_does_not_rewrite_confirmation_time(self):
        with patch.object(backend, "save_config", return_value=None) as save:
            self.client.post("/api/system/disclaimer/accept", json=self.payload)
            stamp=backend.config['disclaimer_accepted_at']
            self.assertEqual(self.client.post("/api/system/disclaimer/accept", json=self.payload).status_code,200)
            self.assertEqual(backend.config['disclaimer_accepted_at'],stamp)
            self.assertEqual(save.call_count,1)
        self.assertTrue(self.client.get("/api/system/disclaimer").json()["accepted"])

    def test_legacy_checkbox_alone_requires_one_time_pledge(self):
        backend.config['disclaimer_accepted']=True
        self.assertFalse(self.client.get('/api/system/disclaimer').json()['accepted'])
        self.assertTrue(self.client.post('/api/system/disclaimer/accept',json=self.payload).json()['accepted'])
        self.assertTrue(self.client.get('/api/system/disclaimer').json()['accepted'])

    def test_missing_wrong_unchecked_and_extra_payload_never_save(self):
        invalid=[{},dict(self.payload,agreed=False),dict(self.payload,agreed='true'),dict(self.payload,agreed=1),
                 dict(self.payload,commitment='本人承诺'),dict(self.payload,commitment=''),
                 dict(self.payload,commitment=backend.COMMITMENT_TEXT.replace('24','48')),
                 dict(self.payload,commitment=backend.COMMITMENT_TEXT+'。'),
                 dict(self.payload,commitment='x'*1025),dict(self.payload,signature='Synthetic')]
        with patch.object(backend,'save_config') as save:
            self.assertEqual(self.client.post('/api/system/disclaimer/accept').status_code,422)
            for value in invalid:
                with self.subTest(value=value):
                    self.assertEqual(self.client.post('/api/system/disclaimer/accept',json=value).status_code,422)
            save.assert_not_called()
        self.assertFalse(self.client.get('/api/system/disclaimer').json()['accepted'])

    def test_stale_version_preserves_configuration(self):
        before=dict(backend.config)
        with patch.object(backend,'save_config') as save:
            self.assertEqual(self.client.post('/api/system/disclaimer/accept',json=dict(self.payload,commitment_version='old')).status_code,409)
            save.assert_not_called()
        self.assertEqual(backend.config,before)

    def test_spacing_and_line_breaks_allowed_without_storing_full_input(self):
        value=' \n'+backend.COMMITMENT_TEXT.replace('；','；\n\u3000')+'\t'
        with patch.object(backend,'save_config') as save:
            self.assertEqual(self.client.post('/api/system/disclaimer/accept',json=dict(self.payload,commitment=value)).status_code,200)
        stored=save.call_args.args[0]
        self.assertEqual(stored['disclaimer_commitment_version'],backend.COMMITMENT_VERSION)
        self.assertIn('disclaimer_accepted_at',stored)
        self.assertNotIn('commitment',stored)
        self.assertNotIn(backend.COMMITMENT_TEXT,str(stored))

    def test_agreement_endpoint_retains_management_csrf_boundary(self):
        with patch.object(backend,'save_config') as save:
            self.assertEqual(self.client.post('/api/system/disclaimer/accept',json=self.payload,headers={'X-BUAA-CSRF':'wrong'}).status_code,403)
            save.assert_not_called()

    def test_actual_local_file_persists_only_confirmation_metadata(self):
        with tempfile.TemporaryDirectory(prefix='pledge-persistence-') as directory:
            target=pathlib.Path(directory)/'config.json'
            with patch.object(backend,'CONFIG_FILE',target),patch.dict(os.environ,{'TESTING':'0'}):
                self.assertEqual(self.client.post('/api/system/disclaimer/accept',json=self.payload).status_code,200)
            stored=json.loads(target.read_text(encoding='utf-8'))
            self.assertTrue(stored['disclaimer_accepted'])
            self.assertEqual(stored['disclaimer_commitment_version'],backend.COMMITMENT_VERSION)
            self.assertIn('disclaimer_accepted_at',stored)
            self.assertNotIn(backend.COMMITMENT_TEXT,target.read_text(encoding='utf-8'))
