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
            with patch("core.autostart.get_linux_service_path") as mock_path, \
                 patch("core.autostart._run_systemctl") as mock_systemctl, \
                 patch("subprocess.run") as mock_subproc:
                mock_file = MagicMock()
                mock_file.exists.return_value = True
                mock_file.stat.return_value.st_size = 200
                mock_path.return_value = mock_file

                # 1. 模拟 systemctl --user is-enabled 正常返回 enabled
                mock_subproc.return_value = MagicMock(returncode=0, stdout="enabled\n")
                status = get_autostart_status()
                self.assertTrue(status)

                # 2. 启用自启动并验证 systemctl daemon-reload 与 enable 闭环调用
                res = set_autostart(True)
                self.assertTrue(res)
                mock_file.write_text.assert_called_once()
                mock_systemctl.assert_any_call(["daemon-reload"])
                mock_systemctl.assert_any_call(["enable", "buaa-signin.service"])

                # 3. 禁用自启动并验证 systemctl disable 与 daemon-reload 闭环调用
                res = set_autostart(False)
                self.assertTrue(res)
                mock_file.unlink.assert_called_once()
                mock_systemctl.assert_any_call(["disable", "buaa-signin.service"])

if __name__ == "__main__":
    unittest.main()
