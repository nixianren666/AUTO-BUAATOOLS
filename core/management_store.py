"""Private password/recovery hashes. No student data and no reversible passwords."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading

from core.profile import resolve_config_path


class ManagementStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else resolve_config_path().with_name('.management-private.json')
        self.lock = threading.RLock()

    def read(self):
        if self.path.is_symlink():
            raise ValueError('管理凭据文件不可为链接')
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        if len(raw) > 8192:
            raise ValueError('管理凭据文件损坏')
        data = json.loads(raw)
        if data.get('version') != 1 or not isinstance(data.get('password'), str) or not isinstance(data.get('recovery'), str):
            raise ValueError('管理凭据文件损坏，请恢复私有备份')
        return data

    @staticmethod
    def digest(value, salt=None):
        salt = salt or secrets.token_bytes(16)
        result = hashlib.scrypt(value.encode('utf-8'), salt=salt, n=16384, r=8, p=1, dklen=32)
        return base64.b64encode(salt + result).decode('ascii')

    @classmethod
    def matches(cls, value, encoded):
        try:
            raw = base64.b64decode(encoded, validate=True)
            return len(raw) == 48 and secrets.compare_digest(cls.digest(value, raw[:16]), encoded)
        except (ValueError, TypeError):
            return False

    def verify(self, password, legacy=''):
        with self.lock:
            data = self.read()
            return self.matches(password, data['password']) if data else bool(legacy) and secrets.compare_digest(password.encode('utf-8'), legacy.encode('utf-8'))

    def write(self, data, create=False):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.management-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            if create:
                # Atomic no-replace: concurrent first claims cannot overwrite.
                os.link(temporary, self.path)
            else:
                if self.path.is_symlink():
                    raise ValueError('管理凭据文件不可为链接')
                os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def set_password(self, password, *, first=False, recovery=None, current=None, legacy=''):
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise ValueError('管理密码需要 8–128 个字符')
        with self.lock:
            data = self.read()
            if first:
                if data or legacy:
                    raise ValueError('服务已经设置管理密码')
            elif recovery is not None:
                if not data or not self.matches(recovery.strip(), data['recovery']):
                    raise PermissionError('恢复码无效')
            elif not self.verify(current or '', legacy):
                raise PermissionError('当前管理密码错误')
            code = secrets.token_urlsafe(32)
            self.write({'version': 1, 'password': self.digest(password), 'recovery': self.digest(code)}, create=not bool(data))
            return code

    def bootstrap_token(self):
        """A deployment-local one-time proof, never included in public status."""
        path = self.path.with_name('.management-setup-token')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ValueError('初始化凭据文件不可为链接')
        if not path.exists():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'w', encoding='ascii') as stream:
                    stream.write(secrets.token_urlsafe(32))
                    stream.flush()
                    os.fsync(stream.fileno())
        token = path.read_text(encoding='ascii').strip()
        if len(token) < 40:
            raise ValueError('初始化凭据不完整，请由部署者检查私有文件')
        return token
