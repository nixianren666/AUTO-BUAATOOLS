"""Real private-vault persistence and cancelled write ordering."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from core.wechat import WechatNotifications
from tests import test_wechat_notifications as fixtures


class PrivateStorageContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'.wechat-private'
        self.env=patch.dict(os.environ,BUAA_VAULT_DIR=self.directory.name,PYTHON_KEYRING_BACKEND='keyring.backends.fail.Keyring')
        self.env.start()
        self.engine=WechatNotifications(self.path,lambda user:False,fixtures.FakeProtocol())
        self.binding=fixtures.NotificationContracts.binding(None,'A')

    async def asyncTearDown(self):
        await self.engine.stop();self.env.stop();self.directory.cleanup()

    async def test_real_vault_roundtrip_contains_no_plain_token_or_context(self):
        await self.engine.save({'A':self.binding})
        raw=self.path.read_text()
        self.assertTrue(raw.startswith('enc:'))
        self.assertNotIn('token-A',raw);self.assertNotIn('context-A',raw)
        self.assertEqual(self.engine._read(),{'A':self.binding})

    async def test_malformed_encrypted_binding_fails_closed_without_worker(self):
        from core import vault
        for mutation in ({'base':'https://evil.example'},{'enabled':'true'},{'generation':'wrong'},{'paused_until':float('nan')}):
            self.path.write_text(vault.encrypt(json.dumps({'version':1,'bindings':{'A':dict(self.binding,**mutation)}})))
            await self.engine.start()
            self.assertTrue(self.engine.storage_error);self.assertEqual(self.engine.bindings,{})
            self.assertFalse(self.engine.tasks);await self.engine.stop()

    async def test_cancelled_save_finishes_file_write_before_releasing_caller(self):
        started=threading.Event();release=threading.Event();finished=threading.Event();write=self.engine._write
        def blocked(bindings):
            started.set();release.wait(timeout=3);write(bindings);finished.set()
        with patch.object(self.engine,'_write',side_effect=blocked):
            save=asyncio.create_task(self.engine.save({'A':self.binding}))
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            save.cancel();await asyncio.sleep(.05);self.assertFalse(save.done())
            release.set()
            with self.assertRaises(asyncio.CancelledError):await save
        self.assertTrue(finished.is_set());self.assertEqual(self.engine._read(),{'A':self.binding})
        self.assertEqual(self.engine.bindings,{'A':self.binding})
        self.assertFalse(self.engine.storage_error)

    async def test_cancelled_failed_write_keeps_memory_and_exposes_storage_failure(self):
        started=threading.Event();release=threading.Event()
        original={'A':self.binding};self.engine.bindings=original
        def failed(bindings):
            started.set();release.wait(timeout=3);raise OSError('synthetic disk full')
        with patch.object(self.engine,'_write',side_effect=failed):
            save=asyncio.create_task(self.engine.save({}))
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            save.cancel();release.set()
            with self.assertRaises(asyncio.CancelledError):await save
        self.assertIs(self.engine.bindings,original)
        self.assertTrue(self.engine.storage_error)

    async def test_failed_unbind_stops_in_memory_and_reports_unpersisted_state(self):
        await self.engine.save({'A':self.binding})
        with patch.object(self.engine,'_write',side_effect=OSError('synthetic disk full')):
            with self.assertRaises(ValueError):await self.engine.remove('A')
        self.assertFalse(self.engine.status('A')['bound']);self.assertTrue(self.engine.storage_error)
        with self.assertRaises(ValueError):await self.engine.test('A')


if __name__=='__main__':unittest.main()
