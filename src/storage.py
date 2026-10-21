"""
Optional lightweight SQLite storage for mentor-specific application state.

Authoritative Source of Truth Policy:
- GitHub private repositories (`pbl-team-13`..`pbl-team-18`) are the SOLE source of truth
  for student project files, code, documentation, tasks, and committed metadata.
- This local SQLite database stores ONLY mentor-facing application data that does not belong
  in student repositories by default:
  1. `mentor_feedback_drafts`: Mentor review evaluations, scores, and action items drafted in
     the dashboard prior to optional explicit GitHub commit.
  2. `mentor_settings`: Custom milestone weight overrides or cohort display preferences.
  3. `audit_log`: Security and administrative audit trail (logins, feedback saves, explicit GitHub commits).
- Never stores GitHub tokens, passwords, or secrets.
- Degrades gracefully: if SQLite is unavailable or read-only, all repository browsing and
  analytics continue uninterrupted.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class MentorLocalStore:
    """Fault-tolerant SQLite wrapper for mentor drafts, preferences, and audit events."""

    def __init__(self, db_path: str = "data/mentor_dashboard.db"):
        self.db_path = db_path
        self.available = False
        self.last_error: Optional[str] = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS mentor_feedback_drafts (
                        repo_name TEXT NOT NULL,
                        review_number INTEGER NOT NULL,
                        mentor_username TEXT NOT NULL,
                        submission_status TEXT NOT NULL,
                        mentor_feedback TEXT,
                        strengths_json TEXT,
                        concerns_json TEXT,
                        improvement_areas_json TEXT,
                        criteria_scores_json TEXT,
                        action_items_json TEXT,
                        updated_at_utc TEXT NOT NULL,
                        committed_to_github INTEGER DEFAULT 0,
                        PRIMARY KEY (repo_name, review_number)
                    );

                    CREATE TABLE IF NOT EXISTS mentor_settings (
                        setting_key TEXT PRIMARY KEY,
                        setting_value_json TEXT NOT NULL,
                        updated_by TEXT,
                        updated_at_utc TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp_utc TEXT NOT NULL,
                        username TEXT NOT NULL,
                        role TEXT NOT NULL,
                        action TEXT NOT NULL,
                        target_repo TEXT,
                        details TEXT
                    );
                    """
                )
            self.available = True
        except Exception as exc:
            self.available = False
            self.last_error = f"SQLite initialization warning: {exc}"

    def log_audit_event(
        self,
        username: str,
        role: str,
        action: str,
        target_repo: Optional[str] = None,
        details: Optional[str] = None,
    ) -> bool:
        """Record a security or mentor action in `audit_log`."""
        if not self.available:
            return False
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log (timestamp_utc, username, role, action, target_repo, details)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (now_utc, username, role, action, target_repo, details),
                )
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def get_recent_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent audit events."""
        if not self.available:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (int(limit),)
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception as exc:
            self.last_error = str(exc)
            return []

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
        """Save or update a mentor review evaluation draft in SQLite."""
        if not self.available:
            return False
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO mentor_feedback_drafts (
                        repo_name, review_number, mentor_username, submission_status,
                        mentor_feedback, strengths_json, concerns_json,
                        improvement_areas_json, criteria_scores_json, action_items_json,
                        updated_at_utc, committed_to_github
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
                        updated_at_utc = excluded.updated_at_utc,
                        committed_to_github = excluded.committed_to_github
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
                        now_utc,
                        1 if committed_to_github else 0,
                    ),
                )
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def get_feedback_draft(self, repo_name: str, review_number: int) -> Optional[Dict[str, Any]]:
        """Retrieve a saved mentor feedback draft for `(repo_name, review_number)`."""
        if not self.available:
            return None
        try:
            with self._connect() as conn:
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
                    "updated_at_utc": row["updated_at_utc"],
                    "committed_to_github": bool(row["committed_to_github"]),
                }
        except Exception as exc:
            self.last_error = str(exc)
            return None

    def set_setting(self, key: str, value: Any, updated_by: str = "system") -> bool:
        """Persist a JSON-serializable dashboard setting."""
        if not self.available:
            return False
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO mentor_settings (setting_key, setting_value_json, updated_by, updated_at_utc)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value_json = excluded.setting_value_json,
                        updated_by = excluded.updated_by,
                        updated_at_utc = excluded.updated_at_utc
                    """,
                    (key, json.dumps(value), updated_by, now_utc),
                )
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Retrieve a dashboard setting or return `default`."""
        if not self.available:
            return default
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT setting_value_json FROM mentor_settings WHERE setting_key = ?", (key,)
                ).fetchone()
                if not row:
                    return default
                return json.loads(row["setting_value_json"])
        except Exception:
            return default
