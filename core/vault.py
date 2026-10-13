"""Private local secret storage. No plaintext or public-key fallback on errors."""
import base64
import ctypes
import os
import secrets
import sys
import stat
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def _dpapi(data, decrypt=False):
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise OSError("系统凭据加密/解密失败")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        local_free = ctypes.WinDLL("kernel32").LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(output.data)

def _key_path():
    configured = os.environ.get("BUAA_VAULT_DIR")
    if configured:
        root = Path(configured)
    elif os.environ.get("BUAA_CONFIG_FILE"):
        root = Path(os.environ["BUAA_CONFIG_FILE"]).resolve().parent
    else:
        from core.profile import resolve_config_path
        root = resolve_config_path().parent
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root / ".vault-key-v2"

def _file_key(create=False):
    path = _key_path()
    if create:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(secrets.token_bytes(32))
                stream.flush()
                os.fsync(stream.fileno())
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid() or path.is_symlink():
            raise PermissionError("凭据密钥必须仅属于当前用户且权限为 0600")
        key = stream.read(33)
    if len(key) != 32:
        raise ValueError("凭据密钥损坏")
    return key

def _keyring_key(create=False):
    import keyring
    # One OS-protected encryption key, rather than an orphan password per config save.
    value = keyring.get_password("BUAA-Signin", "local-vault-v2")
    if value is None and create:
        value = base64.b64encode(secrets.token_bytes(32)).decode()
        keyring.set_password("BUAA-Signin", "local-vault-v2", value)
    if value is None:
        raise ValueError("系统凭据密钥不存在，请重新登录")
    key = base64.b64decode(value, validate=True)
    if len(key) != 32:
        raise ValueError("系统凭据密钥损坏")
    return key

def encrypt(plaintext):
    if not plaintext:
        return ""
    if sys.platform == "win32":
        return "enc:dpapi:" + base64.b64encode(_dpapi(plaintext.encode())).decode()
    import keyring
    backend = keyring.get_keyring()
    backend_name = type(backend).__module__.lower()
    if backend.priority > 0 and ("secretservice" in backend_name or "macos" in backend_name):
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(_keyring_key(create=True)).encrypt(nonce, plaintext.encode(), b"BUAA-Signin/v2")
        return "enc:keyring-v2:" + base64.b64encode(nonce + encrypted).decode()
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_file_key(create=True)).encrypt(nonce, plaintext.encode(), b"BUAA-Signin/v2")
    return "enc:v2:" + base64.b64encode(nonce + ciphertext).decode()

def decrypt(value):
    if value.startswith("enc:keyring-v2:"):
        raw = base64.b64decode(value[len("enc:keyring-v2:"):], validate=True)
        return AESGCM(_keyring_key()).decrypt(raw[:12], raw[12:], b"BUAA-Signin/v2").decode()
    if value.startswith("enc:dpapi:"):
        if sys.platform != "win32":
            raise ValueError("此密码受原 Windows 用户保护，请重新登录")
        return _dpapi(base64.b64decode(value[len("enc:dpapi:"):], validate=True), True).decode()
    if value.startswith("enc:keyring:"):
        import keyring
        result = keyring.get_password("BUAA-Signin", value[len("enc:keyring:"):])
        if result is None:
            raise ValueError("系统凭据不存在，请重新登录")
        return result
    if value.startswith("enc:v2:"):
        raw = base64.b64decode(value[len("enc:v2:"):], validate=True)
        return AESGCM(_file_key()).decrypt(raw[:12], raw[12:], b"BUAA-Signin/v2").decode()
    raise ValueError("未知凭据格式")
