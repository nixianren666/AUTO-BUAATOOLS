"""Atomic operation claims across API/scheduler threads and processes."""
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

class OperationBusy(RuntimeError):
    pass

class OperationLedger:
    def __init__(self, path=":memory:"):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (key TEXT PRIMARY KEY, state TEXT, updated REAL, attempts INTEGER DEFAULT 0)")
        self.db.execute("CREATE TABLE IF NOT EXISTS operation_groups (key TEXT PRIMARY KEY, group_key TEXT)")
        self.db.execute("CREATE INDEX IF NOT EXISTS group_lookup ON operation_groups(group_key)")
        self.db.execute("CREATE TABLE IF NOT EXISTS reservations (user_key TEXT, cid INTEGER, data TEXT, PRIMARY KEY(user_key,cid))")
        self.db.execute("CREATE TABLE IF NOT EXISTS boya_auto_exclusions (user_key TEXT, cid INTEGER, reason TEXT, PRIMARY KEY(user_key,cid))")
        self.db.execute("CREATE TABLE IF NOT EXISTS boya_selected_snapshots (scope_key TEXT, cid INTEGER, PRIMARY KEY(scope_key,cid))")
        self.db.execute("CREATE TABLE IF NOT EXISTS regular_course_policies (user_key TEXT, cid TEXT, data TEXT, PRIMARY KEY(user_key,cid))")
        self.db.commit()
        self._last_prune = time.monotonic()

    @staticmethod
    def key(user, action, cid, day):
        return hashlib.sha256(json.dumps([user, action, str(cid), str(day)]).encode()).hexdigest()

    def claim(self, key, limit=3, group=None, block_group_success=False, retry_delay=None):
        with self.lock:
            if time.monotonic() - self._last_prune >= 86400:
                self.prune()
                self._last_prune = time.monotonic()
            self.db.execute("BEGIN IMMEDIATE")
            try:
                if group:
                    states = {row[0] for row in self.db.execute("SELECT state FROM operations JOIN operation_groups USING(key) WHERE group_key=?", (group,))}
                    if states & {"pending", "uncertain"}:
                        raise OperationBusy("同一操作的先前请求尚待官方确认，禁止跨窗口/容量变化重发")
                    if block_group_success and "success" in states:
                        self.db.commit()
                        return False
                row = self.db.execute("SELECT state, attempts, updated FROM operations WHERE key=?", (key,)).fetchone()
                if row and row[0] == "success":
                    self.db.commit()
                    return False
                if row and (row[0] in ("pending", "uncertain") or row[1] >= limit):
                    raise OperationBusy("操作正在进行、结果待官方复核或已达请求上限")
                if row and retry_delay is not None:
                    remaining = row[2] + retry_delay(row[1]) - time.time()
                    if remaining > 0:
                        import math
                        raise OperationBusy(f"防重复提交冷却中，请在约{math.ceil(remaining)}秒后再试")
                attempts = (row[1] if row else 0) + 1
                self.db.execute("INSERT OR REPLACE INTO operations VALUES (?, 'pending', ?, ?)", (key, time.time(), attempts))
                if group:
                    self.db.execute("INSERT OR REPLACE INTO operation_groups VALUES (?, ?)", (key, group))
                self.db.commit()
                return True
            except BaseException:
                self.db.rollback()
                raise

    def finish(self, key, state):
        if state not in ("success", "failed", "uncertain"):
            raise ValueError("invalid operation state")
        with self.lock:
            self.db.execute("UPDATE operations SET state=?, updated=? WHERE key=?", (state, time.time(), key))
            self.db.commit()

    def read(self, key):
        with self.lock:
            return self.db.execute("SELECT state, attempts, updated FROM operations WHERE key=?", (key,)).fetchone()

    def failed_before_send(self, key):
        """Only transport errors guaranteeing no application request was sent."""
        with self.lock:
            self.db.execute("UPDATE operations SET state='failed', attempts=MAX(0,attempts-1), updated=? WHERE key=? AND state IN ('pending','failed')", (time.time(),key))
            self.db.commit()

    def forget_confirmed(self, key):
        """Only callers with a fresh contrary official enrollment may use this."""
        with self.lock:
            self.db.execute("DELETE FROM operations WHERE key=? AND state='success'", (key,))
            self.db.commit()

    def settle_group(self, group):
        with self.lock:
            self.db.execute("UPDATE operations SET state='success', updated=? WHERE key IN (SELECT key FROM operation_groups WHERE group_key=?) AND state IN ('pending','uncertain')", (time.time(), group))
            self.db.commit()

    def forget_group_confirmed(self, group):
        with self.lock:
            self.db.execute("DELETE FROM operations WHERE key IN (SELECT key FROM operation_groups WHERE group_key=?) AND state='success'", (group,))
            self.db.commit()

    def confirmed(self, key):
        with self.lock:
            self.db.execute("INSERT INTO operations VALUES (?, 'success', ?, 0) ON CONFLICT(key) DO UPDATE SET state='success', updated=excluded.updated", (key, time.time()))
            self.db.commit()

    def prune(self):
        with self.lock:
            self.db.execute("DELETE FROM operations WHERE state IN ('success','failed') AND updated < ?", (time.time()-180*86400,))
            self.db.execute("DELETE FROM operation_groups WHERE key NOT IN (SELECT key FROM operations)")
            self.db.commit()

    def reserve(self, user, course):
        from core.domain import course_id
        cid = course_id(course)
        safe = {field:course.get(field) for field in ("courseStartDate","courseEndDate","courseStartTime","courseEndTime","courseKind")}
        safe.update({"id":cid,"courseId":cid})
        kind = course.get("courseNewKind2")
        if isinstance(kind, dict):
            safe["courseNewKind2"] = {"kindName":kind.get("kindName")}
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO reservations VALUES (?,?,?)", (self.key(user,"reservation","",""),cid,json.dumps(safe)))
            self.db.commit()

    def reservations(self, user):
        with self.lock:
            rows=self.db.execute("SELECT cid,data FROM reservations WHERE user_key=?",(self.key(user,"reservation","",""),)).fetchall()
        return {cid:json.loads(data) for cid,data in rows}

    def clear_reservation(self, user, cid):
        with self.lock:
            self.db.execute("DELETE FROM reservations WHERE user_key=? AND cid=?",(self.key(user,"reservation","",""),cid))
            self.db.commit()

    def exclude_auto_select(self, user, cid, reason="manual_drop"):
        """User intent is monotonic: fresh capacity or a restart cannot undo it."""
        with self.lock:
            try:
                self.db.execute("INSERT OR IGNORE INTO boya_auto_exclusions VALUES (?,?,?)",(self.key(user,"boya-auto-exclusion","",""),int(cid),reason))
                self.db.commit()
            except BaseException:
                self.db.rollback();raise

    def auto_select_excluded(self, user, cid):
        with self.lock:
            return self.db.execute("SELECT 1 FROM boya_auto_exclusions WHERE user_key=? AND cid=?",(self.key(user,"boya-auto-exclusion","",""),int(cid))).fetchone() is not None

    def observe_selected(self, user, scope, ids):
        """Only a fully validated official list may replace the same query scope.

        Disappearance does not prove why a course was removed. It conservatively
        forbids auto re-enrollment; explicit manual selection remains available.
        """
        ids=set(ids);scope_key=self.key(user,"boya-selected-snapshot","",scope)
        owner=self.key(user,"boya-auto-exclusion","","")
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                previous={r[0] for r in self.db.execute("SELECT cid FROM boya_selected_snapshots WHERE scope_key=?",(scope_key,))}
                if previous==ids:
                    self.db.commit();return
                self.db.executemany("INSERT OR IGNORE INTO boya_auto_exclusions VALUES (?,?,?)",[(owner,cid,"official_removed") for cid in previous-ids])
                self.db.execute("DELETE FROM boya_selected_snapshots WHERE scope_key=?",(scope_key,))
                self.db.executemany("INSERT INTO boya_selected_snapshots VALUES (?,?)",[(scope_key,cid) for cid in ids])
                self.db.commit()
            except BaseException:
                self.db.rollback();raise

    def regular_course_policy(self, user, cid):
        with self.lock:
            row=self.db.execute("SELECT data FROM regular_course_policies WHERE user_key=? AND cid=?",(self.key(user,"regular-course-policy","",""),cid)).fetchone()
            return json.loads(row[0]) if row else None

    def regular_course_policies(self, user):
        with self.lock:
            rows=self.db.execute("SELECT data FROM regular_course_policies WHERE user_key=?",(self.key(user,"regular-course-policy","",""),)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def set_regular_course_policy(self, user, cid, data):
        owner=self.key(user,"regular-course-policy","","")
        with self.lock:
            try:
                if data is None:self.db.execute("DELETE FROM regular_course_policies WHERE user_key=? AND cid=?",(owner,cid))
                else:
                    count=self.db.execute("SELECT count(*) FROM regular_course_policies WHERE user_key=?",(owner,)).fetchone()[0]
                    existing=self.db.execute("SELECT 1 FROM regular_course_policies WHERE user_key=? AND cid=?",(owner,cid)).fetchone()
                    if count>=512 and not existing:raise ValueError("课程设置数量已达上限，请先恢复不再需要暂停的课程")
                    self.db.execute("INSERT OR REPLACE INTO regular_course_policies VALUES (?,?,?)",(owner,cid,json.dumps(data)))
                self.db.commit()
            except BaseException:
                self.db.rollback();raise

ledger = OperationLedger()

def configure(path):
    global ledger
    if os.environ.get("TESTING") != "1":
        ledger = OperationLedger(path)
        ledger.prune()
