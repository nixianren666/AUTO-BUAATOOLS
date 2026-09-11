import unittest
import json
from core.boya_crypto import BykcCrypto

class TestBoyaCrypto(unittest.TestCase):
    def test_encrypt_decrypt_roundtrip(self):
        crypto = BykcCrypto()
        payload = {"courseId": 12345, "name": "博雅测试课程"}
        plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        encrypted_body = crypto.encrypt_plaintext(plaintext)
        decrypted = crypto.decrypt_response(encrypted_body)
        self.assertEqual(decrypted["courseId"], 12345)
        self.assertEqual(decrypted["name"], "博雅测试课程")

    def test_request_encrypt_and_response_decrypt(self):
        crypto = BykcCrypto()
        req_payload = {"pageNumber": 1, "pageSize": 20}
        req_pack = crypto.encrypt_request(req_payload)

        headers = req_pack.headers
        self.assertIn("Ak", headers)
        self.assertIn("Sk", headers)
        self.assertIn("Ts", headers)
        self.assertTrue(len(headers["Ak"]) > 20)
        self.assertTrue(len(headers["Sk"]) > 20)

        body = req_pack.body
        self.assertIsInstance(body, bytes)
        self.assertTrue(len(body) > 0)

        resp_data = {"status": "0", "data": {"content": [{"id": 101, "courseName": "航空航天概论"}]}}
        resp_bytes = json.dumps(resp_data).encode("utf-8")
        encrypted_resp = crypto.encrypt_plaintext(resp_bytes)

        decrypted_resp = crypto.decrypt_response(encrypted_resp)
        self.assertEqual(decrypted_resp["status"], "0")
        self.assertEqual(decrypted_resp["data"]["content"][0]["courseName"], "航空航天概论")

if __name__ == "__main__":
    unittest.main()
