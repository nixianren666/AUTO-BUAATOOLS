import unittest
from unittest.mock import patch, MagicMock
import sys
from core.autostart import get_autostart_status, set_autostart, get_executable_command

class TestAutostart(unittest.TestCase):
    def test_windows_fresh_profile_creates_run_key_and_preserves_other_apps(self):
        registry = MagicMock()
        state = {"exists": False, "values": {"OtherApp": "keep"}}
        def opened(*args):
            if not state["exists"]:
                raise FileNotFoundError()
            return MagicMock()
        def created(*args):
            state["exists"] = True
            return MagicMock()
        def queried(key, name):
            if name not in state["values"]:
                raise FileNotFoundError()
            return state["values"][name], registry.REG_SZ
        registry.OpenKey.side_effect = opened
        registry.CreateKeyEx.side_effect = created
        registry.QueryValueEx.side_effect = queried
        registry.SetValueEx.side_effect = lambda key, name, reserved, kind, value: state["values"].update({name: value})
        registry.DeleteValue.side_effect = lambda key, name: state["values"].pop(name)
        with patch("sys.platform", "win32"), patch.dict(sys.modules, {"winreg": registry}):
            self.assertTrue(set_autostart(False))
            registry.CreateKeyEx.assert_not_called()
            self.assertTrue(set_autostart(True))
            self.assertTrue(get_autostart_status())
            self.assertEqual(state["values"]["BUAA-Signin"], get_executable_command())
            self.assertTrue(set_autostart(False))
            self.assertFalse(get_autostart_status())
            self.assertEqual(state["values"], {"OtherApp": "keep"})

    def test_windows_registry_permission_failure_is_not_reported_as_success(self):
        registry = MagicMock()
        registry.CreateKeyEx.side_effect = PermissionError()
        registry.OpenKey.side_effect = PermissionError()
        with patch("sys.platform", "win32"), patch.dict(sys.modules, {"winreg": registry}):
            self.assertFalse(set_autostart(True))
            self.assertFalse(set_autostart(False))
        registry.SetValueEx.assert_not_called()
        registry.DeleteValue.assert_not_called()

    def test_windows_disable_missing_value_is_idempotent(self):
        registry = MagicMock()
        registry.DeleteValue.side_effect = FileNotFoundError()
        with patch("sys.platform", "win32"), patch.dict(sys.modules, {"winreg": registry}):
            self.assertTrue(set_autostart(False))
        registry.CreateKeyEx.assert_not_called()

    def test_get_executable_command(self):
        cmd = get_executable_command()
        self.assertIn("--autostart", cmd)

    def test_macos_autostart_requires_loaded_service(self):
        state = {"loaded": False, "exists": False}
        mock_file = MagicMock()
        mock_file.exists.side_effect = lambda: state["exists"]
        mock_file.write_bytes.side_effect = lambda *args: state.update(exists=True)
        mock_file.unlink.side_effect = lambda: state.update(exists=False)
        def launchctl(args, **kwargs):
            if args[1] == "bootstrap": state["loaded"] = True
            if args[1] == "bootout": state["loaded"] = False
            return MagicMock(returncode=0 if args[1] != "print" or state["loaded"] else 1)
        with patch("sys.platform", "darwin"), patch("os.getuid", return_value=501, create=True), patch("os.chmod"), patch("core.autostart.get_mac_plist_path", return_value=mock_file), patch("subprocess.run", side_effect=launchctl):
            self.assertFalse(get_autostart_status())
            self.assertTrue(set_autostart(True))
            mock_file.write_bytes.assert_called_once()
            self.assertTrue(get_autostart_status())
            self.assertTrue(set_autostart(False))
            self.assertFalse(get_autostart_status())

    def test_linux_autostart_propagates_failures_and_disabled_state(self):
        state = {"enabled": False}
        mock_file = MagicMock()
        def systemctl(args):
            if args[0] == "enable": state["enabled"] = True
            if args[0] == "disable": state["enabled"] = False
            return True
        def status(args, **kwargs):
            return MagicMock(returncode=0 if state["enabled"] else 1, stdout="enabled" if state["enabled"] else "disabled")
        with patch("sys.platform", "linux"), patch("core.autostart.get_linux_service_path", return_value=mock_file), patch("core.autostart._run_systemctl", side_effect=systemctl), patch("subprocess.run", side_effect=status), patch("os.chmod"), patch("os.path.exists", return_value=False):
            self.assertFalse(get_autostart_status())
            self.assertTrue(set_autostart(True))
            self.assertTrue(get_autostart_status())
            self.assertTrue(set_autostart(False))
            self.assertFalse(get_autostart_status())
            with patch("core.autostart._run_systemctl", return_value=False):
                self.assertFalse(set_autostart(True))
                self.assertFalse(set_autostart(False))

if __name__ == "__main__":
    unittest.main()
