"""
Local SQLite Persistence Layer (`MentorLocalStore`).

Stores:
- Mentor review feedback drafts (`mentor_feedback_drafts`)
- Custom dashboard settings such as custom milestone weights (`mentor_settings`)
- Security & operational audit log (`audit_log`)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class MentorLocalStore:
    """Fault-tolerant SQLite store for mentor drafts, custom settings, and audit logs."""

    def __init__(self, db_path: str = "data/mentor_dashboard.db"):
        self.db_path = Path(db_path)
        self.available = False
        self.last_error: Optional[str] = None
        self._init_db()

    def _init_db(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mentor_feedback_drafts (
                        repo_name TEXT NOT NULL,
                        review_number INTEGER NOT NULL,
                        mentor_username TEXT NOT NULL,
                        submission_status TEXT NOT NULL,
                        mentor_feedback TEXT NOT NULL,
                        strengths_json TEXT NOT NULL,
                        concerns_json TEXT NOT NULL,
                        improvement_areas_json TEXT NOT NULL,
                        criteria_scores_json TEXT NOT NULL,
                        action_items_json TEXT NOT NULL,
                        committed_to_github INTEGER NOT NULL DEFAULT 0,
                        updated_at_utc TEXT NOT NULL,
                        PRIMARY KEY (repo_name, review_number)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mentor_settings (
                        setting_key TEXT PRIMARY KEY,
                        setting_value_json TEXT NOT NULL,
                        updated_at_utc TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_utc TEXT NOT NULL,
                        username TEXT NOT NULL,
                        role TEXT NOT NULL,
                        action TEXT NOT NULL,
                        target_repo TEXT,
                        details TEXT
                    )
                    """
                )
                conn.commit()
            self.available = True
        except Exception as exc:
            self.available = False
            self.last_error = str(exc)

    def save_feedback_draft(
        self,
        repo_name: str,
        review_number: int,
        mentor_username: str,
        submission_status: str,
        mentor_feedback: str,
        strengths: List[str],
        concerns: List[str],
        improvement_areas: List[str],
        criteria_scores: List[Dict[str, Any]],
        action_items: List[Dict[str, Any]],
        committed_to_github: bool = False,
    ) -> bool:
        if not self.available:
            return False
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO mentor_feedback_drafts (
                        repo_name, review_number, mentor_username, submission_status,
                        mentor_feedback, strengths_json, concerns_json, improvement_areas_json,
                        criteria_scores_json, action_items_json, committed_to_github, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(repo_name, review_number) DO UPDATE SET
                        mentor_username = excluded.mentor_username,
                        submission_status = excluded.submission_status,
                        mentor_feedback = excluded.mentor_feedback,
                        strengths_json = excluded.strengths_json,
                        concerns_json = excluded.concerns_json,
                        improvement_areas_json = excluded.improvement_areas_json,
                        criteria_scores_json = excluded.criteria_scores_json,
                        action_items_json = excluded.action_items_json,
                        committed_to_github = excluded.committed_to_github,
                        updated_at_utc = excluded.updated_at_utc
                    """,
                    (
                        repo_name,
                        int(review_number),
                        mentor_username,
                        submission_status,
                        mentor_feedback,
                        json.dumps(strengths),
                        json.dumps(concerns),
                        json.dumps(improvement_areas),
                        json.dumps(criteria_scores),
                        json.dumps(action_items),
                        1 if committed_to_github else 0,
                        now_utc,
                    ),
                )
                conn.commit()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def get_feedback_draft(self, repo_name: str, review_number: int) -> Optional[Dict[str, Any]]:
        if not self.available:
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM mentor_feedback_drafts WHERE repo_name = ? AND review_number = ?",
                    (repo_name, int(review_number)),
                ).fetchone()
                if not row:
                    return None
                return {
                    "repo_name": row["repo_name"],
                    "review_number": row["review_number"],
                    "mentor_username": row["mentor_username"],
                    "submission_status": row["submission_status"],
                    "mentor_feedback": row["mentor_feedback"],
                    "strengths": json.loads(row["strengths_json"] or "[]"),
                    "concerns": json.loads(row["concerns_json"] or "[]"),
                    "improvement_areas": json.loads(row["improvement_areas_json"] or "[]"),
                    "criteria_scores": json.loads(row["criteria_scores_json"] or "[]"),
                    "action_items": json.loads(row["action_items_json"] or "[]"),
                    "committed_to_github": bool(row["committed_to_github"]),
                    "updated_at_utc": row["updated_at_utc"],
                }
        except Exception:
            return None

    def set_setting(self, key: str, value: Any) -> bool:
        if not self.available:
            return False
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO mentor_settings (setting_key, setting_value_json, updated_at_utc)
                    VALUES (?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value_json = excluded.setting_value_json,
                        updated_at_utc = excluded.updated_at_utc
                    """,
                    (key, json.dumps(value), now_utc),
                )
                conn.commit()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def get_setting(self, key: str, default: Any = None) -> Any:
        if not self.available:
            return default
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT setting_value_json FROM mentor_settings WHERE setting_key = ?",
                    (key,),
                ).fetchone()
                if not row:
                    return default
                return json.loads(row[0])
        except Exception:
            return default

    def log_audit_event(
        self,
        username: str,
        role: str,
        action: str,
        target_repo: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        if not self.available:
            return
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log (timestamp_utc, username, role, action, target_repo, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (now_utc, username, role, action, target_repo, details),
                )
                conn.commit()
        except Exception:
            pass

    def get_recent_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.available:
            return []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, timestamp_utc, username, role, action, target_repo, details
                    FROM audit_log
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []
