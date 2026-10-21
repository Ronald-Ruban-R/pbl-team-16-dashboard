"""
Central configuration for the PBL Team 16 Dedicated Dashboard (`pbl-team-16`).

Configured specifically for `PBL-Cohort-X-Teams-13-18/pbl-team-16` with two-way
GitHub JSON synchronization so updates made in the Team 16 Dashboard are immediately
reflected in both the Team 16 Dashboard and the 6-Team Mentor Dashboard.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_GITHUB_ORG: str = "PBL-Cohort-X-Teams-13-18"

DEFAULT_TEAM_REPOS: Tuple[str, ...] = ("pbl-team-16",)

CONVENTION_FILES: Dict[str, str] = {
    "readme": "README.md",
    "metadata": "project/metadata.json",
    "progress": "project/progress.json",
    "timeline": "project/timeline.json",
    "members": "team/members.json",
    "responsibilities": "team/responsibilities.json",
    "tasks": "tasks/tasks.json",
    "review_1": "reviews/review-1.json",
    "review_2": "reviews/review-2.json",
    "review_3": "reviews/review-3.json",
    "review_4": "reviews/review-4.json",
}

RECOMMENDED_CATEGORY_FOLDERS: Dict[str, Tuple[str, ...]] = {
    "Research & Literature": ("research", "literature", "papers", "references"),
    "Technical Documentation": ("documentation", "docs", "architecture", "specs", "design"),
    "Datasets & Experiments": ("datasets", "data", "experiments", "notebooks", "results"),
    "Competitions & Achievements": ("competitions", "hackathons", "awards", "certificates"),
    "Meeting Notes & Reports": ("meeting-notes", "meetings", "notes", "reports", "minutes"),
    "Deliverables & Releases": ("deliverables", "submissions", "presentations", "prototypes"),
    "Project Management": ("project", "team", "tasks", "reviews"),
}

PREVIEWABLE_TEXT_EXTENSIONS: Tuple[str, ...] = (
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".r",
    ".ipynb",
    ".xml",
    ".ini",
    ".cfg",
)

PREVIEWABLE_IMAGE_EXTENSIONS: Tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
)

PREVIEWABLE_PDF_EXTENSIONS: Tuple[str, ...] = (".pdf",)

MAX_PREVIEW_FILE_BYTES: int = 1_000_000


def to_plain_dict(obj: Any) -> Any:
    """Recursively convert Streamlit `AttrDict` / `Mapping` objects into standard Python `dict`s."""
    if isinstance(obj, Mapping):
        return {str(k): to_plain_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain_dict(x) for x in obj]
    return obj


@dataclass(frozen=True)
class ReviewDefinition:
    """Configuration for a cohort review stage."""

    review_id: str
    review_number: int
    title: str
    default_file_path: str
    default_weight: float
    required_deliverables: Tuple[str, ...] = field(default_factory=tuple)


DEFAULT_REVIEWS: Tuple[ReviewDefinition, ...] = (
    ReviewDefinition(
        review_id="review-1",
        review_number=1,
        title="Review 1: Problem Definition & Literature Survey",
        default_file_path="reviews/review-1.json",
        default_weight=20.0,
        required_deliverables=(
            "Problem Statement & Stakeholder Analysis",
            "Literature Review Summary (research/)",
            "Team Roles & Responsibility Matrix (team/responsibilities.json)",
            "Initial Project Timeline (project/timeline.json)",
        ),
    ),
    ReviewDefinition(
        review_id="review-2",
        review_number=2,
        title="Review 2: System Architecture & Prototype Design",
        default_file_path="reviews/review-2.json",
        default_weight=25.0,
        required_deliverables=(
            "System Architecture & Technical Specification",
            "Dataset / Experimental Setup Documentation",
            "Initial Prototype / Proof of Concept",
            "Updated Task Tracker (tasks/tasks.json)",
        ),
    ),
    ReviewDefinition(
        review_id="review-3",
        review_number=3,
        title="Review 3: Core Implementation, Experiments & Validation",
        default_file_path="reviews/review-3.json",
        default_weight=30.0,
        required_deliverables=(
            "Integrated Prototype / Core Implementation",
            "Experimental Validation & Test Results",
            "Competition / External Evaluation Entry",
            "Resolution of Review 2 Action Items",
        ),
    ),
    ReviewDefinition(
        review_id="review-4",
        review_number=4,
        title="Review 4: Final Demonstration, Documentation & Handover",
        default_file_path="reviews/review-4.json",
        default_weight=25.0,
        required_deliverables=(
            "Final Technical Report & User Documentation",
            "Final Presentation Deck & Demo Evidence",
            "Complete Verified Deliverable Package",
            "Resolution of All Prior Review Action Items",
        ),
    ),
)


@dataclass
class DashboardConfig:
    """Runtime configuration for the Team 16 Dashboard."""

    github_org: str = DEFAULT_GITHUB_ORG
    team_repos: List[str] = field(default_factory=lambda: list(DEFAULT_TEAM_REPOS))
    github_api_base_url: str = "https://api.github.com"
    api_timeout_seconds: int = 15
    max_retries: int = 3
    cache_ttl_seconds: int = 120
    stale_progress_days: int = 10
    stale_repo_commit_days: int = 14
    sqlite_db_path: str = "data/team16_dashboard.db"
    enable_github_writeback: bool = True
    reviews: List[ReviewDefinition] = field(default_factory=lambda: list(DEFAULT_REVIEWS))

    @classmethod
    def from_mapping(cls, secrets_map: Optional[Mapping] = None) -> "DashboardConfig":
        plain = to_plain_dict(secrets_map) if secrets_map is not None else {}
        if not isinstance(plain, dict):
            plain = {}
        gh_section = plain.get("github", {}) if isinstance(plain.get("github"), Mapping) else {}
        app_section = plain.get("dashboard", {}) if isinstance(plain.get("dashboard"), Mapping) else {}

        org = (
            gh_section.get("organization")
            or os.environ.get("PBL_GITHUB_ORG")
            or DEFAULT_GITHUB_ORG
        )
        repos_raw = gh_section.get("repositories") or os.environ.get("PBL_TEAM_REPOS")
        if isinstance(repos_raw, str):
            repos = [r.strip() for r in repos_raw.split(",") if r.strip()]
        elif isinstance(repos_raw, (list, tuple)):
            repos = [str(r).strip() for r in repos_raw if str(r).strip()]
        else:
            repos = list(DEFAULT_TEAM_REPOS)

        api_base = (
            gh_section.get("api_base_url")
            or os.environ.get("PBL_GITHUB_API_URL")
            or "https://api.github.com"
        )
        timeout = int(
            gh_section.get("timeout_seconds")
            or os.environ.get("PBL_GITHUB_TIMEOUT", 15)
        )
        max_retries = int(
            gh_section.get("max_retries")
            or os.environ.get("PBL_GITHUB_MAX_RETRIES", 3)
        )
        cache_ttl = int(
            app_section.get("cache_ttl_seconds")
            or os.environ.get("PBL_CACHE_TTL_SECONDS", 120)
        )
        stale_progress_days = int(
            app_section.get("stale_progress_days")
            or os.environ.get("PBL_STALE_PROGRESS_DAYS", 10)
        )
        stale_commit_days = int(
            app_section.get("stale_repo_commit_days")
            or os.environ.get("PBL_STALE_COMMIT_DAYS", 14)
        )
        db_path = (
            app_section.get("sqlite_db_path")
            or os.environ.get("PBL_SQLITE_DB_PATH")
            or "data/team16_dashboard.db"
        )
        writeback_raw = app_section.get(
            "enable_github_writeback",
            os.environ.get("PBL_ENABLE_GITHUB_WRITEBACK", "true"),
        )
        enable_writeback = str(writeback_raw).lower() in ("1", "true", "yes")

        return cls(
            github_org=org,
            team_repos=repos,
            github_api_base_url=api_base.rstrip("/"),
            api_timeout_seconds=timeout,
            max_retries=max_retries,
            cache_ttl_seconds=cache_ttl,
            stale_progress_days=stale_progress_days,
            stale_repo_commit_days=stale_commit_days,
            sqlite_db_path=db_path,
            enable_github_writeback=enable_writeback,
        )
