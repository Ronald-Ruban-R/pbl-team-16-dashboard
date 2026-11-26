"""
Schema Validation, Resilient Parsing, and Placeholder Sanitization Module.

Ensures:
- Malformed or incomplete JSON files never crash the dashboard (with automatic recovery
  for common trailing-comma edits).
- Flexible field aliases across `team/responsibilities.json`, `team/members.json`,
  `tasks/tasks.json`, `project/timeline.json`, and `reviews/review-N.json` so both
  guide-formatted and UI-edited JSON files render seamlessly.
- Angle-bracket template placeholders (such as `<TEAM_DISPLAY_NAME>`,
  `<TECHNICAL_OR_SOCIAL_IMPACT_DOMAIN>`, `<PROJECT_TITLE>`, `<MEMBER_FULL_NAME>`, etc.)
  are automatically stripped and replaced with clean, human-readable defaults.
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

_PLACEHOLDER_TOKEN_RE = re.compile(r"^<[^<>]+>$")
_EMBEDDED_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_]{2,}>")
_TRAILING_COMMA_RE = re.compile(r",\s*([\]}])")


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
    """Convert a list or string into a list of clean, non-placeholder strings."""
    if isinstance(items, str):
        parts = [p.strip() for p in re.split(r"[;\n]+", items) if p.strip()]
        return [clean_placeholder_str(p) for p in parts if clean_placeholder_str(p)]
    if not isinstance(items, list):
        return []
    cleaned: List[str] = []
    for item in items:
        val = clean_placeholder_str(item, default="")
        if val:
            cleaned.append(val)
    return cleaned



def normalize_task_status(raw_status: Any, default: str = "Not Started") -> str:
    """Normalize common status casing and synonyms (e.g. 'done', 'in-progress', 'completed')."""
    s = clean_placeholder_str(raw_status, default="")
    if not s:
        return default
    if s in VALID_TASK_STATUSES:
        return s
    low = s.lower().replace("_", " ").replace("-", " ").strip()
    mapping = {
        "completed": "Completed",
        "complete": "Completed",
        "done": "Completed",
        "finished": "Completed",
        "closed": "Completed",
        "in progress": "In Progress",
        "inprogress": "In Progress",
        "ongoing": "In Progress",
        "active": "In Progress",
        "working": "In Progress",
        "blocked": "Blocked",
        "stuck": "Blocked",
        "on hold": "Blocked",
        "delayed": "Delayed",
        "overdue": "Delayed",
        "behind": "Delayed",
        "not started": "Not Started",
        "todo": "Not Started",
        "to do": "Not Started",
        "pending": "Not Started",
        "open": "Not Started",
    }
    return mapping.get(low, default)


def normalize_task_priority(raw_prio: Any, default: str = "Medium") -> str:
    """Normalize priority casing (e.g. 'high' -> 'High')."""
    s = clean_placeholder_str(raw_prio, default="")
    if not s:
        return default
    if s in VALID_TASK_PRIORITIES:
        return s
    low = s.lower().strip()
    mapping = {"low": "Low", "medium": "Medium", "med": "Medium", "high": "High", "critical": "Critical", "urgent": "Critical"}
    return mapping.get(low, default)


def normalize_submission_status(raw_status: Any, default: str = "Not Submitted") -> str:
    """Normalize review submission status casing."""
    s = clean_placeholder_str(raw_status, default="")
    if not s:
        return default
    if s in VALID_SUBMISSION_STATUSES:
        return s
    low = s.lower().replace("_", " ").replace("-", " ").strip()
    mapping = {
        "not submitted": "Not Submitted",
        "pending": "Not Submitted",
        "submitted": "Submitted",
        "done": "Submitted",
        "needs revision": "Needs Revision",
        "revision": "Needs Revision",
        "approved": "Approved",
        "completed": "Approved",
    }
    return mapping.get(low, default)


def _first_clean_str(mapping: Dict[str, Any], keys: Tuple[str, ...], default: str = "") -> str:
    """Return the first non-empty, non-placeholder string from `mapping` matching any key in `keys`."""
    for k in keys:
        if k in mapping:
            val = clean_placeholder_str(mapping.get(k), default="")
            if val:
                return val
    return default


def _first_clean_list(mapping: Dict[str, Any], keys: Tuple[str, ...]) -> List[str]:
    """Return the first non-empty list of strings from `mapping` matching any key in `keys`."""
    for k in keys:
        if k in mapping and mapping.get(k) is not None:
            lst = clean_placeholder_list(mapping.get(k))
            if lst:
                return lst
    return []


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
        # Attempt automatic recovery if the user left a trailing comma before `]` or `}`
        repaired = _TRAILING_COMMA_RE.sub(r"\1", raw_text)
        try:
            parsed = json.loads(repaired)
            issues.append(
                ValidationIssue(
                    file_path,
                    "warning",
                    f"Auto-recovered trailing comma near line {exc.lineno}. Consider removing trailing commas in `{file_path}`.",
                )
            )
            return parsed, issues
        except json.JSONDecodeError:
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

    team_id = _first_clean_str(data, ("team_id", "id", "repo"), default=repo_name)
    team_name = _first_clean_str(data, ("team_name", "name", "display_name"), default=fallback_team_name)
    project_title = _first_clean_str(
        data, ("project_title", "title", "project_name"), default=f"{fallback_team_name} Project"
    )
    domain = _first_clean_str(
        data, ("domain", "theme", "category", "track"), default="General Engineering & Innovation"
    )
    problem_statement = _first_clean_str(
        data,
        ("problem_statement", "description", "abstract", "summary"),
        default="Problem statement not yet submitted.",
    )
    objectives = _first_clean_list(data, ("objectives", "goals", "aims"))
    expected_outcomes = _first_clean_list(data, ("expected_outcomes", "outcomes", "deliverables"))
    start_date = _first_clean_str(data, ("start_date", "kickoff_date"), default="") or None
    target_date = _first_clean_str(
        data, ("target_completion_date", "end_date", "completion_date"), default=""
    ) or None
    lead_mentor = _first_clean_str(data, ("lead_mentor", "mentor", "primary_mentor"), default="")
    co_mentor = _first_clean_str(data, ("co_mentor", "secondary_mentor"), default="")
    tags = _first_clean_list(data, ("tags", "keywords", "technologies"))

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

    raw_list: Any = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for k in ("members", "team_members", "roster", "students", "team"):
            if isinstance(data.get(k), list):
                raw_list = data.get(k)
                break
        if not raw_list:
            for v in data.values():
                if isinstance(v, list):
                    raw_list = v
                    break

    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`members` must be a list of member objects."))
        return [], issues

    members: List[TeamMember] = []
    skipped_placeholders = 0
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        name = _first_clean_str(item, ("name", "member_name", "full_name", "student_name"), default="")
        if not name:
            skipped_placeholders += 1
            continue
        member_id = _first_clean_str(item, ("member_id", "id", "roll_no", "student_id"), default=f"M{idx}")
        gh_user = _first_clean_str(item, ("github_username", "github", "username", "github_id"), default="")
        role = _first_clean_str(item, ("role", "primary_role", "position", "title"), default="Team Member")
        discipline = _first_clean_str(
            item, ("discipline", "department", "branch", "major", "stream"), default=""
        )
        email = _first_clean_str(item, ("email", "mail", "contact"), default="")
        skills = _first_clean_list(item, ("skills", "expertise", "tech_stack"))
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
    """
    Parse `team/responsibilities.json` supporting all common schema variations:
    - Top-level keys: `responsibilities`, `assignments`, `responsibility_matrix`, `members`, `roles`,
      or any top-level list or dictionary mapping member names to duties.
    - Item field aliases:
      - `name` / `member_name` / `member` / `student_name` / `owner` / `assigned_to`
      - `primary_area` / `primary_role` / `area` / `role` / `domain` / `module` / `focus_area` / `component`
      - `responsibilities` / `key_responsibilities` / `duties` / `tasks` / `description` / `work_items`
      - `owned_deliverables` / `deliverables_owned` / `deliverables` / `artifacts` / `outputs`
      - `backup_owner` / `backup` / `secondary_owner`
    """
    data, issues = _safe_load_json(raw_text, file_path)
    if data is None:
        return [], issues

    raw_list: Any = None
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for k in (
            "responsibilities",
            "assignments",
            "responsibility_matrix",
            "matrix",
            "members",
            "team_responsibilities",
            "roles",
            "items",
        ):
            if k in data and isinstance(data[k], list):
                raw_list = data[k]
                break
        if raw_list is None:
            for v in data.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    raw_list = v
                    break
        # Support dict-of-dicts or dict-of-lists keyed by member name
        if raw_list is None:
            converted: List[Dict[str, Any]] = []
            for idx, (k, v) in enumerate(data.items(), start=1):
                if k in ("team_id", "team_name", "last_updated", "version"):
                    continue
                if isinstance(v, list):
                    converted.append(
                        {
                            "member_id": f"M{idx}",
                            "name": str(k),
                            "primary_area": "Project Execution",
                            "responsibilities": v,
                        }
                    )
                elif isinstance(v, dict):
                    merged = dict(v)
                    merged.setdefault("name", str(k))
                    merged.setdefault("member_id", f"M{idx}")
                    converted.append(merged)
            if converted:
                raw_list = converted

    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`responsibilities` must be a list of records."))
        return [], issues

    records: List[ResponsibilityRecord] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        name = _first_clean_str(
            item,
            ("name", "member_name", "member", "student_name", "full_name", "owner", "assigned_to"),
            default="",
        )
        raw_primary_areas = _first_clean_list(item, ("primary_areas", "areas", "roles"))
        primary_area = _first_clean_str(
            item,
            (
                "primary_area",
                "primary_role",
                "area",
                "role",
                "domain",
                "module",
                "focus_area",
                "component",
                "track",
                "title",
            ),
            default=", ".join(raw_primary_areas) if raw_primary_areas else "",
        )
        resp_items = _first_clean_list(
            item,
            (
                "responsibilities",
                "key_responsibilities",
                "primary_areas",
                "duties",
                "tasks",
                "work_items",
                "Sub-tasks",
                "description",
                "details",
                "notes",
            ),
        )
        owned_deliv = _first_clean_list(
            item,
            (
                "owned_deliverables",
                "deliverables_owned",
                "deliverables",
                "artifacts",
                "outputs",
                "files",
            ),
        )
        backup = _first_clean_str(
            item,
            ("backup_owner", "backup", "secondary_owner", "co_owner", "reviewer"),
            default="",
        )
        member_id = _first_clean_str(item, ("member_id", "id", "roll_no"), default=f"M{idx}")

        if not name and not primary_area and not resp_items and not owned_deliv:
            continue

        records.append(
            ResponsibilityRecord(
                member_id=member_id,
                name=name or member_id,
                primary_area=primary_area or "General Project Execution",
                responsibilities=resp_items,
                owned_deliverables=owned_deliv,
                backup_owner=backup,
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

    rep_pct_raw = data.get("overall_reported_pct", data.get("overall_progress_pct", data.get("progress_pct")))
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
            status_val = normalize_task_status(_first_clean_str(m, ("status", "state"), default="Not Started"))
            try:
                weight_val = max(0.0, float(m.get("weight", 25.0)))
            except (TypeError, ValueError):
                weight_val = 25.0
            try:
                comp_val = max(0.0, min(100.0, float(m.get("completion_pct", m.get("progress_pct", 0.0)))))
            except (TypeError, ValueError):
                comp_val = 100.0 if status_val == "Completed" else 0.0

            milestones.append(
                MilestoneProgress(
                    milestone_id=_first_clean_str(m, ("milestone_id", "id"), default=f"M{idx}"),
                    title=_first_clean_str(m, ("title", "name", "milestone"), default=f"Milestone {idx}"),
                    status=status_val,
                    weight=weight_val,
                    completion_pct=comp_val,
                    due_date=_first_clean_str(m, ("due_date", "target_date", "planned_date"), default="") or None,
                    completed_date=_first_clean_str(m, ("completed_date", "actual_date"), default="") or None,
                    evidence_path=_first_clean_str(m, ("evidence_path", "evidence_link", "artifact_path"), default="") or None,
                )
            )

    return (
        ProgressRecord(
            last_updated=_first_clean_str(data, ("last_updated", "updated_at", "date"), default="") or None,
            current_phase=_first_clean_str(data, ("current_phase", "phase", "stage"), default="In Progress"),
            overall_reported_pct=rep_pct,
            summary=_first_clean_str(data, ("summary", "status_summary", "overview"), default=""),
            accomplishments_since_last_update=_first_clean_list(
                data, ("accomplishments_since_last_update", "accomplishments", "completed_recently", "highlights")
            ),
            blockers=_first_clean_list(data, ("blockers", "risks", "impediments", "challenges")),
            next_steps=_first_clean_list(data, ("next_steps", "upcoming", "planned_next")),
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

    raw_list: Any = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for k in ("events", "timeline", "milestones", "schedule", "phases"):
            if isinstance(data.get(k), list):
                raw_list = data.get(k)
                break
        if not raw_list:
            for v in data.values():
                if isinstance(v, list):
                    raw_list = v
                    break

    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`events` must be a list."))
        return [], issues

    events: List[TimelineEvent] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        title = _first_clean_str(item, ("title", "event", "name", "milestone"), default="")
        if not title:
            continue
        status_val = normalize_task_status(_first_clean_str(item, ("status", "state"), default="Not Started"))
        etype = _first_clean_str(item, ("event_type", "type", "category"), default="Milestone")
        if etype not in VALID_TIMELINE_TYPES:
            etype = "Milestone"
        events.append(
            TimelineEvent(
                event_id=_first_clean_str(item, ("event_id", "id", "milestone_id"), default=f"E{idx}"),
                title=title,
                event_type=etype,
                planned_date=_first_clean_str(item, ("planned_date", "target_date", "due_date", "date"), default="") or None,
                actual_date=_first_clean_str(item, ("actual_date", "completed_date"), default="") or None,
                status=status_val,
                description=_first_clean_str(item, ("description", "notes", "details"), default=""),
                owner=_first_clean_str(item, ("owner", "assigned_to", "lead"), default=""),
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

    raw_list: Any = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        for k in ("tasks", "items", "task_list", "backlog"):
            if isinstance(data.get(k), list):
                raw_list = data.get(k)
                break
        if not raw_list:
            for v in data.values():
                if isinstance(v, list):
                    raw_list = v
                    break

    if not isinstance(raw_list, list):
        issues.append(ValidationIssue(file_path, "error", "`tasks` must be a list."))
        return [], issues

    tasks: List[TaskItem] = []
    for idx, item in enumerate(raw_list, start=1):
        if not isinstance(item, dict):
            continue
        title = _first_clean_str(item, ("title", "task_title", "task_name", "task", "name", "summary"), default="")
        if not title:
            continue
        status_val = normalize_task_status(_first_clean_str(item, ("status", "state"), default="Not Started"))
        prio_val = normalize_task_priority(_first_clean_str(item, ("priority", "urgency"), default="Medium"))
        try:
            weight_val = max(0.1, float(item.get("weight", 1.0)))
        except (TypeError, ValueError):
            weight_val = 1.0
        rel_rev = item.get("related_review", item.get("review_number"))
        try:
            rel_rev_int = int(rel_rev) if rel_rev is not None else None
        except (TypeError, ValueError):
            rel_rev_int = None

        tasks.append(
            TaskItem(
                task_id=_first_clean_str(item, ("task_id", "id"), default=f"T-{100 + idx}"),
                title=title,
                description=_first_clean_str(item, ("description", "details", "notes"), default=""),
                assigned_to=_first_clean_str(
                    item, ("assigned_to", "assignee", "owner", "member"), default="Unassigned"
                ),
                priority=prio_val,
                status=status_val,
                start_date=_first_clean_str(item, ("start_date", "created_date"), default="") or None,
                due_date=_first_clean_str(item, ("due_date", "deadline", "target_date"), default="") or None,
                completed_date=_first_clean_str(item, ("completed_date", "actual_date"), default="") or None,
                related_milestone=_first_clean_str(item, ("related_milestone", "milestone_id", "milestone"), default="") or None,
                related_review=rel_rev_int,
                evidence_link=_first_clean_str(
                    item, ("evidence_link", "evidence_path", "artifact_path", "evidence"), default=""
                ) or None,
                last_updated=_first_clean_str(item, ("last_updated", "updated_at"), default="") or None,
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

    sub_status = normalize_submission_status(_first_clean_str(data, ("submission_status", "status"), default="Not Submitted"))

    deliverables: List[DeliverableItem] = []
    for d in data.get("deliverables", []) if isinstance(data.get("deliverables"), list) else []:
        if not isinstance(d, dict):
            continue
        d_title = _first_clean_str(d, ("title", "name", "deliverable"), default="")
        if not d_title:
            continue
        deliverables.append(
            DeliverableItem(
                title=d_title,
                required=bool(d.get("required", True)),
                submitted=bool(d.get("submitted", False)),
                artifact_path=_first_clean_str(
                    d, ("artifact_path", "evidence_path", "file_path", "path", "link"), default=""
                ) or None,
                notes=_first_clean_str(d, ("notes", "comments", "description"), default=""),
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
        crit_name = _first_clean_str(c, ("criterion", "name", "category"), default="")
        if not crit_name:
            continue
        try:
            max_s = float(c.get("max_score", 10.0))
        except (TypeError, ValueError):
            max_s = 10.0
        aw_raw = c.get("awarded_score", c.get("score"))
        try:
            aw_s = float(aw_raw) if aw_raw is not None else None
        except (TypeError, ValueError):
            aw_s = None
        scores.append(
            CriterionScore(
                criterion=crit_name,
                max_score=max_s,
                awarded_score=aw_s,
                comments=_first_clean_str(c, ("comments", "notes", "feedback"), default=""),
            )
        )

    action_items: List[ActionItemRecord] = []
    for idx, a in enumerate(
        data.get("action_items", []) if isinstance(data.get("action_items"), list) else [],
        start=1,
    ):
        if not isinstance(a, dict):
            continue
        desc = _first_clean_str(a, ("description", "title", "action", "task"), default="")
        if not desc:
            continue
        a_status = normalize_task_status(_first_clean_str(a, ("status", "state"), default="Not Started"))
        action_items.append(
            ActionItemRecord(
                action_id=_first_clean_str(a, ("action_id", "id"), default=f"R{rev_num}-A{idx}"),
                description=desc,
                assigned_to=_first_clean_str(a, ("assigned_to", "assignee", "owner"), default="Unassigned"),
                due_date=_first_clean_str(a, ("due_date", "deadline"), default="") or None,
                status=a_status,
                resolution_evidence=_first_clean_str(
                    a, ("resolution_evidence", "evidence_link", "evidence_path"), default=""
                ) or None,
                completed_date=_first_clean_str(a, ("completed_date", "actual_date"), default="") or None,
            )
        )

    return (
        ReviewRecord(
            review_id=_first_clean_str(data, ("review_id", "id"), default=f"review-{rev_num}"),
            review_number=rev_num,
            review_name=_first_clean_str(data, ("review_name", "title", "name"), default=f"Review {rev_num}"),
            scheduled_date=_first_clean_str(data, ("scheduled_date", "date"), default="") or None,
            submission_deadline=_first_clean_str(data, ("submission_deadline", "deadline"), default="") or None,
            submitted_at=_first_clean_str(data, ("submitted_at", "submitted_date"), default="") or None,
            submission_status=sub_status,
            deliverables=deliverables,
            evidence_links=evidence_links,
            mentor_feedback=_first_clean_str(data, ("mentor_feedback", "feedback", "comments"), default=""),
            criteria_scores=scores,
            strengths=_first_clean_list(data, ("strengths", "positives")),
            concerns=_first_clean_list(data, ("concerns", "weaknesses", "issues")),
            improvement_areas=_first_clean_list(data, ("improvement_areas", "improvements", "recommendations")),
            action_items=action_items,
        ),
        issues,
    )
