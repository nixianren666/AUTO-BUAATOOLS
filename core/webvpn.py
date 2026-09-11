"""
BUAA WebVPN (d.buaa.edu.cn) URL 加解密与重写模块
复刻自 BUAASubnet/UBAA LocalWebVpnSupport 算法规范
"""

import urllib.parse
import warnings
from typing import Optional

# 抑制 cryptography 关于 CFB mode 移动的警告
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    try:
        from cryptography.hazmat.decrepit.ciphers.modes import CFB
    except ImportError:
        from cryptography.hazmat.primitives.ciphers.modes import CFB
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    from cryptography.hazmat.backends import default_backend

GATEWAY_HOST = "d.buaa.edu.cn"
KEY_BYTES = b"wrdvpnisthebest!"
IV_BYTES = b"wrdvpnisthebest!"


def _encrypt_aes_cfb(plain: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), CFB(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    return encryptor.update(plain) + encryptor.finalize()


def _decrypt_aes_cfb(cipher_bytes: bytes, key: bytes, iv: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), CFB(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(cipher_bytes) + decryptor.finalize()


def encrypt_host(host: str) -> str:
    """加密原始域名为 WebVPN 路径参数"""
    plain = host.encode("utf-8")
    pad_len = (16 - len(plain) % 16) % 16
    padded = plain + (b"0" * pad_len)
    cipher_text = _encrypt_aes_cfb(padded, KEY_BYTES, IV_BYTES)
    return IV_BYTES.hex() + cipher_text.hex()[: len(plain) * 2]


def decrypt_host(encoded_host: str) -> str:
    """解密 WebVPN 路径参数为原始域名"""
    if len(encoded_host) < 32:
        raise ValueError("Invalid WebVPN host payload length")
    iv = bytes.fromhex(encoded_host[:32])
    cipher_hex = encoded_host[32:]
    pad_len = (32 - len(cipher_hex) % 32) % 32
    padded_hex = cipher_hex + ("0" * pad_len)
    decrypted = _decrypt_aes_cfb(bytes.fromhex(padded_hex), KEY_BYTES, iv)
    original_len = len(encoded_host) // 2 - 16
    return decrypted[:original_len].decode("utf-8", errors="ignore")


def to_webvpn_url(url: str) -> str:
    """将普通校内 URL 转换为 WebVPN 网关访问 URL"""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    if parsed.hostname and parsed.hostname.lower() == GATEWAY_HOST.lower():
        return url

    scheme = parsed.scheme.lower()
    port = parsed.port
    host = parsed.hostname or ""

    if port == 80 and scheme == "http":
        protocol_part = "http"
    elif port == 443 and scheme == "https":
        protocol_part = "https"
    elif port is None or port <= 0:
        protocol_part = scheme
    else:
        protocol_part = f"{scheme}-{port}"

    encoded_host = encrypt_host(host)
    path = parsed.path or ""
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""

    return f"https://{GATEWAY_HOST}/{protocol_part}/{encoded_host}{path}{query}{fragment}"


def from_webvpn_url(url: str) -> str:
    """将 WebVPN 网关访问 URL 还原为原始校内 URL"""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.hostname or parsed.hostname.lower() != GATEWAY_HOST.lower():
        return url

    path_segments = [s for s in parsed.path.split("/") if s]
    if len(path_segments) < 2:
        return url

    protocol_part = path_segments[0]
    encoded_host = path_segments[1]

    parts = protocol_part.split("-", 1)
    scheme = parts[0]
    port = parts[1] if len(parts) > 1 else None

    try:
        host = decrypt_host(encoded_host)
    except Exception:
        return url

    authority = f"{scheme}://{host}" + (f":{port}" if port else "")
    remaining_segments = path_segments[2:]
    if remaining_segments:
        path = "/" + "/".join(remaining_segments)
        if parsed.path.endswith("/") and not path.endswith("/"):
            path += "/"
    elif parsed.path.endswith("/"):
        path = "/"
    else:
        path = ""

    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""

    return f"{authority}{path}{query}{fragment}"
