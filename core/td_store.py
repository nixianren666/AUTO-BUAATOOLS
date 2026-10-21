"""Private per-account TD media and transactional, crash-safe operation journal."""
from contextlib import contextmanager
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import uuid
import warnings

from PIL import Image, ImageOps
from core.td_policy import validate_settings

DEFAULTS = dict(enabled=False, campus="学院路", start="", end="", target=32,
                daily_limit=3, count=None, count_source="unknown", count_at=None,
                confirmed=False, last_photo=None, last_group=None, semester_start='', semester_end='', weekdays=[], closed_dates=[])
BUSY = {"sending_entry", "sending_exit", "waiting_exit", "uncertain", "rejected"}


def owner_key(username):
    return hashlib.sha256(("td-v1:" + username).encode()).hexdigest()


class TDStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "state.sqlite", timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles(owner TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS images(owner TEXT, id TEXT, digest TEXT, bytes INTEGER,
                PRIMARY KEY(owner,id), UNIQUE(owner,digest));
            CREATE TABLE IF NOT EXISTS jobs(owner TEXT, day TEXT, data TEXT NOT NULL,
                PRIMARY KEY(owner,day));
            CREATE TABLE IF NOT EXISTS photo_groups(owner TEXT, id TEXT, name TEXT,
                entry_image TEXT, exit_image TEXT, PRIMARY KEY(owner,id));
            """)
            self.db.commit()
        except BaseException:
            self.db.close()
            raise
        try:
            os.chmod(self.root, 0o700)
            os.chmod(self.root / "state.sqlite", 0o600)
        except OSError:
            pass  # Native Windows inherits the containing user's directory ACL.

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def profile(self, owner):
        row = self.db.execute("SELECT data FROM profiles WHERE owner=?", (owner,)).fetchone()
        return {**DEFAULTS, **(json.loads(row[0]) if row else {})}

    def save_profile(self, owner, data):
        self.db.execute("INSERT OR REPLACE INTO profiles VALUES (?,?)", (owner, json.dumps(data)))

    def job(self, owner, day):
        row = self.db.execute("SELECT data FROM jobs WHERE owner=? AND day=?", (owner, day)).fetchone()
        return json.loads(row[0]) if row else dict(state="idle", attempted=0, completed=0, due=0)

    def save_job(self, owner, day, data):
        self.db.execute("INSERT OR REPLACE INTO jobs VALUES (?,?,?)", (owner, day, json.dumps(data)))

    def outstanding(self, owner):
        return [(row[0], json.loads(row[1])) for row in self.db.execute(
            "SELECT day,data FROM jobs WHERE owner=? ORDER BY day DESC", (owner,))
                if json.loads(row[1]).get("state") in BUSY]

    def configure(self, username, settings):
        owner = owner_key(username)
        with self.transaction():
            previous = self.profile(owner)
            structural = any(settings[k] != previous[k] for k in ("semester_start", "semester_end", "start", "end", "campus", "daily_limit", "target", "weekdays", "closed_dates"))
            if structural and self.outstanding(owner):
                raise ValueError("仍有配对或待核验记录，请先暂停并核对后再改规则")
            validate_settings(settings)
            old_term = (previous['semester_start'], previous['semester_end'])
            new_term = (settings['semester_start'], settings['semester_end'])
            if old_term != new_term and old_term != ('', ''):
                previous.update(count=None, count_source="unknown", count_at=None)
            # Saving a setting never silently starts an operation.
            previous.update(settings)
            previous["enabled"] = False
            self.save_profile(owner, previous)

    def images(self, owner):
        return [dict(row) for row in self.db.execute("SELECT id,bytes FROM images WHERE owner=? ORDER BY rowid", (owner,))]

    def groups(self, owner):
        return [dict(row) for row in self.db.execute('SELECT id,name,entry_image,exit_image FROM photo_groups WHERE owner=? ORDER BY rowid', (owner,))]

    def create_group(self, username, entry_id, exit_id, name, confirmed):
        if confirmed is not True:
            raise ValueError('请确认本组两张照片为本人且穿搭、妆容一致')
        if not isinstance(name, str) or len(name.strip()) > 40:
            raise ValueError('照片组名称最多40字')
        owner = owner_key(username)
        with self.transaction():
            duplicate = self.db.execute('SELECT id FROM photo_groups WHERE owner=? AND entry_image=? AND exit_image=?', (owner,entry_id,exit_id)).fetchone()
            if duplicate:
                return {'id':duplicate[0], 'duplicate':True}
            if len(self.groups(owner)) >= 50:
                raise ValueError('每账号最多50组')
            for image_id in (entry_id, exit_id):
                self.image_path(owner, image_id)
                if not self.db.execute('SELECT 1 FROM images WHERE owner=? AND id=?', (owner,image_id)).fetchone():
                    raise ValueError('照片不存在或不属于当前账号')
            group_id = uuid.uuid4().hex
            self.db.execute('INSERT INTO photo_groups VALUES (?,?,?,?,?)', (owner,group_id,name.strip() or '本人照片组',entry_id,exit_id))
            return {'id':group_id}

    def import_group(self, username, entry_bytes, exit_bytes, name, confirmed):
        # Decode/validate BOTH before touching the library. Group visibility is
        # committed only after both images exist; partial imports never execute.
        entry_encoded, exit_encoded = self.encode_image(entry_bytes), self.encode_image(exit_bytes)
        owner = owner_key(username)
        created = []
        with self.lock:
            if confirmed is not True or len(self.groups(owner)) >= 50:
                raise ValueError('请确认照片一致性，并检查50组上限')
            try:
                entry = self.add_encoded(username, entry_encoded)
                if not entry['duplicate']: created.append(entry['id'])
                exit_image = self.add_encoded(username, exit_encoded)
                if not exit_image['duplicate']: created.append(exit_image['id'])
                return self.create_group(username, entry['id'], exit_image['id'], name, confirmed)
            except BaseException:
                if created:
                    self.delete_images(username, created)
                raise

    def delete_groups(self, username, ids):
        owner = owner_key(username)
        with self.lock:
            with self.transaction():
                protected = {j.get('group_id') for _,j in self.outstanding(owner)}
                if protected.intersection(ids):
                    raise ValueError('照片组正在配对或待核验，不能删除')
                groups = {g['id']:g for g in self.groups(owner)}
                if any(group_id not in groups for group_id in ids):
                    raise ValueError('照片组不存在或不属于当前账号')
                candidates = {groups[g][key] for g in ids for key in ('entry_image','exit_image')}
                self.db.executemany('DELETE FROM photo_groups WHERE owner=? AND id=?', [(owner,g) for g in ids])
                referenced = {g[key] for g in self.groups(owner) for key in ('entry_image','exit_image')}
                protected_images = {j.get(key) for _,j in self.outstanding(owner) for key in ('entry_image','exit_image')}
            unused = candidates - referenced - protected_images
            return self.delete_images(username, list(unused)) if unused else {'cleanup_pending':0}

    def image_path(self, owner, image_id, thumbnail=False):
        if not re.fullmatch(r"[0-9a-f]{64}", owner) or not re.fullmatch(r"[0-9a-f]{32}", image_id):
            raise ValueError("无效图片标识")
        return self.root / owner / (image_id + (".thumb.jpg" if thumbnail else ".jpg"))

    @staticmethod
    def encode_image(data):
        if not 1 <= len(data) <= 8 * 1024 * 1024:
            raise ValueError("每张图片需在8MB以内")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as original:
                    if original.format not in ("JPEG", "PNG", "WEBP") or original.width * original.height > 16000000 or getattr(original, "n_frames", 1) != 1:
                        raise ValueError()
                    image = ImageOps.exif_transpose(original).convert("RGB")
                    image.thumbnail((1600, 1600))
                    full = io.BytesIO(); image.save(full, "JPEG", quality=86)
                    image.thumbnail((320, 240))
                    small = io.BytesIO(); image.save(small, "JPEG", quality=80)
                    jpeg, thumb = full.getvalue(), small.getvalue()
        except Exception as exc:
            raise ValueError("仅支持有效的静态JPEG/PNG/WebP，像素不超过1600万；图片未导入") from exc
        return jpeg, thumb

    def add_image(self, username, data):
        return self.add_encoded(username, self.encode_image(data))

    def add_encoded(self, username, encoded):
        jpeg, thumb = encoded
        owner = owner_key(username)
        digest = hashlib.sha256(jpeg).hexdigest()
        with self.transaction():
            duplicate = self.db.execute("SELECT id FROM images WHERE owner=? AND digest=?", (owner, digest)).fetchone()
            if duplicate:
                return {"id": duplicate[0], "duplicate": True}
            total, size = self.db.execute("SELECT count(*),COALESCE(sum(bytes),0) FROM images WHERE owner=?", (owner,)).fetchone()
            if total >= 100 or size + len(jpeg) > 100 * 1024 * 1024:
                raise ValueError("每账号最多100张或100MB，请先删除不用的图片")
            image_id = uuid.uuid4().hex
            path = self.image_path(owner, image_id)
            path.parent.mkdir(exist_ok=True, mode=0o700)
            try:
                path.write_bytes(jpeg)
                self.image_path(owner, image_id, True).write_bytes(thumb)
                os.chmod(path, 0o600)
                os.chmod(self.image_path(owner, image_id, True), 0o600)
                self.db.execute("INSERT INTO images VALUES (?,?,?,?)", (owner, image_id, digest, len(jpeg)))
            except BaseException:
                path.unlink(missing_ok=True)
                self.image_path(owner, image_id, True).unlink(missing_ok=True)
                raise
        return {"id": image_id, "duplicate": False}

    def read_image(self, username, image_id, thumbnail=False):
        owner = owner_key(username)
        with self.lock:
            if not self.db.execute("SELECT 1 FROM images WHERE owner=? AND id=?", (owner, image_id)).fetchone():
                raise ValueError("图片不存在或不属于当前账号")
            return self.image_path(owner, image_id, thumbnail).read_bytes()

    def delete_images(self, username, ids):
        owner = owner_key(username)
        staged = []
        try:
            with self.transaction():
                protected = {j.get(key) for _, j in self.outstanding(owner) for key in ("entry_image", "exit_image")}
                protected.update(g[key] for g in self.groups(owner) for key in ('entry_image','exit_image'))
                if protected.intersection(ids):
                    raise ValueError("所选图片正在配对或待核验中，不能删除")
                for image_id in ids:
                    self.image_path(owner, image_id)
                    if not self.db.execute("SELECT 1 FROM images WHERE owner=? AND id=?", (owner, image_id)).fetchone():
                        raise ValueError("图片不存在或不属于当前账号")
                for image_id in ids:
                    for thumbnail in (False, True):
                        path = self.image_path(owner, image_id, thumbnail)
                        if path.exists():
                            trash = path.with_name(path.name + '.delete-' + uuid.uuid4().hex)
                            path.rename(trash)
                            staged.append((path, trash))
                    self.db.execute("DELETE FROM images WHERE owner=? AND id=?", (owner, image_id))
        except BaseException:
            for path, trash in reversed(staged):
                if trash.exists():
                    trash.rename(path)
            raise
        pending = 0
        for _, trash in staged:
            try:
                trash.unlink(missing_ok=True)
            except OSError:
                pending += 1
        return {"cleanup_pending": pending}
