"""Regression for the school's legacy HTTP SSO Location, never an HTTP request."""
import unittest
from core.cas_transport import resolve_auth_redirect, secure_cas_transport_url
from core.domain import trusted_url
from core.webvpn import to_webvpn_url, from_webvpn_url, encrypt_host


class SsoTransport(unittest.TestCase):
    def test_exact_upgrade_preserves_nested_service_encoding(self):
        suffix='/login?service=https%3A%2F%2Fuc.buaa.edu.cn%2Fapi%2Flogin%3Ftarget%3Da%252Bb&x=%2F#fragment'
        for authority in ['http://sso.buaa.edu.cn','http://sso.buaa.edu.cn:80','HTTP://SSO.BUAA.EDU.CN:80']:
            self.assertEqual(secure_cas_transport_url(authority+suffix),'https://sso.buaa.edu.cn'+suffix)

    def test_direct_and_webvpn_raw_and_wrapped_locations(self):
        raw='http://sso.buaa.edu.cn/login?service=https%3A%2F%2Fuc.buaa.edu.cn%2Fapi%2Flogin'
        for mode in ['direct','webvpn']:
            for loc in [raw,to_webvpn_url(raw)]:
                result=resolve_auth_redirect('https://uc.buaa.edu.cn/api/login',loc,mode)
                self.assertEqual(from_webvpn_url(result),raw.replace('http:','https:',1))
                self.assertEqual(result.startswith('https://d.buaa.edu.cn/'),mode=='webvpn')

    def test_untrusted_targets_and_nondefault_ports_remain_blocked(self):
        for loc in ['http://uc.buaa.edu.cn/','http://sso.buaa.edu.cn:8080/login','http://sso.buaa.edu.cn.attacker.test/login','https://attacker.test/login','http://x@sso.buaa.edu.cn/login','http://sso.buaa.edu.cn@attacker.test/login']:
            # The generic VPN encoder discards URL userinfo. Construct that
            # malformed encrypted authority explicitly rather than testing a
            # sanitized representation which no longer contains the attack.
            vpn=('https://d.buaa.edu.cn/http/'+encrypt_host(loc.split('://',1)[1].split('/',1)[0])+'/login'
                 if '@' in loc else to_webvpn_url(loc))
            for wrapped in [loc,vpn]:
                with self.subTest(location=loc,wrapped=wrapped!=loc),self.assertRaises(ValueError):
                    resolve_auth_redirect('https://uc.buaa.edu.cn/api/login',wrapped,'webvpn')

    def test_relative_callback_and_empty_location(self):
        self.assertEqual(resolve_auth_redirect('https://uc.buaa.edu.cn/api/login?ticket=fixture','../home','webvpn'),to_webvpn_url('https://uc.buaa.edu.cn/home'))
        for empty in ['', '  ']:
            with self.assertRaises(ValueError):resolve_auth_redirect('https://uc.buaa.edu.cn/',empty)

    def test_generic_school_allowlist_still_refuses_plaintext(self):
        with self.assertRaises(ValueError):trusted_url('http://sso.buaa.edu.cn/login')
