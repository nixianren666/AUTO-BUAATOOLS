import unittest
from unittest.mock import patch, MagicMock
import sys
from core.autostart import get_autostart_status, set_autostart, get_executable_command

class TestAutostart(unittest.TestCase):
    def test_get_executable_command(self):
        cmd = get_executable_command()
        self.assertIn("--autostart", cmd)

    def test_macos_autostart_mock(self):
        with patch("sys.platform", "darwin"):
            with patch("core.autostart.get_mac_plist_path") as mock_path:
                mock_file = MagicMock()
                mock_file.exists.return_value = True
                mock_file.stat.return_value.st_size = 120
                mock_path.return_value = mock_file

                status = get_autostart_status()
                self.assertTrue(status)

                res = set_autostart(True)
                self.assertTrue(res)
                mock_file.write_text.assert_called_once()

                res = set_autostart(False)
                self.assertTrue(res)
                mock_file.unlink.assert_called_once()

    def test_linux_autostart_mock(self):
        with patch("sys.platform", "linux"):
            with patch("core.autostart.get_linux_service_path") as mock_path:
                mock_file = MagicMock()
                mock_file.exists.return_value = True
                mock_file.stat.return_value.st_size = 200
                mock_path.return_value = mock_file

                status = get_autostart_status()
                self.assertTrue(status)

                res = set_autostart(True)
                self.assertTrue(res)
                mock_file.write_text.assert_called_once()

                res = set_autostart(False)
                self.assertTrue(res)
                mock_file.unlink.assert_called_once()

if __name__ == "__main__":
    unittest.main()
