"""
单元测试：WebVPN 加解密与 CAS 页面解析
对标 UBAA VpnCipherTest 与 CasParserTest
"""

import unittest
from core.webvpn import to_webvpn_url, from_webvpn_url, encrypt_host, decrypt_host
from core.cas import CasParser
from core.iclass import extract_login_name_from_url, resolve_redirect_url, sanitize_signin_message


class TestWebVpn(unittest.TestCase):
    def test_host_encryption_roundtrip(self):
        host = "iclass.buaa.edu.cn"
        encrypted = encrypt_host(host)
        self.assertTrue(len(encrypted) >= 32)
        decrypted = decrypt_host(encrypted)
        self.assertEqual(decrypted, host)

    def test_url_wrapping_roundtrip(self):
        original = "https://iclass.buaa.edu.cn:8346/?loginName=abc%2Bdef%3D&type=jumpMyCenter#/MyCenter"
        vpn_url = to_webvpn_url(original)
        self.assertIn("d.buaa.edu.cn", vpn_url)
        restored = from_webvpn_url(vpn_url)
        self.assertEqual(restored, original)

    def test_standard_http_https_ports(self):
        url_http = "http://sso.buaa.edu.cn/login"
        wrapped_http = to_webvpn_url(url_http)
        self.assertIn("/http/", wrapped_http)
        self.assertEqual(from_webvpn_url(wrapped_http), url_http)

        url_https = "https://sso.buaa.edu.cn/login"
        wrapped_https = to_webvpn_url(url_https)
        self.assertIn("/https/", wrapped_https)
        self.assertEqual(from_webvpn_url(wrapped_https), url_https)


class TestCasParser(unittest.TestCase):
    def test_extract_execution(self):
        html = '<form><input type="hidden" name="execution" value="e1s1_sample_token"></form>'
        self.assertEqual(CasParser.extract_execution(html), "e1s1_sample_token")

    def test_detect_captcha(self):
        html = 'var config = { test: 1 }; config.captcha = { type: "sliding", id: "cap_12345" };'
        result = CasParser.detect_captcha(html)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("sliding", "cap_12345"))

    def test_is_ignorable_password_expiry(self):
        html = '<input name="execution" value="token123"><form id="continueForm">账号存在安全风险</form>'
        self.assertTrue(CasParser.is_ignorable_password_expiry(html))

    def test_build_login_params(self):
        html = '''
        <form>
            <input type="hidden" name="execution" value="exec_val">
            <input type="text" name="username" value="">
            <input type="password" name="password" value="">
        </form>
        '''
        params = CasParser.build_login_params(html, "21370000", "my_password")
        self.assertEqual(params["username"], "21370000")
        self.assertEqual(params["password"], "my_password")
        self.assertEqual(params["execution"], "exec_val")
        self.assertEqual(params["_eventId"], "submit")


class TestIclassSupport(unittest.TestCase):
    def test_extract_login_name(self):
        url = "https://iclass.buaa.edu.cn:8346/?type=jumpMyCenter&loginName=13800000000#page"
        self.assertEqual(extract_login_name_from_url(url), "13800000000")

    def test_sanitize_message(self):
        self.assertEqual(sanitize_signin_message(True, ""), "签到成功")
        self.assertEqual(sanitize_signin_message(False, "系统提示：您今天已签到了"), "您今天已经签到过了")
        self.assertEqual(sanitize_signin_message(False, "当前不是上课时间"), "当前不是上课时间，无法签到")


if __name__ == "__main__":
    unittest.main()
