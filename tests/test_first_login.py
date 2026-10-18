"""First-use acceptance must not survive a failed local configuration write."""
import os
import unittest
from unittest.mock import patch

if os.environ.get("TESTING") != "1" or not os.environ.get("BUAA_CONFIG_FILE"):
    raise RuntimeError("Use scripts/test_isolated.py; never open personal configuration")

from fastapi.testclient import TestClient
from server import app as backend


class FirstLoginAcceptance(unittest.TestCase):
    def setUp(self):
        self.previous = dict(backend.config)
        backend.config["disclaimer_accepted"] = False
        self.client = TestClient(backend.app)
        self.client.headers["X-BUAA-CSRF"] = self.client.get("/api/session").json()["csrf"]

    def tearDown(self):
        self.client.close()
        backend.config.clear()
        backend.config.update(self.previous)

    def test_failed_acceptance_remains_unaccepted(self):
        with patch.object(backend, "save_config", side_effect=OSError("synthetic write failure")):
            response = self.client.post("/api/system/disclaimer/accept")
        self.assertEqual(response.status_code, 500)
        self.assertFalse(self.client.get("/api/system/disclaimer").json()["accepted"])

    def test_failed_acceptance_can_be_retried(self):
        with patch.object(backend, "save_config", side_effect=OSError("synthetic write failure")):
            self.client.post("/api/system/disclaimer/accept")
        with patch.object(backend, "save_config", return_value=None) as save:
            response = self.client.post("/api/system/disclaimer/accept")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["accepted"])
        self.assertTrue(self.client.get("/api/system/disclaimer").json()["accepted"])
        save.assert_called_once_with(backend.config)

    def test_failed_repeat_does_not_revoke_existing_acceptance(self):
        backend.config["disclaimer_accepted"] = True
        with patch.object(backend, "save_config", side_effect=OSError("synthetic write failure")):
            self.assertEqual(self.client.post("/api/system/disclaimer/accept").status_code, 500)
        self.assertTrue(self.client.get("/api/system/disclaimer").json()["accepted"])
