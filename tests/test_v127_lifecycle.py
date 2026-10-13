"""Independent process/session lifecycle regressions; synthetic profiles only."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from server import app as backend
from core import operations
import run

class InstanceContracts(unittest.TestCase):
    def test_same_profile_different_ports_cannot_start_second_process(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory)/"config.json"
            profile.write_text("{}")
            with patch.dict(os.environ, {"BUAA_CONFIG_FILE":str(profile)}):
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1",0)); first_port=probe.getsockname()[1]
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1",0)); second_port=probe.getsockname()[1]
                self.assertTrue(run.acquire_single_instance(first_port))
                try:
                    child = subprocess.run([sys.executable,"-c", "import run; print(run.acquire_single_instance("+str(second_port)+"))"], capture_output=True,text=True,timeout=15)
                    self.assertEqual(child.returncode,0,child.stderr)
                    self.assertEqual(child.stdout.strip(),"False")
                finally:
                    run.release_single_instance()
                self.assertTrue(run.acquire_single_instance(second_port))
                run.release_single_instance()

    def test_foreign_listener_is_not_an_existing_buaa_instance(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as directory:
            listener.bind(("127.0.0.1",0)); listener.listen()
            with patch.dict(os.environ,{"BUAA_CONFIG_FILE":str(Path(directory)/"config.json")}):
                with self.assertRaises(RuntimeError):
                    run.acquire_single_instance(listener.getsockname()[1])
                self.assertIsNone(run._single_instance_mutex)

    def test_invalid_port_fails_before_lock(self):
        for value in (-1,0,65536,True):
            with self.assertRaises(ValueError):
                run.acquire_single_instance(value)

class AuthenticationContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.account = backend.AccountState("fixture-lifecycle",password="fixture-password",remember=False)

    async def asyncTearDown(self):
        self.account.boya_client.close()
        await self.account.client.close()

    async def test_concurrent_refreshes_share_one_attempt_and_stop_writes(self):
        attempts=[]
        async def connect(account):
            attempts.append(1)
            self.assertFalse(account.client.request_guard())
            self.assertFalse(account.boya_client.request_guard())
            await asyncio.sleep(0.03)
            return True
        with patch.object(backend,"_connect_single_account",connect):
            results = await asyncio.gather(*(backend.connect_single_account(self.account) for _ in range(8)))
        self.assertEqual(len(attempts),1)
        self.assertEqual(sum(results),1)
        self.assertFalse(self.account.maintenance)
        self.assertEqual(self.account.auth_epoch,1)

    async def test_captcha_pause_does_not_retry_on_every_poll(self):
        self.account.auth_requires_input=True
        with patch.object(backend,"_connect_single_account") as connect:
            self.assertFalse(await backend.connect_single_account(self.account))
            connect.assert_not_called()

    async def test_exception_releases_maintenance_and_leaves_cooldown(self):
        async def failure(account):
            raise TimeoutError("synthetic")
        with patch.object(backend,"_connect_single_account",failure):
            with self.assertRaises(TimeoutError):
                await backend.connect_single_account(self.account)
        self.assertFalse(self.account.maintenance)
        self.assertFalse(await backend.connect_single_account(self.account))

class ConfigContracts(unittest.TestCase):
    def test_one_undecipherable_secret_does_not_discard_all_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            profile=Path(directory)/"config.json"
            raw={"accounts":[{"username":"fixture-one","password":"enc:v2:broken","auto_checkin":True},{"username":"fixture-two","password":"","remember":False}]}
            profile.write_text(json.dumps(raw))
            with patch.object(backend,"CONFIG_FILE",profile),patch.object(backend,"config_read_error",False):
                result=backend.load_config()
            self.assertEqual(len(result["accounts"]),2)
            self.assertEqual(result["accounts"][0]["password"],"")
            self.assertEqual(result["accounts"][0]["_protected_password"],"enc:v2:broken")
            self.assertFalse(result["accounts"][0]["auto_checkin"])
            self.assertEqual(json.loads(profile.read_text()),raw)

    def test_invalid_config_cannot_be_overwritten_by_empty_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            profile=Path(directory)/"config.json";profile.write_text("broken synthetic config")
            with patch.object(backend,"CONFIG_FILE",profile),patch.object(backend,"config_read_error",False):
                backend.load_config()
                with patch.dict(os.environ,{"TESTING":"0"}):
                    with self.assertRaises(RuntimeError):
                        backend.save_config({"accounts":[]})
            self.assertEqual(profile.read_text(),"broken synthetic config")
