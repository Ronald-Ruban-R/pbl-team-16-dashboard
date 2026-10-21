"""
JSON Schema validation and structured metadata parsers for the PBL Cohort-X Mentor Dashboard.

Clearly distinguishes between:
- `MISSING`: The metadata file is not present in the repository.
- `MALFORMED`: The file exists but contains invalid JSON syntax or violates schema rules.
- `VALID`: The file exists and was parsed into structured dataclasses (with any non-fatal warnings attached).

Never invents or fabricates missing values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ValidationState(str, Enum):
    """Status of a structured repository metadata file."""

    VALID = "valid"
    MISSING = "missing"
    MALFORMED = "malformed"
    RETRIEVAL_ERROR = "retrieval_error"


VALID_TASK_STATUSES = ("Not Started", "In Progress", "Blocked", "Completed")
VALID_TASK_PRIORITIES = ("Low", "Medium", "High", "Critical")
VALID_SUBMISSION_STATUSES = ("Not Submitted", "Partial", "Submitted", "Reviewed", "Resubmission Required")


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Parse an ISO-8601 date (`YYYY-MM-DD` or full timestamp) without raising."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
        except ValueError:
            return None


@dataclass
class ValidationReport:
    """Detailed validation outcome for a single metadata file."""

    file_path: str
    state: ValidationState
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parsed_data: Optional[Any] = None


@dataclass
class ProjectMetadata:
    """Parsed `project/metadata.json`."""

    team_id: str
    team_name: str
    project_title: str
    domain: str
    problem_statement: str
    objectives: List[str] = field(default_factory=list)
    expected_outcomes: List[str] = field(default_factory=list)
    start_date: Optional[str] = None
    target_completion_date: Optional[str] = None
    lead_mentor: Optional[str] = None
    co_mentor: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class MilestoneProgressEntry:
    """Single milestone entry inside `project/progress.json`."""

    milestone_id: str
    title: str
    status: str  # Not Started, In Progress, Blocked, Completed
    weight: float = 0.0
    completion_pct: Optional[float] = None
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    evidence_path: Optional[str] = None


@dataclass
class ReportedProgress:
    """Parsed `project/progress.json`."""

    last_updated: Optional[str]
    current_phase: str
    overall_reported_pct: Optional[float]
    summary: str
    accomplishments_since_last_update: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    milestones: List[MilestoneProgressEntry] = field(default_factory=list)


@dataclass
class TeamMember:
    """Parsed member record from `team/members.json`."""

    member_id: str
    name: str
    github_username: Optional[str] = None
    role: str = "Team Member"
    discipline: Optional[str] = None
    email: Optional[str] = None


@dataclass
class MemberResponsibility:
    """Parsed responsibility assignment from `team/responsibilities.json`."""

    member_id: str
    member_name: str
    primary_areas: List[str] = field(default_factory=list)
    deliverables_owned: List[str] = field(default_factory=list)
    notes: Optional[str] = None


@dataclass
class TaskRecord:
    """Parsed task from `tasks/tasks.json`."""

    task_id: str
    title: str
    description: str
    assigned_to: str
    priority: str  # Low, Medium, High, Critical
    status: str    # Not Started, In Progress, Blocked, Completed
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    completed_date: Optional[str] = None
    related_milestone: Optional[str] = None
    related_review: Optional[str] = None
    evidence_link: Optional[str] = None
    last_updated: Optional[str] = None
    weight: float = 1.0


@dataclass
class ActionItemRecord:
    """Action item assigned during a mentor review."""

    action_id: str
    description: str
    assigned_to: str
    due_date: Optional[str] = None
    status: str = "Not Started"  # Not Started, In Progress, Blocked, Completed
    resolution_evidence: Optional[str] = None
    completed_date: Optional[str] = None


@dataclass
class CriterionScore:
    """Evaluation criterion score inside a review record."""

    criterion: str
    max_score: float
    awarded_score: Optional[float] = None
    comments: Optional[str] = None


@dataclass
class ReviewDeliverableItem:
    """Deliverable item listed in `reviews/review-N.json`."""

    title: str
    required: bool = True
    submitted: bool = False
    artifact_path: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class ReviewRecord:
    """Parsed `reviews/review-N.json`."""

    review_id: str
    review_number: int
    review_name: str
    scheduled_date: Optional[str] = None
    submission_deadline: Optional[str] = None
    submitted_at: Optional[str] = None
    submission_status: str = "Not Submitted"
    deliverables: List[ReviewDeliverableItem] = field(default_factory=list)
    evidence_links: Dict[str, str] = field(default_factory=dict)
    mentor_feedback: Optional[str] = None
    criteria_scores: List[CriterionScore] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)
    improvement_areas: List[str] = field(default_factory=list)
    action_items: List[ActionItemRecord] = field(default_factory=list)


@dataclass
class TimelineEvent:
    """Chronological event from `project/timeline.json`."""

    event_id: str
    title: str
    category: str  # Milestone, Review, Competition, Deliverable, Task
    planned_date: Optional[str] = None
    actual_date: Optional[str] = None
    status: str = "Not Started"
    delay_reason: Optional[str] = None
    evidence_path: Optional[str] = None


@dataclass
class ResearchEntry:
    """Structured research, dataset, or competition entry extracted from timeline/metadata or repository."""

    entry_id: str
    title: str
    category: str  # Literature Review, Dataset, Experiment, Competition, Technical Doc, Certificate
    file_path: str
    html_url: str
    date_recorded: Optional[str] = None
    related_review: Optional[str] = None
    phase: Optional[str] = None
    summary: Optional[str] = None


# ---------------------------------------------------------------------------
# Validation Helper Functions
# ---------------------------------------------------------------------------

def _load_json_dict(file_path: str, raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], ValidationReport]:
    if not exists:
        if fetch_error and "not found" not in fetch_error.lower() and "not present" not in fetch_error.lower():
            return None, ValidationReport(
                file_path=file_path,
                state=ValidationState.RETRIEVAL_ERROR,
                errors=[fetch_error],
            )
        return None, ValidationReport(
            file_path=file_path,
            state=ValidationState.MISSING,
            warnings=[f"`{file_path}` is not present in the repository."],
        )

    if raw_text is None or not raw_text.strip():
        return None, ValidationReport(
            file_path=file_path,
            state=ValidationState.MALFORMED,
            errors=[f"`{file_path}` is empty or contains no readable JSON text."],
        )

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, ValidationReport(
            file_path=file_path,
            state=ValidationState.MALFORMED,
            errors=[f"Invalid JSON syntax in `{file_path}` at line {exc.lineno}, column {exc.colno}: {exc.msg}"],
        )

    if not isinstance(parsed, dict):
        return None, ValidationReport(
            file_path=file_path,
            state=ValidationState.MALFORMED,
            errors=[f"Root element of `{file_path}` must be a JSON object (`{{...}}`), got `{type(parsed).__name__}`."],
        )

    return parsed, ValidationReport(file_path=file_path, state=ValidationState.VALID)


def validate_project_metadata(raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None, file_path: str = "project/metadata.json") -> ValidationReport:
    """Validate and parse `project/metadata.json`."""
    data, report = _load_json_dict(file_path, raw_text, exists, fetch_error)
    if data is None:
        return report

    required_fields = ("team_id", "team_name", "project_title", "domain", "problem_statement")
    for req in required_fields:
        val = data.get(req)
        if not isinstance(val, str) or not val.strip():
            report.errors.append(f"Missing or empty required string field `{req}` in `{file_path}`.")

    if report.errors:
        report.state = ValidationState.MALFORMED
        return report

    objectives = data.get("objectives", [])
    if not isinstance(objectives, list):
        report.warnings.append("`objectives` should be a list of strings; ignoring invalid type.")
        objectives = []

    outcomes = data.get("expected_outcomes", [])
    if not isinstance(outcomes, list):
        report.warnings.append("`expected_outcomes` should be a list of strings; ignoring invalid type.")
        outcomes = []

    start_date = data.get("start_date")
    if start_date and parse_iso_date(str(start_date)) is None:
        report.warnings.append(f"`start_date` ('{start_date}') is not a valid YYYY-MM-DD date.")

    target_date = data.get("target_completion_date")
    if target_date and parse_iso_date(str(target_date)) is None:
        report.warnings.append(f"`target_completion_date` ('{target_date}') is not a valid YYYY-MM-DD date.")

    report.parsed_data = ProjectMetadata(
        team_id=str(data["team_id"]).strip(),
        team_name=str(data["team_name"]).strip(),
        project_title=str(data["project_title"]).strip(),
        domain=str(data["domain"]).strip(),
        problem_statement=str(data["problem_statement"]).strip(),
        objectives=[str(x).strip() for x in objectives if str(x).strip()],
        expected_outcomes=[str(x).strip() for x in outcomes if str(x).strip()],
        start_date=str(start_date).strip() if start_date else None,
        target_completion_date=str(target_date).strip() if target_date else None,
        lead_mentor=str(data["lead_mentor"]).strip() if data.get("lead_mentor") else None,
        co_mentor=str(data["co_mentor"]).strip() if data.get("co_mentor") else None,
        tags=[str(t).strip() for t in data.get("tags", []) if isinstance(data.get("tags"), list) and str(t).strip()],
    )
    return report


def validate_progress_data(raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None, file_path: str = "project/progress.json") -> ValidationReport:
    """Validate and parse `project/progress.json`."""
    data, report = _load_json_dict(file_path, raw_text, exists, fetch_error)
    if data is None:
        return report

    overall_pct = data.get("overall_reported_pct")
    parsed_pct: Optional[float] = None
    if overall_pct is not None:
        try:
            parsed_pct = float(overall_pct)
            if not (0.0 <= parsed_pct <= 100.0):
                report.errors.append(f"`overall_reported_pct` must be between 0 and 100 (got {parsed_pct}).")
        except (ValueError, TypeError):
            report.errors.append(f"`overall_reported_pct` must be a number (got '{overall_pct}').")

    last_updated = data.get("last_updated")
    if last_updated and parse_iso_date(str(last_updated)) is None:
        report.warnings.append(f"`last_updated` ('{last_updated}') is not a valid ISO date.")

    milestones_raw = data.get("milestones", [])
    milestones: List[MilestoneProgressEntry] = []
    if not isinstance(milestones_raw, list):
        report.errors.append("`milestones` in `project/progress.json` must be a list.")
    else:
        for idx, m in enumerate(milestones_raw):
            if not isinstance(m, dict):
                report.warnings.append(f"Milestone at index {idx} is not an object; skipped.")
                continue
            m_id = str(m.get("milestone_id") or f"M-{idx + 1}").strip()
            title = str(m.get("title") or "").strip()
            if not title:
                report.warnings.append(f"Milestone `{m_id}` is missing a `title`.")
                continue
            status = str(m.get("status") or "Not Started").strip()
            if status not in VALID_TASK_STATUSES:
                report.warnings.append(
                    f"Milestone `{m_id}` has unrecognized status '{status}'. Expected one of {VALID_TASK_STATUSES}."
                )
            weight = 0.0
            try:
                weight = float(m.get("weight", 0.0))
                if weight < 0:
                    report.errors.append(f"Milestone `{m_id}` has negative weight ({weight}).")
            except (ValueError, TypeError):
                report.warnings.append(f"Milestone `{m_id}` has non-numeric weight; defaulting to 0.")

            comp_pct: Optional[float] = None
            if m.get("completion_pct") is not None:
                try:
                    comp_pct = float(m["completion_pct"])
                    if not (0.0 <= comp_pct <= 100.0):
                        report.errors.append(f"Milestone `{m_id}` completion_pct ({comp_pct}) out of [0, 100] range.")
                except (ValueError, TypeError):
                    report.warnings.append(f"Milestone `{m_id}` has non-numeric `completion_pct`.")

            milestones.append(
                MilestoneProgressEntry(
                    milestone_id=m_id,
                    title=title,
                    status=status,
                    weight=weight,
                    completion_pct=comp_pct,
                    due_date=str(m["due_date"]).strip() if m.get("due_date") else None,
                    completed_date=str(m["completed_date"]).strip() if m.get("completed_date") else None,
                    evidence_path=str(m["evidence_path"]).strip() if m.get("evidence_path") else None,
                )
            )

    if report.errors:
        report.state = ValidationState.MALFORMED
        return report

    def _clean_str_list(key: str) -> List[str]:
        raw = data.get(key, [])
        if not isinstance(raw, list):
            report.warnings.append(f"`{key}` should be a list of strings.")
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    report.parsed_data = ReportedProgress(
        last_updated=str(last_updated).strip() if last_updated else None,
        current_phase=str(data.get("current_phase") or "Not Specified").strip(),
        overall_reported_pct=parsed_pct,
        summary=str(data.get("summary") or "").strip(),
        accomplishments_since_last_update=_clean_str_list("accomplishments_since_last_update"),
        blockers=_clean_str_list("blockers"),
        next_steps=_clean_str_list("next_steps"),
        milestones=milestones,
    )
    return report


def validate_members_data(raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None, file_path: str = "team/members.json") -> ValidationReport:
    """Validate and parse `team/members.json`."""
    data, report = _load_json_dict(file_path, raw_text, exists, fetch_error)
    if data is None:
        return report

    members_raw = data.get("members")
    if not isinstance(members_raw, list):
        report.errors.append(f"`{file_path}` must contain a `members` list.")
        report.state = ValidationState.MALFORMED
        return report

    members: List[TeamMember] = []
    for idx, item in enumerate(members_raw):
        if not isinstance(item, dict):
            report.errors.append(f"Member entry at index {idx} in `{file_path}` must be an object.")
            continue
        name = str(item.get("name") or "").strip()
        member_id = str(item.get("member_id") or f"M{idx + 1}").strip()
        if not name:
            report.errors.append(f"Member entry `{member_id}` in `{file_path}` is missing required `name`.")
            continue
        members.append(
            TeamMember(
                member_id=member_id,
                name=name,
                github_username=str(item["github_username"]).strip() if item.get("github_username") else None,
                role=str(item.get("role") or "Team Member").strip(),
                discipline=str(item["discipline"]).strip() if item.get("discipline") else None,
                email=str(item["email"]).strip() if item.get("email") else None,
            )
        )

    if report.errors:
        report.state = ValidationState.MALFORMED
        return report

    report.parsed_data = members
    return report


def validate_responsibilities_data(raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None, file_path: str = "team/responsibilities.json") -> ValidationReport:
    """Validate and parse `team/responsibilities.json`."""
    data, report = _load_json_dict(file_path, raw_text, exists, fetch_error)
    if data is None:
        return report

    resp_raw = data.get("responsibilities")
    if not isinstance(resp_raw, list):
        report.errors.append(f"`{file_path}` must contain a `responsibilities` list.")
        report.state = ValidationState.MALFORMED
        return report

    records: List[MemberResponsibility] = []
    for idx, item in enumerate(resp_raw):
        if not isinstance(item, dict):
            report.warnings.append(f"Responsibility entry at index {idx} is not an object; skipped.")
            continue
        member_id = str(item.get("member_id") or f"M{idx + 1}").strip()
        member_name = str(item.get("member_name") or item.get("name") or "").strip()
        if not member_name:
            report.errors.append(f"Responsibility entry `{member_id}` is missing `member_name`.")
            continue
        areas = item.get("primary_areas", [])
        deliverables = item.get("deliverables_owned", [])
        records.append(
            MemberResponsibility(
                member_id=member_id,
                member_name=member_name,
                primary_areas=[str(a).strip() for a in areas if isinstance(areas, list) and str(a).strip()],
                deliverables_owned=[str(d).strip() for d in deliverables if isinstance(deliverables, list) and str(d).strip()],
                notes=str(item["notes"]).strip() if item.get("notes") else None,
            )
        )

    if report.errors:
        report.state = ValidationState.MALFORMED
        return report

    report.parsed_data = records
    return report


def validate_tasks_data(raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None, file_path: str = "tasks/tasks.json") -> ValidationReport:
    """Validate and parse `tasks/tasks.json`."""
    data, report = _load_json_dict(file_path, raw_text, exists, fetch_error)
    if data is None:
        return report

    tasks_raw = data.get("tasks")
    if not isinstance(tasks_raw, list):
        report.errors.append(f"`{file_path}` must contain a `tasks` list.")
        report.state = ValidationState.MALFORMED
        return report

    tasks: List[TaskRecord] = []
    seen_ids = set()
    for idx, item in enumerate(tasks_raw):
        if not isinstance(item, dict):
            report.errors.append(f"Task at index {idx} in `{file_path}` must be a JSON object.")
            continue
        task_id = str(item.get("task_id") or f"T-{idx + 1}").strip()
        if task_id in seen_ids:
            report.warnings.append(f"Duplicate task_id `{task_id}` in `{file_path}`.")
        seen_ids.add(task_id)

        title = str(item.get("title") or "").strip()
        if not title:
            report.errors.append(f"Task `{task_id}` in `{file_path}` is missing required `title`.")
            continue

        status = str(item.get("status") or "Not Started").strip()
        if status not in VALID_TASK_STATUSES:
            report.errors.append(
                f"Task `{task_id}` has invalid status '{status}'. Allowed values: {', '.join(VALID_TASK_STATUSES)}."
            )
            continue

        priority = str(item.get("priority") or "Medium").strip()
        if priority not in VALID_TASK_PRIORITIES:
            report.warnings.append(
                f"Task `{task_id}` has non-standard priority '{priority}'. Defaulting to 'Medium'."
            )
            priority = "Medium"

        weight = 1.0
        if item.get("weight") is not None:
            try:
                weight = float(item["weight"])
                if weight <= 0:
                    report.warnings.append(f"Task `{task_id}` weight must be > 0; using 1.0.")
                    weight = 1.0
            except (ValueError, TypeError):
                report.warnings.append(f"Task `{task_id}` has invalid numeric weight; using 1.0.")

        due_date = str(item["due_date"]).strip() if item.get("due_date") else None
        if due_date and parse_iso_date(due_date) is None:
            report.warnings.append(f"Task `{task_id}` has malformed `due_date` ('{due_date}').")

        tasks.append(
            TaskRecord(
                task_id=task_id,
                title=title,
                description=str(item.get("description") or "").strip(),
                assigned_to=str(item.get("assigned_to") or "Unassigned").strip(),
                priority=priority,
                status=status,
                start_date=str(item["start_date"]).strip() if item.get("start_date") else None,
                due_date=due_date,
                completed_date=str(item["completed_date"]).strip() if item.get("completed_date") else None,
                related_milestone=str(item["related_milestone"]).strip() if item.get("related_milestone") else None,
                related_review=str(item["related_review"]).strip() if item.get("related_review") else None,
                evidence_link=str(item["evidence_link"]).strip() if item.get("evidence_link") else None,
                last_updated=str(item["last_updated"]).strip() if item.get("last_updated") else None,
                weight=weight,
            )
        )

    if report.errors:
        report.state = ValidationState.MALFORMED
        return report

    report.parsed_data = tasks
    return report


def validate_review_data(raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None, file_path: str = "reviews/review-1.json") -> ValidationReport:
    """Validate and parse a `reviews/review-N.json` file."""
    data, report = _load_json_dict(file_path, raw_text, exists, fetch_error)
    if data is None:
        return report

    review_id = str(data.get("review_id") or "").strip()
    review_name = str(data.get("review_name") or "").strip()
    review_number = data.get("review_number")

    if not review_id or not review_name or review_number is None:
        report.errors.append(
            f"`{file_path}` must define `review_id`, `review_number`, and `review_name`."
        )
        report.state = ValidationState.MALFORMED
        return report

    try:
        review_num_int = int(review_number)
    except (ValueError, TypeError):
        report.errors.append(f"`review_number` in `{file_path}` must be an integer.")
        report.state = ValidationState.MALFORMED
        return report

    sub_status = str(data.get("submission_status") or "Not Submitted").strip()
    if sub_status not in VALID_SUBMISSION_STATUSES:
        report.warnings.append(
            f"Unrecognized `submission_status` ('{sub_status}') in `{file_path}`. Expected one of {VALID_SUBMISSION_STATUSES}."
        )

    deliverables: List[ReviewDeliverableItem] = []
    for idx, d in enumerate(data.get("deliverables", []) if isinstance(data.get("deliverables"), list) else []):
        if not isinstance(d, dict):
            continue
        title = str(d.get("title") or "").strip()
        if not title:
            continue
        deliverables.append(
            ReviewDeliverableItem(
                title=title,
                required=bool(d.get("required", True)),
                submitted=bool(d.get("submitted", False)),
                artifact_path=str(d["artifact_path"]).strip() if d.get("artifact_path") else None,
                notes=str(d["notes"]).strip() if d.get("notes") else None,
            )
        )

    criteria_scores: List[CriterionScore] = []
    for idx, c in enumerate(data.get("criteria_scores", []) if isinstance(data.get("criteria_scores"), list) else []):
        if not isinstance(c, dict):
            continue
        crit_name = str(c.get("criterion") or "").strip()
        if not crit_name:
            continue
        try:
            max_s = float(c.get("max_score", 10.0))
        except (ValueError, TypeError):
            max_s = 10.0
        awarded_s: Optional[float] = None
        if c.get("awarded_score") is not None:
            try:
                awarded_s = float(c["awarded_score"])
                if awarded_s < 0 or awarded_s > max_s:
                    report.warnings.append(
                        f"Criterion '{crit_name}' awarded_score ({awarded_s}) is outside [0, {max_s}]."
                    )
            except (ValueError, TypeError):
                report.warnings.append(f"Criterion '{crit_name}' has non-numeric `awarded_score`.")
        criteria_scores.append(
            CriterionScore(
                criterion=crit_name,
                max_score=max_s,
                awarded_score=awarded_s,
                comments=str(c["comments"]).strip() if c.get("comments") else None,
            )
        )

    action_items: List[ActionItemRecord] = []
    for idx, a in enumerate(data.get("action_items", []) if isinstance(data.get("action_items"), list) else []):
        if not isinstance(a, dict):
            continue
        desc = str(a.get("description") or "").strip()
        if not desc:
            continue
        a_status = str(a.get("status") or "Not Started").strip()
        if a_status not in VALID_TASK_STATUSES:
            report.warnings.append(f"Action item `{a.get('action_id', idx)}` has unrecognized status '{a_status}'.")
        action_items.append(
            ActionItemRecord(
                action_id=str(a.get("action_id") or f"AI-{review_num_int}-{idx + 1}").strip(),
                description=desc,
                assigned_to=str(a.get("assigned_to") or "Team").strip(),
                due_date=str(a["due_date"]).strip() if a.get("due_date") else None,
                status=a_status,
                resolution_evidence=str(a["resolution_evidence"]).strip() if a.get("resolution_evidence") else None,
                completed_date=str(a["completed_date"]).strip() if a.get("completed_date") else None,
            )
        )

    evidence_links_raw = data.get("evidence_links", {})
    evidence_links = (
        {str(k): str(v) for k, v in evidence_links_raw.items() if v}
        if isinstance(evidence_links_raw, dict)
        else {}
    )

    def _str_list(field_name: str) -> List[str]:
        val = data.get(field_name, [])
        return [str(x).strip() for x in val if isinstance(val, list) and str(x).strip()]

    report.parsed_data = ReviewRecord(
        review_id=review_id,
        review_number=review_num_int,
        review_name=review_name,
        scheduled_date=str(data["scheduled_date"]).strip() if data.get("scheduled_date") else None,
        submission_deadline=str(data["submission_deadline"]).strip() if data.get("submission_deadline") else None,
        submitted_at=str(data["submitted_at"]).strip() if data.get("submitted_at") else None,
        submission_status=sub_status,
        deliverables=deliverables,
        evidence_links=evidence_links,
        mentor_feedback=str(data["mentor_feedback"]).strip() if data.get("mentor_feedback") else None,
        criteria_scores=criteria_scores,
        strengths=_str_list("strengths"),
        concerns=_str_list("concerns"),
        improvement_areas=_str_list("improvement_areas"),
        action_items=action_items,
    )
    return report


def validate_timeline_data(raw_text: Optional[str], exists: bool, fetch_error: Optional[str] = None, file_path: str = "project/timeline.json") -> ValidationReport:
    """Validate and parse `project/timeline.json`."""
    data, report = _load_json_dict(file_path, raw_text, exists, fetch_error)
    if data is None:
        return report

    events_raw = data.get("events")
    if not isinstance(events_raw, list):
        report.errors.append(f"`{file_path}` must contain an `events` list.")
        report.state = ValidationState.MALFORMED
        return report

    events: List[TimelineEvent] = []
    for idx, ev in enumerate(events_raw):
        if not isinstance(ev, dict):
            report.warnings.append(f"Timeline event at index {idx} is not an object; skipped.")
            continue
        title = str(ev.get("title") or "").strip()
        if not title:
            report.errors.append(f"Timeline event at index {idx} in `{file_path}` is missing `title`.")
            continue
        planned = str(ev["planned_date"]).strip() if ev.get("planned_date") else None
        actual = str(ev["actual_date"]).strip() if ev.get("actual_date") else None
        if planned and parse_iso_date(planned) is None:
            report.warnings.append(f"Timeline event '{title}' has invalid `planned_date` ('{planned}').")
        if actual and parse_iso_date(actual) is None:
            report.warnings.append(f"Timeline event '{title}' has invalid `actual_date` ('{actual}').")

        events.append(
            TimelineEvent(
                event_id=str(ev.get("event_id") or f"EV-{idx + 1}").strip(),
                title=title,
                category=str(ev.get("category") or "Milestone").strip(),
                planned_date=planned,
                actual_date=actual,
                status=str(ev.get("status") or "Not Started").strip(),
                delay_reason=str(ev["delay_reason"]).strip() if ev.get("delay_reason") else None,
                evidence_path=str(ev["evidence_path"]).strip() if ev.get("evidence_path") else None,
            )
        )

    if report.errors:
        report.state = ValidationState.MALFORMED
        return report

    report.parsed_data = events
    return report
