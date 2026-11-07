"""
Schema Validation, Resilient Parsing, and Placeholder Sanitization Module.

Ensures:
- Malformed or incomplete JSON files never crash the dashboard.
- Angle-bracket template placeholders (such as `<TEAM_DISPLAY_NAME>`,
  `<TECHNICAL_OR_SOCIAL_IMPACT_DOMAIN>`, `<PROJECT_TITLE>`, `<MEMBER_FULL_NAME>`, etc.)
  are automatically stripped and replaced with clean, human-readable defaults so raw
  template placeholders never appear in the production dashboard.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.config import format_repo_display_name


VALID_TASK_STATUSES: Tuple[str, ...] = (
    "Not Started",
    "In Progress",
    "Completed",
    "Blocked",
    "Delayed",
)

VALID_TASK_PRIORITIES: Tuple[str, ...] = (
    "Low",
    "Medium",
    "High",
    "Critical",
)

VALID_SUBMISSION_STATUSES: Tuple[str, ...] = (
    "Not Submitted",
    "Submitted",
    "Needs Revision",
    "Approved",
)

VALID_TIMELINE_TYPES: Tuple[str, ...] = (
    "Milestone",
    "Review",
    "Deliverable",
    "Sprint",
    "External",
)

# Regex matching angle-bracket template placeholders like `<TEAM_DISPLAY_NAME>` or `<TECHNICAL_OR_SOCIAL_IMPACT_DOMAIN>`
_PLACEHOLDER_TOKEN_RE = re.compile(r"^<[^<>]+>$")
_EMBEDDED_PLACEHOLDER_RE = re.compile(r"<[A-Z0-9_/\-\s]{3,}>")


def is_placeholder_string(value: Any) -> bool:
    """Return True if `value` is an unedited template placeholder like `<TEAM_DISPLAY_NAME>`."""
    if value is None:
        return True
    s = str(value).strip()
    if not s:
        return True
    if _PLACEHOLDER_TOKEN_RE.match(s):
        return True
    if _EMBEDDED_PLACEHOLDER_RE.search(s):
        return True
    upper = s.upper()
    if upper in (
        "TEAM_DISPLAY_NAME",
        "TECHNICAL_OR_SOCIAL_IMPACT_DOMAIN",
        "PROJECT_TITLE",
        "CLEAR_PROBLEM_STATEMENT_2_TO_4_SENTENCES",
        "LEAD_MENTOR_NAME",
        "CO_MENTOR_NAME",
        "MEMBER_FULL_NAME",
        "GITHUB_USERNAME",
        "DEGREE_OR_DISCIPLINE",
        "EMAIL_ADDRESS",
    ):
        return True
    return False


def clean_placeholder_str(value: Any, default: str = "") -> str:
    """Return `default` if `value` is empty or contains a template placeholder like `<...>`."""
    if is_placeholder_string(value):
        return default
    return str(value).strip()


def clean_placeholder_list(items: Any) -> List[str]:
    """Filter a list of strings, removing empty items and any `<...>` template placeholders."""
    if not isinstance(items, list):
        return []
    cleaned: List[str] = []
    for item in items:
        val = clean_placeholder_str(item, default="")
        if val:
            cleaned.append(val)
    return cleaned


@dataclass
class ValidationIssue:
    """Represents a non-fatal validation warning or error for a repository file."""

    file_path: str
    severity: str  # "warning" or "error"
    message: str


@dataclass
class ProjectMetadata:
    team_id: str
    team_name: str
    project_title: str
    domain: str
    problem_statement: str
    objectives: List[str] = field(default_factory=list)
    expected_outcomes: List[str] = field(default_factory=list)
    start_date: Optional[str] = None
    target_completion_date: Optional[str] = None
    lead_mentor: str = ""
    co_mentor: str = ""
    tags: List[str] = field(default_factory=list)


@dataclass
class TeamMember:
    member_id: str
    name: str
    github_username: str = ""
    role: str = "Member"
    discipline: str = ""
    email: str = ""
    skills: List[str] = field(default_factory=list)


@dataclass
class ResponsibilityRecord:
    member_id: str
    name: str
    primary_area: str
    responsibilities: List[str] = field(default_factory=list)
    owned_deliverables: List[str] = field(default_factory=list)
    backup_owner: str = ""


@dataclass
class MilestoneProgress:
    milestone_id: str
    title: str
    status: str = "Not Started"
    weight: float = 25.0
    completion_pct: float = 0.0
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    evidence_path: Optional[str] = None


@dataclass
class ProgressRecord:
    last_updated: Optional[str] = None
    current_phase: str = "Not Reported"
    overall_reported_pct: Optional[float] = None
    summary: str = ""
    accomplishments_since_last_update: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    milestones: List[MilestoneProgress] = field(default_factory=list)


@dataclass
class TimelineEvent:
    event_id: str
    title: str
    event_type: str = "Milestone"
    planned_date: Optional[str] = None
    actual_date: Optional[str] = None
    status: str = "Not Started"
    description: str = ""
    owner: str = ""


@dataclass
class TaskItem:
    task_id: str
    title: str
    description: str = ""
    assigned_to: str = "Unassigned"
    priority: str = "Medium"
    status: str = "Not Started"
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    related_milestone: Optional[str] = None
    related_review: Optional[int] = None
    evidence_link: Optional[str] = None
    last_updated: Optional[str] = None
    weight: float = 1.0


@dataclass
class DeliverableItem:
    title: str
    required: bool = True
    submitted: bool = False
    artifact_path: Optional[str] = None
    notes: str = ""


@dataclass
class CriterionScore:
    criterion: str
    max_score: float = 10.0
    awarded_score: Optional[float] = None
    comments: str = ""


@dataclass
class ActionItemRecord:
    action_id: str
    description: str
    assigned_to: str = "Unassigned"
    due_date: Optional[str] = None
    status: str = "Not Started"
    resolution_evidence: Optional[str] = None
    completed_date: Optional[str] = None


@dataclass
class ReviewRecord:
    review_id: str
    review_number: int
    review_name: str
    scheduled_date: Optional[str] = None
    submission_deadline: Optional[str] = None
    submitted_at: Optional[str] = None
    submission_status: str = "Not Submitted"
    deliverables: List[DeliverableItem] = field(default_factory=list)
    evidence_links: Dict[str, str] = field(default_factory=dict)
    mentor_feedback: str = ""
    criteria_scores: List[CriterionScore] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    improvement_areas: List[str] = field(default_factory=list)
    action_items: List[ActionItemRecord] = field(default_factory=list)


def _safe_load_json(raw_text: Optional[str], file_path: str) -> Tuple[Optional[Any], List[ValidationIssue]]:
    issues: List[ValidationIssue] = []
    if raw_text is None or not raw_text.strip():
        issues.append(ValidationIssue(file_path, "warning", "File is empty."))
        return None, issues
    try:
        return json.loads(raw_text), issues
    except json.JSONDecodeError as exc:
        issues.append(
            ValidationIssue(
                file_path,
                "error",
                f"Malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            )
        )
        return None, issues


def parse_project_metadata(
    raw_text: Optional[str],
    repo_name: str,
    file_path: str = "project/metadata.json",
) -> Tuple[Optional[ProjectMetadata], List[ValidationIssue]]:
    """Parse `project/metadata.json` and sanitize any `<...>` template placeholders."""
    data, issues = _safe_load_json(raw_text, file_path)
    if not isinstance(data, dict):
        if data is not None:
            issues.append(ValidationIssue(file_path, "error", "Root element must be a JSON object."))
        return None, issues

    fallback_team_name = format_repo_display_name(repo_name)
    raw_team_name = data.get("team_name")
    raw_domain = data.get("domain")
    raw_title = data.get("project_title")

    if is_placeholder_string(raw_team_name) or is_placeholder_string(raw_domain) or is_placeholder_string(raw_title):
        issues.append(
            ValidationIssue(
                file_path,
                "warning",
                "Contains unedited starter template placeholders; displaying clean default labels until updated.",
            )
        )

    team_id = clean_placeholder_str(data.get("team_id"), default=repo_name)
    team_name = clean_placeholder_str(raw_team_name, default=fallback_team_name)
    project_title = clean_placeholder_str(raw_title, default=f"{fallback_team_name} Project")
    domain = clean_placeholder_str(raw_domain, default="General Engineering & Innovation")
    problem_statement = clean_placeholder_str(
        data.get("problem_statement"),
        default="Problem statement not yet submitted.",
    )
    objectives = clean_placeholder_list(data.get("objectives", []))
    expected_outcomes = clean_placeholder_list(data.get("expected_outcomes", []))
    start_date = clean_placeholder_str(data.get("start_date"), default="") or None
    target_date = clean_placeholder_str(data.get("target_completion_date"), default="") or None
    lead_mentor = clean_placeholder_str(data.get("lead_mentor"), default="")
    co_mentor = clean_placeholder_str(data.get("co_mentor"), default="")
    tags = clean_placeholder_list(data.get("tags", []))

    return (
        ProjectMetadata(
            team_id=team_id,
            team_name=team_name,
            project_title=project_title,
            domain=domain,
            problem_statement=problem_statement,
            objectives=objectives,
            expected_outcomes=expected_outcomes,
            start_date=start_date,
            target_completion_date=target_date,
            lead_mentor=lead_mentor,
            co_mentor=co_mentor,
            tags=tags,
        ),
        issues,
    )


def parse_team_members(
    raw_text: Optional[str],
    file_path: str = "team/members.json",
) -> Tuple[List[TeamMember], List[ValidationIssue]]:
    """Parse `team/members.json` and filter out unedited `<MEMBER_FULL_NAME>` template rows."""
    data, issues = _safe_load_json(raw_text, file_path)
    if data is None:
        return [], issues

    raw_list = data.get("members", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`members` must be a list of member objects."))
        return [], issues

    members: List[TeamMember] = []
    skipped_placeholders = 0
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        name = clean_placeholder_str(item.get("name"), default="")
        if not name:
            skipped_placeholders += 1
            continue
        member_id = clean_placeholder_str(item.get("member_id"), default=f"M{idx}")
        gh_user = clean_placeholder_str(item.get("github_username"), default="")
        role = clean_placeholder_str(item.get("role"), default="Team Member")
        discipline = clean_placeholder_str(item.get("discipline"), default="")
        email = clean_placeholder_str(item.get("email"), default="")
        skills = clean_placeholder_list(item.get("skills", []))
        members.append(
            TeamMember(
                member_id=member_id,
                name=name,
                github_username=gh_user,
                role=role,
                discipline=discipline,
                email=email,
                skills=skills,
            )
        )

    if skipped_placeholders > 0 and not members:
        issues.append(
            ValidationIssue(
                file_path,
                "warning",
                "Team roster still contains unedited template placeholders (`<MEMBER_FULL_NAME>`).",
            )
        )
    return members, issues


def parse_responsibilities(
    raw_text: Optional[str],
    file_path: str = "team/responsibilities.json",
) -> Tuple[List[ResponsibilityRecord], List[ValidationIssue]]:
    """Parse `team/responsibilities.json` and strip `<...>` template placeholders."""
    data, issues = _safe_load_json(raw_text, file_path)
    if data is None:
        return [], issues

    raw_list = (
        data.get("responsibilities", [])
        if isinstance(data, dict)
        else (data if isinstance(data, list) else [])
    )
    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`responsibilities` must be a list."))
        return [], issues

    records: List[ResponsibilityRecord] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        name = clean_placeholder_str(item.get("name"), default="")
        primary_area = clean_placeholder_str(item.get("primary_area"), default="")
        if not name and not primary_area:
            continue
        records.append(
            ResponsibilityRecord(
                member_id=clean_placeholder_str(item.get("member_id"), default=f"M{idx}"),
                name=name or f"Member {idx}",
                primary_area=primary_area or "General Project Tasks",
                responsibilities=clean_placeholder_list(item.get("responsibilities", [])),
                owned_deliverables=clean_placeholder_list(item.get("owned_deliverables", [])),
                backup_owner=clean_placeholder_str(item.get("backup_owner"), default=""),
            )
        )
    return records, issues


def parse_progress(
    raw_text: Optional[str],
    file_path: str = "project/progress.json",
) -> Tuple[Optional[ProgressRecord], List[ValidationIssue]]:
    """Parse `project/progress.json` and sanitize placeholders."""
    data, issues = _safe_load_json(raw_text, file_path)
    if not isinstance(data, dict):
        if data is not None:
            issues.append(ValidationIssue(file_path, "error", "Root element must be a JSON object."))
        return None, issues

    rep_pct_raw = data.get("overall_reported_pct")
    rep_pct: Optional[float] = None
    if rep_pct_raw is not None:
        try:
            rep_pct = max(0.0, min(100.0, float(rep_pct_raw)))
        except (TypeError, ValueError):
            issues.append(ValidationIssue(file_path, "warning", "Invalid `overall_reported_pct`; expected 0–100."))

    milestones: List[MilestoneProgress] = []
    raw_ms = data.get("milestones", [])
    if isinstance(raw_ms, list):
        for idx, m in enumerate(raw_ms, start=1):
            if not isinstance(m, dict):
                continue
            status_val = clean_placeholder_str(m.get("status"), default="Not Started")
            if status_val not in VALID_TASK_STATUSES:
                status_val = "Not Started"
            try:
                weight_val = max(0.0, float(m.get("weight", 25.0)))
            except (TypeError, ValueError):
                weight_val = 25.0
            try:
                comp_val = max(0.0, min(100.0, float(m.get("completion_pct", 0.0))))
            except (TypeError, ValueError):
                comp_val = 100.0 if status_val == "Completed" else 0.0

            milestones.append(
                MilestoneProgress(
                    milestone_id=clean_placeholder_str(m.get("milestone_id"), default=f"M{idx}"),
                    title=clean_placeholder_str(m.get("title"), default=f"Milestone {idx}"),
                    status=status_val,
                    weight=weight_val,
                    completion_pct=comp_val,
                    due_date=clean_placeholder_str(m.get("due_date"), default="") or None,
                    completed_date=clean_placeholder_str(m.get("completed_date"), default="") or None,
                    evidence_path=clean_placeholder_str(m.get("evidence_path"), default="") or None,
                )
            )

    return (
        ProgressRecord(
            last_updated=clean_placeholder_str(data.get("last_updated"), default="") or None,
            current_phase=clean_placeholder_str(data.get("current_phase"), default="In Progress"),
            overall_reported_pct=rep_pct,
            summary=clean_placeholder_str(data.get("summary"), default=""),
            accomplishments_since_last_update=clean_placeholder_list(
                data.get("accomplishments_since_last_update", [])
            ),
            blockers=clean_placeholder_list(data.get("blockers", [])),
            next_steps=clean_placeholder_list(data.get("next_steps", [])),
            milestones=milestones,
        ),
        issues,
    )


def parse_timeline(
    raw_text: Optional[str],
    file_path: str = "project/timeline.json",
) -> Tuple[List[TimelineEvent], List[ValidationIssue]]:
    """Parse `project/timeline.json` and sanitize placeholders."""
    data, issues = _safe_load_json(raw_text, file_path)
    if data is None:
        return [], issues

    raw_list = data.get("events", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`events` must be a list."))
        return [], issues

    events: List[TimelineEvent] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        title = clean_placeholder_str(item.get("title"), default="")
        if not title:
            continue
        status_val = clean_placeholder_str(item.get("status"), default="Not Started")
        if status_val not in VALID_TASK_STATUSES:
            status_val = "Not Started"
        etype = clean_placeholder_str(item.get("event_type"), default="Milestone")
        if etype not in VALID_TIMELINE_TYPES:
            etype = "Milestone"
        events.append(
            TimelineEvent(
                event_id=clean_placeholder_str(item.get("event_id"), default=f"E{idx}"),
                title=title,
                event_type=etype,
                planned_date=clean_placeholder_str(item.get("planned_date"), default="") or None,
                actual_date=clean_placeholder_str(item.get("actual_date"), default="") or None,
                status=status_val,
                description=clean_placeholder_str(item.get("description"), default=""),
                owner=clean_placeholder_str(item.get("owner"), default=""),
            )
        )
    return events, issues


def parse_tasks(
    raw_text: Optional[str],
    file_path: str = "tasks/tasks.json",
) -> Tuple[List[TaskItem], List[ValidationIssue]]:
    """Parse `tasks/tasks.json` and sanitize placeholders."""
    data, issues = _safe_load_json(raw_text, file_path)
    if data is None:
        return [], issues

    raw_list = data.get("tasks", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`tasks` must be a list."))
        return [], issues

    tasks: List[TaskItem] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        title = clean_placeholder_str(item.get("title"), default="")
        if not title:
            continue
        status_val = clean_placeholder_str(item.get("status"), default="Not Started")
        if status_val not in VALID_TASK_STATUSES:
            status_val = "Not Started"
        prio_val = clean_placeholder_str(item.get("priority"), default="Medium")
        if prio_val not in VALID_TASK_PRIORITIES:
            prio_val = "Medium"
        try:
            weight_val = max(0.1, float(item.get("weight", 1.0)))
        except (TypeError, ValueError):
            weight_val = 1.0
        rel_rev = item.get("related_review")
        try:
            rel_rev_int = int(rel_rev) if rel_rev is not None else None
        except (TypeError, ValueError):
            rel_rev_int = None

        tasks.append(
            TaskItem(
                task_id=clean_placeholder_str(item.get("task_id"), default=f"T-{100 + idx}"),
                title=title,
                description=clean_placeholder_str(item.get("description"), default=""),
                assigned_to=clean_placeholder_str(item.get("assigned_to"), default="Unassigned"),
                priority=prio_val,
                status=status_val,
                start_date=clean_placeholder_str(item.get("start_date"), default="") or None,
                due_date=clean_placeholder_str(item.get("due_date"), default="") or None,
                completed_date=clean_placeholder_str(item.get("completed_date"), default="") or None,
                related_milestone=clean_placeholder_str(item.get("related_milestone"), default="") or None,
                related_review=rel_rev_int,
                evidence_link=clean_placeholder_str(item.get("evidence_link"), default="") or None,
                last_updated=clean_placeholder_str(item.get("last_updated"), default="") or None,
                weight=weight_val,
            )
        )
    return tasks, issues


def parse_review(
    raw_text: Optional[str],
    default_review_number: int = 1,
    file_path: str = "reviews/review-1.json",
) -> Tuple[Optional[ReviewRecord], List[ValidationIssue]]:
    """Parse `reviews/review-N.json` and sanitize placeholders."""
    data, issues = _safe_load_json(raw_text, file_path)
    if not isinstance(data, dict):
        if data is not None:
            issues.append(ValidationIssue(file_path, "error", "Root element must be a JSON object."))
        return None, issues

    try:
        rev_num = int(data.get("review_number", default_review_number))
    except (TypeError, ValueError):
        rev_num = default_review_number

    sub_status = clean_placeholder_str(data.get("submission_status"), default="Not Submitted")
    if sub_status not in VALID_SUBMISSION_STATUSES:
        sub_status = "Not Submitted"

    deliverables: List[DeliverableItem] = []
    for d in data.get("deliverables", []) if isinstance(data.get("deliverables"), list) else []:
        if not isinstance(d, dict):
            continue
        d_title = clean_placeholder_str(d.get("title"), default="")
        if not d_title:
            continue
        deliverables.append(
            DeliverableItem(
                title=d_title,
                required=bool(d.get("required", True)),
                submitted=bool(d.get("submitted", False)),
                artifact_path=clean_placeholder_str(d.get("artifact_path"), default="") or None,
                notes=clean_placeholder_str(d.get("notes"), default=""),
            )
        )

    evidence_links: Dict[str, str] = {}
    raw_ev = data.get("evidence_links")
    if isinstance(raw_ev, dict):
        for k, v in raw_ev.items():
            cleaned_v = clean_placeholder_str(v, default="")
            if cleaned_v:
                evidence_links[str(k).strip()] = cleaned_v

    scores: List[CriterionScore] = []
    for c in data.get("criteria_scores", []) if isinstance(data.get("criteria_scores"), list) else []:
        if not isinstance(c, dict):
            continue
        crit_name = clean_placeholder_str(c.get("criterion"), default="")
        if not crit_name:
            continue
        try:
            max_s = float(c.get("max_score", 10.0))
        except (TypeError, ValueError):
            max_s = 10.0
        aw_raw = c.get("awarded_score")
        try:
            aw_s = float(aw_raw) if aw_raw is not None else None
        except (TypeError, ValueError):
            aw_s = None
        scores.append(
            CriterionScore(
                criterion=crit_name,
                max_score=max_s,
                awarded_score=aw_s,
                comments=clean_placeholder_str(c.get("comments"), default=""),
            )
        )

    action_items: List[ActionItemRecord] = []
    for idx, a in enumerate(
        data.get("action_items", []) if isinstance(data.get("action_items"), list) else [],
        start=1,
    ):
        if not isinstance(a, dict):
            continue
        desc = clean_placeholder_str(a.get("description"), default="")
        if not desc:
            continue
        a_status = clean_placeholder_str(a.get("status"), default="Not Started")
        if a_status not in VALID_TASK_STATUSES:
            a_status = "Not Started"
        action_items.append(
            ActionItemRecord(
                action_id=clean_placeholder_str(a.get("action_id"), default=f"R{rev_num}-A{idx}"),
                description=desc,
                assigned_to=clean_placeholder_str(a.get("assigned_to"), default="Unassigned"),
                due_date=clean_placeholder_str(a.get("due_date"), default="") or None,
                status=a_status,
                resolution_evidence=clean_placeholder_str(a.get("resolution_evidence"), default="") or None,
                completed_date=clean_placeholder_str(a.get("completed_date"), default="") or None,
            )
        )

    return (
        ReviewRecord(
            review_id=clean_placeholder_str(data.get("review_id"), default=f"review-{rev_num}"),
            review_number=rev_num,
            review_name=clean_placeholder_str(data.get("review_name"), default=f"Review {rev_num}"),
            scheduled_date=clean_placeholder_str(data.get("scheduled_date"), default="") or None,
            submission_deadline=clean_placeholder_str(data.get("submission_deadline"), default="") or None,
            submitted_at=clean_placeholder_str(data.get("submitted_at"), default="") or None,
            submission_status=sub_status,
            deliverables=deliverables,
            evidence_links=evidence_links,
            mentor_feedback=clean_placeholder_str(data.get("mentor_feedback"), default=""),
            criteria_scores=scores,
            strengths=clean_placeholder_list(data.get("strengths", [])),
            concerns=clean_placeholder_list(data.get("concerns", [])),
            improvement_areas=clean_placeholder_list(data.get("improvement_areas", [])),
            action_items=action_items,
        ),
        issues,
    )
