"""A failed foreground save must not silently change subsequent API ownership."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from fastapi import HTTPException
import server.app as backend

class ForegroundTransaction(unittest.IsolatedAsyncioTestCase):
 async def test_failed_switch_save_restores_original_student_and_does_not_start_auth(self):
  accounts={u:backend.AccountState(u,password='synthetic-only') for u in ['A','B']}
  with patch.object(backend,'accounts',accounts),patch.object(backend,'active_username','A'),patch.object(backend,'sync_config',side_effect=OSError('synthetic disk full')),patch.object(backend,'connect_single_account') as connect:
   with self.assertRaises(HTTPException) as caught:await backend.switch_account(SimpleNamespace(username='B'))
   self.assertEqual(caught.exception.status_code,503);self.assertEqual(backend.active_username,'A');connect.assert_not_called()
   self.assertIs(backend.get_active_account(),accounts['A'])
