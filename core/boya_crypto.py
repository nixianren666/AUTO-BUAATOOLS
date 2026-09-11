"""
北航博雅系统 (BYKC) 加密与签名算法
支持 AES-128-ECB 对称加密与 RSA-1024 非对称公钥交换
"""

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import padding as sym_padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BYKC_RSA_PEM = b"""-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDlHMQ3B5GsWnCe7Nlo1YiG/YmH
dlOiKOST5aRm4iaqYSvhvWmwcigoyWTM+8bv2+sf6nQBRDWTY4KmNV7DBk1eDnTI
Qo6ENA31k5/tYCLEXgjPbEjCK9spiyB62fCT6cqOhbamJB0lcDJRO6Vo1m3dy+fD
0jbxfDVBBNtyltIsDQIDAQAB
-----END PUBLIC KEY-----
"""

KEY_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"


@dataclass
class EncryptedRequest:
    body: bytes
    headers: Dict[str, str]


def random_aes_key() -> bytes:
    """生成随机 16 字节 AES 密钥"""
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(16)).encode("utf-8")


class BykcCrypto:
    def __init__(self, key: Optional[bytes] = None) -> None:
        self.key = key or random_aes_key()
        self.public_key = serialization.load_pem_public_key(BYKC_RSA_PEM)

    def encrypt_plaintext(self, plaintext: bytes) -> bytes:
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(algorithms.AES(self.key), modes.ECB()).encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        return json.dumps(base64.b64encode(encrypted).decode("utf-8")).encode("utf-8")

    def decrypt_response(self, body: Any) -> Any:
        text = body.decode("utf-8") if isinstance(body, bytes) else body
        encoded = json.loads(text)
        encrypted = base64.b64decode(encoded)
        decryptor = Cipher(algorithms.AES(self.key), modes.ECB()).decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        unpadder = sym_padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        return json.loads(plaintext.decode("utf-8"))

    def encrypt_request(self, payload: Any) -> EncryptedRequest:
        if isinstance(payload, str):
            plaintext = payload.encode("utf-8")
        else:
            plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        body = self.encrypt_plaintext(plaintext)
        return EncryptedRequest(
            body=body,
            headers={
                "Ak": self._rsa_b64(self.key),
                "Sk": self._rsa_b64(hashlib.sha1(plaintext).hexdigest().encode("utf-8")),
                "Ts": str(int(time.time() * 1000)),
            },
        )

    def _rsa_b64(self, data: bytes) -> str:
        encrypted = self.public_key.encrypt(data, asym_padding.PKCS1v15())
        return base64.b64encode(encrypted).decode("utf-8")