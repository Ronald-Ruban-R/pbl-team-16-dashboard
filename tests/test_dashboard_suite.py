"""
Comprehensive unit and integration test suite for the PBL Cohort-X Mentor Dashboard.

Covers:
1. Progress calculation rules (strict separation from commit counts, zero vs Not Reported vs Malformed,
   evidence verification against repository file tree, milestone weight validation and normalization).
2. JSON schema validation (`metadata.json`, `progress.json`, `timeline.json`, `members.json`,
   `responsibilities.json`, `tasks.json`, `review-1.json`).
3. Repository handling and partial-failure isolation (e.g., `pbl-team-15` inaccessible while the
   remaining 5 teams continue working, custom folder discovery, large file >1MB preview guard,
   rate-limit handling).
4. Security, RBAC access control, PBKDF2-HMAC-SHA256 verification, student repository isolation,
   XSS Markdown sanitization, and credential redaction.
5. Local SQLite mentor storage (`MentorLocalStore`).

Run with either:
    python3 -m unittest discover -s tests -v
or:
    pytest -v
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from datetime import date
from typing import Any, Dict, Optional

from src.analytics import (
    categorize_repository_files,
    compute_milestone_metrics,
    compute_task_metrics,
    evaluate_team_repository,
    is_evidence_verified_in_repo,
)
from src.config import DEFAULT_GITHUB_ORG, DEFAULT_TEAM_REPOS, DashboardConfig
from src.github_client import (
    CommitRecord,
    FileContentResult,
    GitHubAuthProvider,
    GitHubCohortClient,
    RepoFileEntry,
    RepositorySnapshot,
)
from src.security import (
    AccessControlManager,
    AuthenticatedUser,
    AuthorizationError,
    UserRole,
    hash_password_pbkdf2,
    is_safe_external_url,
    redact_secrets,
    sanitize_markdown_for_display,
    verify_password,
)
from src.storage import MentorLocalStore
from src.validators import (
    ValidationState,
    validate_members_data,
    validate_progress_data,
    validate_project_metadata,
    validate_responsibilities_data,
    validate_review_data,
    validate_tasks_data,
    validate_timeline_data,
)


class FakeHTTPResponse:
    """Minimal mock HTTP response for testing `GitHubCohortClient` offline."""

    def __init__(
        self,
        status_code: int,
        json_data: Any = None,
        text: str = "",
        content: bytes = b"",
        headers: Optional[Dict[str, str]] = None,
    ):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text or (json.dumps(json_data) if json_data is not None else "")
        self.content = content or self.text.encode("utf-8")
        self.headers = headers or {
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4985",
            "X-RateLimit-Used": "15",
            "X-RateLimit-Reset": "1999999999",
        }

    def json(self) -> Any:
        if self._json_data is None:
            raise ValueError("No JSON body")
        return self._json_data


class FakeHTTPSession:
    """Deterministic fake `requests.Session` mapping URL substrings to responses."""

    def __init__(self, route_handler):
        self.route_handler = route_handler
        self.calls = []

    def request(self, method: str, url: str, headers=None, params=None, json=None, timeout=None):
        self.calls.append((method, url, params))
        return self.route_handler(method, url, headers, params, json)


class TestSecurityAndAccessControl(unittest.TestCase):
    """Tests for authentication, PBKDF2 hashing, RBAC isolation, and sanitization."""

    def setUp(self) -> None:
        self.owner1_hash = hash_password_pbkdf2("Owner1Secret!2026")
        self.owner2_hash = hash_password_pbkdf2("Owner2Secret!2026")
        self.student13_hash = hash_password_pbkdf2("StudentTeam13Pass!")

        self.secrets_map = {
            "auth": {
                "users": {
                    "owner1": {
                        "display_name": "Org Owner 1",
                        "role": "owner",
                        "password_hash": self.owner1_hash,
                        "allowed_repos": ["*"],
                    },
                    "owner2": {
                        "display_name": "Org Owner 2",
                        "role": "owner",
                        "password_hash": self.owner2_hash,
                        "allowed_repos": list(DEFAULT_TEAM_REPOS),
                    },
                    "student_t13": {
                        "display_name": "Team 13 Lead",
                        "role": "student",
                        "password_hash": self.student13_hash,
                        "allowed_repos": ["pbl-team-13"],
                    },
                    "student_misconfigured_wildcard": {
                        "display_name": "Student With Wildcard Attempt",
                        "role": "student",
                        "password_hash": self.student13_hash,
                        "allowed_repos": ["*"],
                    },
                }
            }
        }
        self.acm = AccessControlManager(
            secrets_map=self.secrets_map,
            configured_repos=list(DEFAULT_TEAM_REPOS),
        )

    def test_pbkdf2_password_hashing_and_verification(self) -> None:
        pw = "CorrectHorseBatteryStaple#99"
        hashed = hash_password_pbkdf2(pw)
        self.assertTrue(hashed.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password(pw, hashed))
        self.assertFalse(verify_password("WrongPassword", hashed))
        self.assertFalse(verify_password("", hashed))

    def test_two_organization_owners_can_access_all_six_repos(self) -> None:
        u1 = self.acm.authenticate("owner1", "Owner1Secret!2026")
        u2 = self.acm.authenticate("owner2", "Owner2Secret!2026")
        self.assertIsNotNone(u1)
        self.assertIsNotNone(u2)
        assert u1 is not None and u2 is not None

        for repo in DEFAULT_TEAM_REPOS:
            self.assertTrue(u1.can_access_repo(repo))
            self.assertTrue(u2.can_access_repo(repo))
            self.acm.authorize_repo_access(u1, repo)
            self.acm.authorize_repo_access(u2, repo)

    def test_student_strictly_restricted_to_single_team_repo(self) -> None:
        student = self.acm.authenticate("student_t13", "StudentTeam13Pass!")
        self.assertIsNotNone(student)
        assert student is not None

        self.assertTrue(student.can_access_repo("pbl-team-13"))
        self.acm.authorize_repo_access(student, "pbl-team-13")
        self.assertFalse(student.can_write_feedback("pbl-team-13"))
        self.assertFalse(student.can_manage_settings())

        for other_repo in ("pbl-team-14", "pbl-team-15", "pbl-team-16", "pbl-team-17", "pbl-team-18"):
            self.assertFalse(student.can_access_repo(other_repo))
            with self.assertRaises(AuthorizationError):
                self.acm.authorize_repo_access(student, other_repo)

    def test_student_cannot_gain_wildcard_access_even_if_misconfigured(self) -> None:
        student_wc = self.acm.authenticate("student_misconfigured_wildcard", "StudentTeam13Pass!")
        self.assertIsNotNone(student_wc)
        assert student_wc is not None
        self.assertFalse(student_wc.can_access_repo("pbl-team-13"))

    def test_markdown_sanitization_strips_xss_vectors(self) -> None:
        malicious_md = (
            "# Project Report\n"
            "<script>alert('xss')</script>\n"
            "<img src=x onerror=\"alert(1)\">\n"
            "[Click Me](javascript:alert('steal_token'))"
        )
        cleaned = sanitize_markdown_for_display(malicious_md)
        self.assertNotIn("<script>", cleaned.lower())
        self.assertNotIn("onerror=", cleaned.lower())
        self.assertNotIn("javascript:", cleaned.lower())
        self.assertIn("# Project Report", cleaned)

    def test_secret_redaction_strips_github_tokens(self) -> None:
        raw_err = "Request failed with header Authorization: Bearer ghp_1234567890abcdefghijklmnopqrstuvwx"
        redacted = redact_secrets(raw_err)
        self.assertNotIn("ghp_1234567890", redacted)
        self.assertIn("[REDACTED_CREDENTIAL]", redacted)

    def test_safe_external_url_validation(self) -> None:
        self.assertTrue(is_safe_external_url("https://github.com/PBL-Cohort-X-Teams-13-18/pbl-team-13"))
        self.assertTrue(is_safe_external_url("docs/architecture.md"))
        self.assertFalse(is_safe_external_url("javascript:alert(1)"))
        self.assertFalse(is_safe_external_url("../../etc/passwd"))


class TestMetadataValidation(unittest.TestCase):
    """Tests for JSON schema validation and missing/malformed handling."""

    def test_valid_project_metadata(self) -> None:
        payload = json.dumps(
            {
                "team_id": "pbl-team-13",
                "team_name": "Team 13 — SolarGrid",
                "project_title": "Microgrid Fault Detection",
                "domain": "Clean Energy",
                "problem_statement": "Detecting inverter anomalies in rural solar microgrids.",
                "objectives": ["Build sensor pipeline", "Train anomaly detector"],
                "expected_outcomes": ["95% detection recall"],
                "start_date": "2026-08-01",
                "target_completion_date": "2026-12-15",
            }
        )
        rep = validate_project_metadata(payload, exists=True)
        self.assertEqual(rep.state, ValidationState.VALID)
        self.assertEqual(rep.parsed_data.team_name, "Team 13 — SolarGrid")

    def test_missing_vs_malformed_metadata(self) -> None:
        missing_rep = validate_project_metadata(None, exists=False)
        self.assertEqual(missing_rep.state, ValidationState.MISSING)

        malformed_syntax = validate_project_metadata("{bad json", exists=True)
        self.assertEqual(malformed_syntax.state, ValidationState.MALFORMED)
        self.assertTrue(any("Invalid JSON syntax" in e for e in malformed_syntax.errors))

        missing_req_field = validate_project_metadata(json.dumps({"team_id": "pbl-team-14"}), exists=True)
        self.assertEqual(missing_req_field.state, ValidationState.MALFORMED)
        self.assertTrue(any("problem_statement" in e for e in missing_req_field.errors))

    def test_validate_tasks_and_reviews(self) -> None:
        bad_tasks = json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "T1",
                        "title": "Valid Title",
                        "status": "InventedInvalidStatus",
                    }
                ]
            }
        )
        t_rep = validate_tasks_data(bad_tasks, exists=True)
        self.assertEqual(t_rep.state, ValidationState.MALFORMED)

        good_review = json.dumps(
            {
                "review_id": "review-1",
                "review_number": 1,
                "review_name": "Review 1",
                "submission_status": "Reviewed",
                "criteria_scores": [
                    {"criterion": "Problem Clarity", "max_score": 25, "awarded_score": 22.5}
                ],
                "action_items": [
                    {
                        "action_id": "AI-1",
                        "description": "Add benchmark dataset comparison",
                        "assigned_to": "Aarav",
                        "due_date": "2026-10-01",
                        "status": "In Progress",
                    }
                ],
            }
        )
        r_rep = validate_review_data(good_review, exists=True)
        self.assertEqual(r_rep.state, ValidationState.VALID)
        self.assertEqual(r_rep.parsed_data.review_number, 1)
        self.assertEqual(len(r_rep.parsed_data.action_items), 1)


class TestProgressCalculationsAndErrorIsolation(unittest.TestCase):
    """Tests for progress calculations, commit non-inference, and repository failure isolation."""

    def test_commits_never_infer_completion_when_progress_missing(self) -> None:
        """
        Even if a repository has 50 recent commits and many source files, if `progress.json`
        and `tasks.json` are missing, progress MUST be 'Not Reported' (None), never a guessed %.
        """
        cfg = DashboardConfig()
        snap = RepositorySnapshot(
            org=DEFAULT_GITHUB_ORG,
            repo_name="pbl-team-13",
            accessible=True,
            status_code=200,
            tree_entries=[
                RepoFileEntry(name="main.py", path="src/main.py", item_type="file", size=1200),
                RepoFileEntry(name="paper.pdf", path="research/paper.pdf", item_type="file", size=54000),
            ],
            recent_commits=[
                CommitRecord(
                    sha=f"sha{i}",
                    short_sha=f"sha{i}",
                    message="feat: add code",
                    author_name="Student",
                    author_login="student",
                    committed_date="2026-10-14T10:00:00Z",
                    html_url="https://github.com/...",
                )
                for i in range(20)
            ],
            convention_raw_files={},
        )
        summary = evaluate_team_repository(snap, cfg, reference_date=date(2026, 10, 15))
        self.assertIsNone(summary.hybrid_progress_pct)
        self.assertEqual(summary.progress_display_status, "Not Reported")
        self.assertEqual(summary.task_metrics.status_label, "Not Reported")
        self.assertIsNone(summary.task_metrics.reported_completion_pct)

    def test_zero_percent_progress_distinguished_from_not_reported(self) -> None:
        """When tasks exist and 0 are completed, completion is explicitly 0.0%, not 'Not Reported'."""
        tasks_json = json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "T-1",
                        "title": "Design schema",
                        "description": "Initial schema",
                        "assigned_to": "Priya",
                        "priority": "High",
                        "status": "In Progress",
                        "due_date": "2026-10-01",
                        "evidence_link": "documentation/schema.md",
                        "weight": 1.0,
                    }
                ]
            }
        )
        t_rep = validate_tasks_data(tasks_json, exists=True)
        metrics = compute_task_metrics(
            t_rep.parsed_data,
            t_rep,
            repo_accessible=True,
            repo_file_paths_lower={"documentation/schema.md"},
            reference_date=date(2026, 10, 15),
        )
        self.assertEqual(metrics.status_label, "Reported")
        self.assertEqual(metrics.reported_completion_pct, 0.0)
        self.assertEqual(metrics.verified_completion_pct, 0.0)
        self.assertEqual(metrics.overdue_tasks, 1)

    def test_hybrid_evidence_verification_checks_actual_repo_tree(self) -> None:
        """
        If 2 equal-weight tasks are marked Completed, but only 1 has an `evidence_link`
        that actually exists in the repository tree, `reported_completion_pct` is 100.0%
        while `verified_completion_pct` is 50.0%.
        """
        tasks_json = json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "T-1",
                        "title": "Verified Task",
                        "description": "",
                        "assigned_to": "Member A",
                        "priority": "High",
                        "status": "Completed",
                        "evidence_link": "research/lit_review.md",
                        "weight": 1.0,
                    },
                    {
                        "task_id": "T-2",
                        "title": "Unverified Task (File Missing in Repo)",
                        "description": "",
                        "assigned_to": "Member B",
                        "priority": "High",
                        "status": "Completed",
                        "evidence_link": "deliverables/non_existent_report.pdf",
                        "weight": 1.0,
                    },
                ]
            }
        )
        t_rep = validate_tasks_data(tasks_json, exists=True)
        repo_paths = {"research/lit_review.md", "readme.md"}
        metrics = compute_task_metrics(
            t_rep.parsed_data,
            t_rep,
            repo_accessible=True,
            repo_file_paths_lower=repo_paths,
            reference_date=date(2026, 10, 15),
        )
        self.assertEqual(metrics.reported_completion_pct, 100.0)
        self.assertEqual(metrics.verified_completion_pct, 50.0)

    def test_milestone_weights_validation_and_normalization(self) -> None:
        prog_json = json.dumps(
            {
                "last_updated": "2026-10-12",
                "current_phase": "Prototype",
                "overall_reported_pct": 50.0,
                "summary": "In progress",
                "milestones": [
                    {
                        "milestone_id": "M1",
                        "title": "Phase 1",
                        "status": "Completed",
                        "weight": 40.0,
                        "completion_pct": 100.0,
                        "evidence_path": "research/notes.md",
                    },
                    {
                        "milestone_id": "M2",
                        "title": "Phase 2",
                        "status": "Not Started",
                        "weight": 40.0,
                        "completion_pct": 0.0,
                    },
                ],
            }
        )
        p_rep = validate_progress_data(prog_json, exists=True)
        m_summary = compute_milestone_metrics(
            p_rep.parsed_data,
            p_rep,
            repo_accessible=True,
            repo_file_paths_lower={"research/notes.md"},
        )
        self.assertFalse(m_summary.weights_valid_100)
        self.assertEqual(m_summary.raw_weight_sum, 80.0)
        self.assertEqual(m_summary.weighted_completion_pct, 50.0)
        self.assertIsNotNone(m_summary.weight_warning)

    def test_team_15_failure_isolation_does_not_break_other_five_teams(self) -> None:
        """
        Verify Section 11 requirement:
        If `pbl-team-15` cannot be accessed (HTTP 404/403), the other five teams
        remain accessible and evaluated cleanly.
        """
        def route_handler(method, url, headers, params, json_body):
            if "/repos/PBL-Cohort-X-Teams-13-18/pbl-team-15" in url:
                return FakeHTTPResponse(404, {"message": "Not Found"})
            if "/git/trees/" in url:
                return FakeHTTPResponse(
                    200,
                    {
                        "truncated": False,
                        "tree": [
                            {"path": "README.md", "type": "blob", "size": 120, "sha": "abc1"},
                            {"path": "custom_robotics_cad", "type": "tree", "size": 0, "sha": "abc2"},
                            {"path": "custom_robotics_cad/chassis.step", "type": "blob", "size": 4096, "sha": "abc3"},
                        ],
                    },
                )
            if "/commits" in url:
                return FakeHTTPResponse(200, [])
            if "/contents/README.md" in url:
                b64 = base64.b64encode(b"# Team Repo\n").decode("ascii")
                return FakeHTTPResponse(
                    200,
                    {"name": "README.md", "path": "README.md", "size": 12, "sha": "abc1", "encoding": "base64", "content": b64},
                )
            if "/repos/PBL-Cohort-X-Teams-13-18/pbl-team-" in url:
                repo_name = url.rsplit("/", 1)[-1]
                return FakeHTTPResponse(
                    200,
                    {
                        "name": repo_name,
                        "private": True,
                        "default_branch": "main",
                        "html_url": f"https://github.com/PBL-Cohort-X-Teams-13-18/{repo_name}",
                        "pushed_at": "2026-10-14T08:00:00Z",
                    },
                )
            return FakeHTTPResponse(404, {"message": "Not Found"})

        cfg = DashboardConfig()
        auth = GitHubAuthProvider(token="github_pat_fake_test_token_12345678901234567890")
        client = GitHubCohortClient(config=cfg, auth_provider=auth, session=FakeHTTPSession(route_handler))

        evaluations = {}
        for repo in cfg.team_repos:
            snap = client.fetch_repository_snapshot(repo)
            evaluations[repo] = evaluate_team_repository(snap, cfg)

        self.assertFalse(evaluations["pbl-team-15"].snapshot.accessible)
        self.assertEqual(evaluations["pbl-team-15"].attention_level, "Unavailable")

        for healthy_repo in ("pbl-team-13", "pbl-team-14", "pbl-team-16", "pbl-team-17", "pbl-team-18"):
            self.assertTrue(evaluations[healthy_repo].snapshot.accessible)
            self.assertIn("custom_robotics_cad", evaluations[healthy_repo].custom_top_folders)


class TestSQLiteLocalStore(unittest.TestCase):
    """Tests for `MentorLocalStore` draft persistence, settings, and audit logging."""

    def test_feedback_draft_and_audit_log_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_mentor.db")
            store = MentorLocalStore(db_path=db_path)
            self.assertTrue(store.available)

            ok = store.save_feedback_draft(
                repo_name="pbl-team-14",
                review_number=2,
                mentor_username="owner1",
                submission_status="Reviewed",
                mentor_feedback="Strong prototype architecture.",
                strengths=["Clean modular Python code"],
                concerns=["Dataset size is small"],
                improvement_areas=["Expand validation set before Review 3"],
                criteria_scores=[{"criterion": "Architecture", "max_score": 25.0, "awarded_score": 23.0}],
                action_items=[{"action_id": "AI-2-1", "description": "Collect 500 more samples", "status": "In Progress"}],
            )
            self.assertTrue(ok)

            draft = store.get_feedback_draft("pbl-team-14", 2)
            self.assertIsNotNone(draft)
            assert draft is not None
            self.assertEqual(draft["submission_status"], "Reviewed")
            self.assertEqual(draft["mentor_feedback"], "Strong prototype architecture.")

            store.log_audit_event("owner1", "owner", "save_review_feedback", "pbl-team-14", "Saved Review 2")
            logs = store.get_recent_audit_logs(limit=10)
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["target_repo"], "pbl-team-14")


if __name__ == "__main__":
    unittest.main()
