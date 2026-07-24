#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
待办任务存储模块（SQLite）
"""

import datetime
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple


class TodoStore:
    """待办任务持久化存储。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    event_title TEXT NOT NULL,
                    meeting_time TEXT NOT NULL,
                    trigger_time TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    recipient_email TEXT NOT NULL,
                    recipient_source TEXT NOT NULL,
                    email_template TEXT NOT NULL,
                    status TEXT NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 3,
                    last_error TEXT NOT NULL DEFAULT '',
                    retain_days_snapshot INTEGER NOT NULL DEFAULT 7,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    meta_json TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS task_ops (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    op_type TEXT NOT NULL,
                    op_desc TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    extra_json TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status_trigger ON tasks(status, trigger_time)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_task_ops_task ON task_ops(task_id)")
            self._conn.commit()

    def close(self) -> None:
        """释放 SQLite 连接。"""
        with self._lock:
            self._conn.close()

    @staticmethod
    def _now_iso() -> str:
        return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {k: row[k] for k in row.keys()}

    def create_task(self, task: Dict[str, Any]) -> None:
        now = self._now_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO tasks (
                    task_id, user_id, event_title, meeting_time, trigger_time, timezone,
                    recipient_email, recipient_source, email_template, status,
                    retry_count, max_retries, last_error, retain_days_snapshot,
                    created_at, updated_at, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["task_id"],
                    task.get("user_id", "default"),
                    task["event_title"],
                    task["meeting_time"],
                    task["trigger_time"],
                    task["timezone"],
                    task["recipient_email"],
                    task.get("recipient_source", "profile"),
                    task["email_template"],
                    task.get("status", "scheduled"),
                    task.get("retry_count", 0),
                    task.get("max_retries", 3),
                    task.get("last_error", ""),
                    task.get("retain_days_snapshot", 7),
                    now,
                    now,
                    task.get("meta_json", ""),
                ),
            )
            self._conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def list_scheduled(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status = 'scheduled' ORDER BY trigger_time ASC"
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def recover_interrupted_sending(self) -> int:
        """应用重启时将异常中断的 sending 任务恢复为可重试状态。"""
        with self._lock:
            now = self._now_iso()
            cur = self._conn.execute(
                """
                UPDATE tasks
                SET status='scheduled', trigger_time=?, updated_at=?,
                    last_error='应用在发送过程中退出，已自动恢复'
                WHERE status='sending'
                """,
                (now, now),
            )
            self._conn.commit()
            return cur.rowcount

    def list_scheduled_matching(self, keyword: str) -> List[Dict[str, Any]]:
        kw = (keyword or "").strip()
        with self._lock:
            if not kw:
                rows = self._conn.execute(
                    "SELECT * FROM tasks WHERE status = 'scheduled' ORDER BY trigger_time ASC"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'scheduled'
                      AND (event_title LIKE ? OR task_id LIKE ?)
                    ORDER BY trigger_time ASC
                    """,
                    (f"%{kw}%", f"%{kw}%"),
                ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            now = self._now_iso()
            cur = self._conn.execute(
                "UPDATE tasks SET status='cancelled', updated_at=? WHERE task_id=? AND status='scheduled'",
                (now, task_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def replace_task_atomic(self, old_task_id: str, new_task: Dict[str, Any]) -> Tuple[bool, str]:
        """原子替换：旧任务取消 + 新任务创建。"""
        now = self._now_iso()
        with self._lock:
            try:
                cur = self._conn.cursor()
                cur.execute("BEGIN")
                cur.execute(
                    "UPDATE tasks SET status='cancelled', updated_at=? WHERE task_id=? AND status='scheduled'",
                    (now, old_task_id),
                )
                if cur.rowcount == 0:
                    cur.execute("ROLLBACK")
                    return False, "旧任务不存在或已不可修改"

                cur.execute(
                    """
                    INSERT INTO tasks (
                        task_id, user_id, event_title, meeting_time, trigger_time, timezone,
                        recipient_email, recipient_source, email_template, status,
                        retry_count, max_retries, last_error, retain_days_snapshot,
                        created_at, updated_at, meta_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_task["task_id"],
                        new_task.get("user_id", "default"),
                        new_task["event_title"],
                        new_task["meeting_time"],
                        new_task["trigger_time"],
                        new_task["timezone"],
                        new_task["recipient_email"],
                        new_task.get("recipient_source", "profile"),
                        new_task["email_template"],
                        new_task.get("status", "scheduled"),
                        new_task.get("retry_count", 0),
                        new_task.get("max_retries", 3),
                        new_task.get("last_error", ""),
                        new_task.get("retain_days_snapshot", 7),
                        now,
                        now,
                        new_task.get("meta_json", ""),
                    ),
                )
                cur.execute("COMMIT")
                return True, ""
            except Exception as e:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                return False, str(e)

    def try_mark_sending(self, task_id: str) -> bool:
        """幂等锁：仅 scheduled -> sending 才成功。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status='sending', updated_at=? WHERE task_id=? AND status='scheduled'",
                (self._now_iso(), task_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_sent(self, task_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status='sent', updated_at=?, last_error='' WHERE task_id=?",
                (self._now_iso(), task_id),
            )
            self._conn.commit()

    def requeue_with_retry(self, task_id: str, error: str, delay_seconds: int) -> Optional[Dict[str, Any]]:
        """失败后重试：retry_count+1，状态回到 scheduled，刷新 trigger_time。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT retry_count, max_retries FROM tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            retry_count = int(row["retry_count"]) + 1
            max_retries = int(row["max_retries"])
            if retry_count > max_retries:
                self._conn.execute(
                    "UPDATE tasks SET status='failed', retry_count=?, last_error=?, updated_at=? WHERE task_id=?",
                    (retry_count, error, self._now_iso(), task_id),
                )
                self._conn.commit()
                return self.get_task(task_id)

            new_trigger = datetime.datetime.now().astimezone() + datetime.timedelta(seconds=delay_seconds)
            self._conn.execute(
                """
                UPDATE tasks
                SET status='scheduled',
                    retry_count=?,
                    trigger_time=?,
                    last_error=?,
                    updated_at=?
                WHERE task_id=?
                """,
                (retry_count, new_trigger.isoformat(timespec="seconds"), error, self._now_iso(), task_id),
            )
            self._conn.commit()
            return self.get_task(task_id)

    def add_op_log(self, task_id: str, op_type: str, op_desc: str, extra_json: str = "") -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO task_ops(task_id, op_type, op_desc, timestamp, extra_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, op_type, op_desc, self._now_iso(), extra_json),
            )
            self._conn.commit()

    def cleanup_expired(self, default_retention_days: int) -> int:
        """清理已完成类任务（sent/cancelled/failed）。scheduled 不清理。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT task_id, created_at, retain_days_snapshot FROM tasks WHERE status IN ('sent','cancelled','failed')"
            ).fetchall()
            to_delete = []
            now = datetime.datetime.now().astimezone()
            for row in rows:
                created_at = row["created_at"]
                days = int(row["retain_days_snapshot"] or default_retention_days)
                try:
                    created_dt = datetime.datetime.fromisoformat(created_at)
                except Exception:
                    created_dt = now
                # 兼容历史数据：旧记录可能是 naive datetime
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=now.tzinfo)
                if (now - created_dt).days >= days:
                    to_delete.append(row["task_id"])

            if not to_delete:
                return 0

            q = ",".join("?" for _ in to_delete)
            self._conn.execute(f"DELETE FROM tasks WHERE task_id IN ({q})", to_delete)
            self._conn.execute(f"DELETE FROM task_ops WHERE task_id IN ({q})", to_delete)
            self._conn.commit()
            return len(to_delete)

    def manual_cleanup(self, mode: str, default_retention_days: int) -> int:
        """
        手动清理：
        - all: 按保留期清理 sent/cancelled/failed
        - sent / cancelled / failed: 仅清理对应状态
        """
        if mode == "all":
            return self.cleanup_expired(default_retention_days)

        if mode not in ("sent", "cancelled", "failed"):
            return 0

        with self._lock:
            rows = self._conn.execute("SELECT task_id FROM tasks WHERE status = ?", (mode,)).fetchall()
            ids = [r["task_id"] for r in rows]
            if not ids:
                return 0
            q = ",".join("?" for _ in ids)
            self._conn.execute(f"DELETE FROM tasks WHERE task_id IN ({q})", ids)
            self._conn.execute(f"DELETE FROM task_ops WHERE task_id IN ({q})", ids)
            self._conn.commit()
            return len(ids)

