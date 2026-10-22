import os,unittest,json,hashlib
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import app as backend
from server.presentation import StartupPresentation,capabilities
from core.td_license import container_installation_id,machine_anchor


class DeploymentPresentation(unittest.TestCase):
    def test_atomic_once_across_tabs_clients_and_new_process_epoch(self):
        state=StartupPresentation()
        self.assertFalse(state.claim(prefetch=True))
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(lambda _:state.claim(),range(32))),1)
        self.assertFalse(state.claim())
        self.assertTrue(StartupPresentation().claim())

    def test_no_browser_storage_required_and_reload_html_has_no_blackout(self):
        with patch.object(backend,'startup_presentation',StartupPresentation()),TestClient(backend.app) as c:
            self.assertIn('data-startup-enabled="false"',c.get('/',headers={'Sec-Purpose':'prefetch'}).text)
            self.assertIn('data-startup-enabled="true"',c.get('/').text)
            self.assertIn('data-startup-enabled="false"',c.get('/').text)
            c.cookies.clear()
            self.assertIn('data-startup-enabled="false"',c.get('/').text)
            self.assertEqual(c.get('/').headers['cache-control'],'no-cache, no-store, must-revalidate')

    def test_headless_read_only_capabilities_never_touch_os_autostart(self):
        with patch.dict(os.environ,{'BUAA_RUNTIME_MODE':'headless'}),TestClient(backend.app) as c:
            csrf=c.get('/api/session').json()['csrf']
            with patch('core.autostart.get_autostart_status') as read,patch('core.autostart.set_autostart') as write:
                r=c.get('/api/system/autostart').json()
                self.assertFalse(r['supported']);self.assertEqual(r['runtime']['exit_behavior'],'management-session')
                self.assertEqual(c.post('/api/system/autostart',json={'enabled':True},headers={'X-BUAA-CSRF':csrf}).status_code,409)
                read.assert_not_called();write.assert_not_called()

    def test_explicit_desktop_capability_only(self):
        with patch.dict(os.environ,{'BUAA_RUNTIME_MODE':'desktop'}):
            self.assertTrue(capabilities()['autostart_supported'])
            self.assertEqual(capabilities()['exit_behavior'],'application')

    def test_phone_layout_hint_is_server_runtime_not_user_agent_or_auth(self):
        for mode in ('desktop','headless'):
            with patch.dict(os.environ,{'BUAA_RUNTIME_MODE':mode}),TestClient(backend.app) as c:
                page=c.get('/',headers={'User-Agent':'synthetic iPhone Mobile'})
                self.assertIn('data-runtime-mode="'+mode+'"',page.text)
                self.assertIn('/static/css/remote-phone.css',page.text)
                self.assertIn('/static/js/remote-phone.js',page.text)
                self.assertEqual(capabilities()['exit_behavior'],'application' if mode=='desktop' else 'management-session')

    def test_container_identity_is_private_persistent_and_never_rotates_bad_file(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'BUAA_TD_DEVICE_FILE':str(Path(d)/'.td-device-id')}):
            first=container_installation_id();self.assertEqual(len(first),64)
            self.assertEqual(container_installation_id(),first)
            p=Path(d)/'.td-device-id';p.write_text('damaged')
            with self.assertRaises(OSError):container_installation_id()
            self.assertEqual(p.read_text(),'damaged')

    def test_missing_container_identity_setting_fails_closed(self):
        with patch.dict(os.environ,{'BUAA_TD_DEVICE_FILE':''}):
            with self.assertRaises(OSError):container_installation_id()

    def test_container_empty_system_machine_id_uses_real_license_anchor(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'BUAA_TD_DEVICE_FILE':str(Path(d)/'.td-device-id')}):
            identity=container_installation_id()
            with patch('core.td_license.sys.platform','linux'),patch.object(Path,'is_file',return_value=True),patch.object(Path,'read_text',return_value=''):
                self.assertEqual(machine_anchor(),hashlib.sha256(('linux:'+identity).encode()).hexdigest())

    def test_legacy_empty_profile_keeps_confirmation_metadata_without_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json';p.write_text(json.dumps({'disclaimer_accepted':True,
                'disclaimer_commitment_version':backend.COMMITMENT_VERSION,
                'disclaimer_accepted_at':'synthetic-time','autostart':True,'password':'synthetic-obsolete-secret'}))
            with patch.object(backend,'CONFIG_FILE',p):data=backend.load_config()
            self.assertTrue(data['disclaimer_accepted']);self.assertEqual(data['disclaimer_commitment_version'],backend.COMMITMENT_VERSION)
            self.assertEqual(data['accounts'],[]);self.assertTrue(data['autostart']);self.assertNotIn('password',data)
