"""
Progress calculation, hybrid evidence verification, review comparison, and alert engine.

Core rules enforced:
1. NEVER calculate or infer project completion from commit counts, lines of code, or push activity.
2. Clearly distinguish between:
   - `0.0%` completion (structured tasks/milestones exist and 0% are completed),
   - `"Not Reported"` (no structured `tasks.json` or `progress.json` present),
   - `"Data Malformed"` (JSON validation failed), and
   - `"Repository Unavailable"` (GitHub API retrieval failed).
3. Hybrid verification model: Cross-checks student-reported task/milestone/review evidence links
   against the actual GitHub repository file tree to compute both *Reported Completion %* and
   *Evidence-Verified Completion %*.
4. Validates milestone weight totals and normalizes weights transparently if they do not sum to 100%.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import (
    CONVENTION_FILES,
    DashboardConfig,
    RECOMMENDED_CATEGORY_FOLDERS,
)
from src.github_client import RepoFileEntry, RepositorySnapshot
from src.validators import (
    ActionItemRecord,
    MemberResponsibility,
    ProjectMetadata,
    ReportedProgress,
    ResearchEntry,
    ReviewRecord,
    TaskRecord,
    TeamMember,
    TimelineEvent,
    ValidationReport,
    ValidationState,
    parse_iso_date,
    validate_members_data,
    validate_progress_data,
    validate_project_metadata,
    validate_responsibilities_data,
    validate_review_data,
    validate_tasks_data,
    validate_timeline_data,
)


@dataclass
class AlertItem:
    """Actionable mentor alert for a team."""

    repo_name: str
    team_name: str
    severity: str  # "critical", "warning", "info"
    category: str  # "Access", "Malformed Data", "Missing Deliverable", "Overdue Task", "Stale Update", "Action Item"
    message: str


@dataclass
class TaskProgressMetrics:
    """Quantitative breakdown of team tasks."""

    status_label: str  # "Reported", "Not Reported", "Malformed", "Unavailable"
    total_tasks: int = 0
    completed_tasks: int = 0
    in_progress_tasks: int = 0
    blocked_tasks: int = 0
    not_started_tasks: int = 0
    overdue_tasks: int = 0
    evidence_linked_tasks: int = 0
    evidence_verified_tasks: int = 0
    reported_completion_pct: Optional[float] = None
    verified_completion_pct: Optional[float] = None
    member_task_breakdown: Dict[str, Dict[str, int]] = field(default_factory=dict)


@dataclass
class MilestoneWeightSummary:
    """Summary of weighted milestone completion."""

    status_label: str  # "Reported", "Not Reported", "Invalid Weights"
    total_milestones: int = 0
    completed_milestones: int = 0
    pending_milestones: int = 0
    raw_weight_sum: float = 0.0
    weights_valid_100: bool = False
    weighted_completion_pct: Optional[float] = None
    verified_weighted_pct: Optional[float] = None
    weight_warning: Optional[str] = None


@dataclass
class TeamEvaluationSummary:
    """
    Consolidated, validated view of a single team's repository, metadata, progress,
    tasks, reviews, timeline, categorized files, and mentor alerts.
    """

    repo_name: str
    snapshot: RepositorySnapshot
    validation_reports: Dict[str, ValidationReport] = field(default_factory=dict)
    metadata: Optional[ProjectMetadata] = None
    progress: Optional[ReportedProgress] = None
    members: List[TeamMember] = field(default_factory=list)
    responsibilities: List[MemberResponsibility] = field(default_factory=list)
    tasks: List[TaskRecord] = field(default_factory=list)
    reviews: Dict[int, ReviewRecord] = field(default_factory=dict)
    timeline_events: List[TimelineEvent] = field(default_factory=list)

    # Computed metrics
    task_metrics: TaskProgressMetrics = field(
        default_factory=lambda: TaskProgressMetrics(status_label="Not Reported")
    )
    milestone_metrics: MilestoneWeightSummary = field(
        default_factory=lambda: MilestoneWeightSummary(status_label="Not Reported")
    )
    hybrid_progress_pct: Optional[float] = None
    progress_display_status: str = "Not Reported"
    current_review_label: str = "Not Reported"
    unresolved_action_items: List[Tuple[int, ActionItemRecord]] = field(default_factory=list)
    categorized_files: Dict[str, List[RepoFileEntry]] = field(default_factory=dict)
    custom_top_folders: List[str] = field(default_factory=list)
    research_and_competition_items: List[ResearchEntry] = field(default_factory=list)
    alerts: List[AlertItem] = field(default_factory=list)
    attention_level: str = "On Track"  # "On Track", "Needs Attention", "Critical / Blocked", "Unavailable"
    last_reported_date: Optional[str] = None
    days_since_last_report: Optional[int] = None
    days_since_last_commit: Optional[int] = None


def is_evidence_verified_in_repo(evidence_link: Optional[str], repo_file_paths_lower: Set[str]) -> bool:
    """
    Verify whether an evidence link points to an existing file/directory inside the repository
    or is a valid external URL.
    """
    if not evidence_link or not isinstance(evidence_link, str):
        return False
    cleaned = evidence_link.strip()
    if not cleaned:
        return False
    if cleaned.startswith(("https://", "http://")):
        return True
    norm_path = cleaned.strip("/").lower()
    if norm_path in repo_file_paths_lower:
        return True
    prefix = norm_path + "/"
    return any(p.startswith(prefix) for p in repo_file_paths_lower)


def compute_task_metrics(
    tasks: Optional[List[TaskRecord]],
    tasks_report: ValidationReport,
    repo_accessible: bool,
    repo_file_paths_lower: Set[str],
    reference_date: Optional[date] = None,
) -> TaskProgressMetrics:
    """
    Calculate task completion percentages and per-member breakdown using explicit rules:
    - Each task has a `weight` (default 1.0).
    - `Completed` contributes 100% of its weight to `reported_completion_pct`.
    - `In Progress` contributes 0% to strict completion (never guesses partial percentages).
    - `verified_completion_pct` counts a task as completed ONLY if `status == "Completed"` AND
      its `evidence_link` is non-empty and verified in the repository (or external HTTPS URL).
    - If `tasks.json` is missing, returns `status_label="Not Reported"` and `reported_completion_pct=None`.
    """
    today = reference_date or datetime.now(timezone.utc).date()

    if not repo_accessible:
        return TaskProgressMetrics(status_label="Unavailable")

    if tasks_report.state == ValidationState.MALFORMED:
        return TaskProgressMetrics(status_label="Malformed")

    if tasks_report.state != ValidationState.VALID or tasks is None:
        return TaskProgressMetrics(status_label="Not Reported")

    if len(tasks) == 0:
        return TaskProgressMetrics(
            status_label="Reported",
            total_tasks=0,
            reported_completion_pct=0.0,
            verified_completion_pct=0.0,
        )

    total_weight = 0.0
    completed_weight = 0.0
    verified_weight = 0.0

    completed_count = 0
    in_progress_count = 0
    blocked_count = 0
    not_started_count = 0
    overdue_count = 0
    evidence_linked_count = 0
    evidence_verified_count = 0
    member_map: Dict[str, Dict[str, int]] = {}

    for t in tasks:
        w = max(0.0, float(t.weight or 1.0))
        total_weight += w
        assignee = t.assigned_to or "Unassigned"
        if assignee not in member_map:
            member_map[assignee] = {
                "total": 0,
                "completed": 0,
                "in_progress": 0,
                "blocked": 0,
                "not_started": 0,
                "overdue": 0,
            }
        member_map[assignee]["total"] += 1

        has_evidence = bool(t.evidence_link and t.evidence_link.strip())
        is_verified = is_evidence_verified_in_repo(t.evidence_link, repo_file_paths_lower)
        if has_evidence:
            evidence_linked_count += 1
        if is_verified:
            evidence_verified_count += 1

        if t.status == "Completed":
            completed_count += 1
            completed_weight += w
            member_map[assignee]["completed"] += 1
            if is_verified:
                verified_weight += w
        elif t.status == "In Progress":
            in_progress_count += 1
            member_map[assignee]["in_progress"] += 1
        elif t.status == "Blocked":
            blocked_count += 1
            member_map[assignee]["blocked"] += 1
        else:
            not_started_count += 1
            member_map[assignee]["not_started"] += 1

        if t.status != "Completed" and t.due_date:
            due_dt = parse_iso_date(t.due_date)
            if due_dt and due_dt < today:
                overdue_count += 1
                member_map[assignee]["overdue"] += 1

    reported_pct = round((completed_weight / total_weight) * 100.0, 1) if total_weight > 0 else 0.0
    verified_pct = round((verified_weight / total_weight) * 100.0, 1) if total_weight > 0 else 0.0

    return TaskProgressMetrics(
        status_label="Reported",
        total_tasks=len(tasks),
        completed_tasks=completed_count,
        in_progress_tasks=in_progress_count,
        blocked_tasks=blocked_count,
        not_started_tasks=not_started_count,
        overdue_tasks=overdue_count,
        evidence_linked_tasks=evidence_linked_count,
        evidence_verified_tasks=evidence_verified_count,
        reported_completion_pct=reported_pct,
        verified_completion_pct=verified_pct,
        member_task_breakdown=member_map,
    )


def compute_milestone_metrics(
    progress: Optional[ReportedProgress],
    progress_report: ValidationReport,
    repo_accessible: bool,
    repo_file_paths_lower: Set[str],
    custom_weights: Optional[Dict[str, float]] = None,
) -> MilestoneWeightSummary:
    """
    Calculate weighted milestone completion from `project/progress.json`.
    Validates that milestone weights sum to 100.0% (within 0.05 tolerance).
    If weights do not sum to 100%, normalizes by total positive weight and attaches a clear warning.
    """
    if not repo_accessible:
        return MilestoneWeightSummary(status_label="Unavailable")

    if progress_report.state == ValidationState.MALFORMED:
        return MilestoneWeightSummary(status_label="Malformed")

    if progress_report.state != ValidationState.VALID or progress is None:
        return MilestoneWeightSummary(status_label="Not Reported")

    milestones = progress.milestones
    if not milestones:
        return MilestoneWeightSummary(
            status_label="Reported",
            total_milestones=0,
            weighted_completion_pct=progress.overall_reported_pct,
            verified_weighted_pct=None,
        )

    raw_sum = 0.0
    completed_cnt = 0
    pending_cnt = 0
    weighted_acc = 0.0
    verified_acc = 0.0

    effective_weights: List[float] = []
    for m in milestones:
        w = custom_weights.get(m.milestone_id, m.weight) if custom_weights else m.weight
        if w <= 0:
            w = 1.0
        effective_weights.append(w)
        raw_sum += w

    weights_valid_100 = abs(raw_sum - 100.0) <= 0.05
    warning_msg: Optional[str] = None
    if not weights_valid_100:
        warning_msg = (
            f"Milestone weights sum to {raw_sum:.1f}% instead of 100.0%. "
            "Completion has been normalized proportionally across the defined weights."
        )

    for m, w in zip(milestones, effective_weights):
        if m.status == "Completed":
            completed_cnt += 1
            m_pct = 100.0
        else:
            pending_cnt += 1
            m_pct = float(m.completion_pct) if m.completion_pct is not None else 0.0

        weighted_acc += w * (m_pct / 100.0)
        if m.status == "Completed" and is_evidence_verified_in_repo(m.evidence_path, repo_file_paths_lower):
            verified_acc += w
        elif m.status != "Completed" and is_evidence_verified_in_repo(m.evidence_path, repo_file_paths_lower):
            verified_acc += w * (m_pct / 100.0)

    norm_pct = round((weighted_acc / raw_sum) * 100.0, 1) if raw_sum > 0 else 0.0
    ver_pct = round((verified_acc / raw_sum) * 100.0, 1) if raw_sum > 0 else 0.0

    return MilestoneWeightSummary(
        status_label="Reported",
        total_milestones=len(milestones),
        completed_milestones=completed_cnt,
        pending_milestones=pending_cnt,
        raw_weight_sum=round(raw_sum, 2),
        weights_valid_100=weights_valid_100,
        weighted_completion_pct=norm_pct,
        verified_weighted_pct=ver_pct,
        weight_warning=warning_msg,
    )


def categorize_repository_files(
    repo_name: str,
    org: str,
    default_branch: str,
    tree_entries: List[RepoFileEntry],
) -> Tuple[Dict[str, List[RepoFileEntry]], List[str], List[ResearchEntry]]:
    """
    Dynamically categorize repository files into standard project areas AND identify
    custom top-level folders created by the student team.
    Also extracts structured `ResearchEntry` items for the Research & Competition tracker.
    """
    categories: Dict[str, List[RepoFileEntry]] = {k: [] for k in RECOMMENDED_CATEGORY_FOLDERS}
    categories["Source Code & Implementation"] = []
    categories["Custom & Other Files"] = []

    known_folder_names: Set[str] = set()
    for folder_tuple in RECOMMENDED_CATEGORY_FOLDERS.values():
        for fname in folder_tuple:
            known_folder_names.add(fname.lower())

    custom_top_folders: Set[str] = set()
    research_items: List[ResearchEntry] = []

    for entry in tree_entries:
        parts = entry.path.split("/")
        top_segment = parts[0].lower() if parts else ""

        if entry.item_type == "dir" and len(parts) == 1:
            if top_segment not in known_folder_names and not top_segment.startswith("."):
                custom_top_folders.add(entry.name)
            continue

        if entry.item_type != "file":
            continue

        matched_cat: Optional[str] = None
        for cat_name, prefixes in RECOMMENDED_CATEGORY_FOLDERS.items():
            if top_segment in prefixes or any(seg.lower() in prefixes for seg in parts[:-1]):
                matched_cat = cat_name
                break

        if matched_cat:
            categories[matched_cat].append(entry)
        elif entry.extension in (".py", ".js", ".ts", ".tsx", ".jsx", ".cpp", ".c", ".java", ".go", ".rs", ".sql", ".html", ".css", ".sh"):
            categories["Source Code & Implementation"].append(entry)
        else:
            categories["Custom & Other Files"].append(entry)
            if len(parts) > 1 and top_segment not in known_folder_names and not top_segment.startswith("."):
                custom_top_folders.add(parts[0])

        if matched_cat in ("Research & Literature", "Datasets & Experiments", "Competitions & Achievements", "Technical Documentation"):
            sub_type = {
                "Research & Literature": "Literature Review / Research",
                "Datasets & Experiments": "Dataset / Experiment",
                "Competitions & Achievements": "Competition / Certificate",
                "Technical Documentation": "Technical Documentation",
            }[matched_cat]
            research_items.append(
                ResearchEntry(
                    entry_id=f"{repo_name}:{entry.path}",
                    title=entry.name,
                    category=sub_type,
                    file_path=entry.path,
                    html_url=entry.html_url or f"https://github.com/{org}/{repo_name}/blob/{default_branch}/{entry.path}",
                    phase="Repository Artifact",
                    summary=f"Size: {entry.size:,} bytes | Path: {entry.path}",
                )
            )

    return categories, sorted(custom_top_folders), research_items


def evaluate_team_repository(
    snapshot: RepositorySnapshot,
    config: DashboardConfig,
    custom_milestone_weights: Optional[Dict[str, float]] = None,
    reference_date: Optional[date] = None,
) -> TeamEvaluationSummary:
    """
    Perform complete validation, progress calculation, evidence verification,
    and alert generation for a single team's `RepositorySnapshot`.
    """
    today = reference_date or datetime.now(timezone.utc).date()
    summary = TeamEvaluationSummary(repo_name=snapshot.repo_name, snapshot=snapshot)

    if not snapshot.accessible:
        summary.progress_display_status = "Repository Unavailable"
        summary.attention_level = "Unavailable"
        summary.alerts.append(
            AlertItem(
                repo_name=snapshot.repo_name,
                team_name=snapshot.repo_name,
                severity="critical",
                category="Access",
                message=snapshot.error_message or f"Repository `{snapshot.repo_name}` could not be accessed.",
            )
        )
        return summary

    repo_paths_lower: Set[str] = {
        e.path.strip("/").lower() for e in snapshot.tree_entries if e.item_type == "file"
    }

    def _raw(rel_path: str):
        res = snapshot.convention_raw_files.get(rel_path)
        if res is None:
            return None, False, None
        return res.text_content, res.exists, res.error_message

    meta_report = validate_project_metadata(*_raw(CONVENTION_FILES["metadata"]), file_path=CONVENTION_FILES["metadata"])
    prog_report = validate_progress_data(*_raw(CONVENTION_FILES["progress"]), file_path=CONVENTION_FILES["progress"])
    time_report = validate_timeline_data(*_raw(CONVENTION_FILES["timeline"]), file_path=CONVENTION_FILES["timeline"])
    memb_report = validate_members_data(*_raw(CONVENTION_FILES["members"]), file_path=CONVENTION_FILES["members"])
    resp_report = validate_responsibilities_data(*_raw(CONVENTION_FILES["responsibilities"]), file_path=CONVENTION_FILES["responsibilities"])
    task_report = validate_tasks_data(*_raw(CONVENTION_FILES["tasks"]), file_path=CONVENTION_FILES["tasks"])

    summary.validation_reports = {
        CONVENTION_FILES["metadata"]: meta_report,
        CONVENTION_FILES["progress"]: prog_report,
        CONVENTION_FILES["timeline"]: time_report,
        CONVENTION_FILES["members"]: memb_report,
        CONVENTION_FILES["responsibilities"]: resp_report,
        CONVENTION_FILES["tasks"]: task_report,
    }

    if meta_report.state == ValidationState.VALID:
        summary.metadata = meta_report.parsed_data
    if prog_report.state == ValidationState.VALID:
        summary.progress = prog_report.parsed_data
    if time_report.state == ValidationState.VALID:
        summary.timeline_events = time_report.parsed_data or []
    if memb_report.state == ValidationState.VALID:
        summary.members = memb_report.parsed_data or []
    if resp_report.state == ValidationState.VALID:
        summary.responsibilities = resp_report.parsed_data or []
    if task_report.state == ValidationState.VALID:
        summary.tasks = task_report.parsed_data or []

    team_display_name = (
        summary.metadata.team_name
        if summary.metadata and summary.metadata.team_name
        else snapshot.repo_name
    )

    for path_key, raw_res in sorted(snapshot.convention_raw_files.items()):
        if path_key.startswith("reviews/") and path_key.endswith(".json"):
            r_report = validate_review_data(
                raw_res.text_content,
                raw_res.exists,
                raw_res.error_message,
                file_path=path_key,
            )
            summary.validation_reports[path_key] = r_report
            if r_report.state == ValidationState.VALID and isinstance(r_report.parsed_data, ReviewRecord):
                rev: ReviewRecord = r_report.parsed_data
                summary.reviews[rev.review_number] = rev

    summary.task_metrics = compute_task_metrics(
        summary.tasks if task_report.state == ValidationState.VALID else None,
        task_report,
        snapshot.accessible,
        repo_paths_lower,
        reference_date=today,
    )
    summary.milestone_metrics = compute_milestone_metrics(
        summary.progress if prog_report.state == ValidationState.VALID else None,
        prog_report,
        snapshot.accessible,
        repo_paths_lower,
        custom_weights=custom_milestone_weights,
    )

    t_pct = summary.task_metrics.reported_completion_pct
    m_pct = summary.milestone_metrics.weighted_completion_pct
    if t_pct is not None and m_pct is not None:
        summary.hybrid_progress_pct = round(0.5 * m_pct + 0.5 * t_pct, 1)
        summary.progress_display_status = f"{summary.hybrid_progress_pct:.1f}%"
    elif t_pct is not None:
        summary.hybrid_progress_pct = t_pct
        summary.progress_display_status = f"{t_pct:.1f}% (Tasks)"
    elif m_pct is not None:
        summary.hybrid_progress_pct = m_pct
        summary.progress_display_status = f"{m_pct:.1f}% (Milestones)"
    elif prog_report.state == ValidationState.MALFORMED or task_report.state == ValidationState.MALFORMED:
        summary.hybrid_progress_pct = None
        summary.progress_display_status = "Malformed Metadata"
    else:
        summary.hybrid_progress_pct = None
        summary.progress_display_status = "Not Reported"

    if summary.reviews:
        highest_completed = [
            r for r in summary.reviews.values() if r.submission_status in ("Submitted", "Reviewed")
        ]
        if highest_completed:
            latest_rev = max(highest_completed, key=lambda r: r.review_number)
            summary.current_review_label = f"Review {latest_rev.review_number} ({latest_rev.submission_status})"
        else:
            first_rev = min(summary.reviews.values(), key=lambda r: r.review_number)
            summary.current_review_label = f"Review {first_rev.review_number} ({first_rev.submission_status})"

        for r_num, rev in sorted(summary.reviews.items()):
            for ai in rev.action_items:
                if ai.status != "Completed":
                    summary.unresolved_action_items.append((r_num, ai))
    else:
        summary.current_review_label = "Not Reported"

    cat_files, custom_folders, research_items = categorize_repository_files(
        snapshot.repo_name,
        snapshot.org,
        snapshot.default_branch,
        snapshot.tree_entries,
    )
    summary.categorized_files = cat_files
    summary.custom_top_folders = custom_folders
    summary.research_and_competition_items = research_items

    if summary.progress and summary.progress.last_updated:
        summary.last_reported_date = summary.progress.last_updated
        rep_dt = parse_iso_date(summary.progress.last_updated)
        if rep_dt:
            summary.days_since_last_report = max(0, (today - rep_dt).days)

    latest_commit_date_str: Optional[str] = None
    if snapshot.recent_commits:
        latest_commit_date_str = snapshot.recent_commits[0].committed_date
    elif snapshot.pushed_at:
        latest_commit_date_str = snapshot.pushed_at

    if latest_commit_date_str:
        c_dt = parse_iso_date(latest_commit_date_str)
        if c_dt:
            summary.days_since_last_commit = max(0, (today - c_dt).days)

    for fpath, vrep in summary.validation_reports.items():
        if vrep.state == ValidationState.MALFORMED:
            summary.alerts.append(
                AlertItem(
                    repo_name=snapshot.repo_name,
                    team_name=team_display_name,
                    severity="critical",
                    category="Malformed Data",
                    message=f"Malformed JSON in `{fpath}`: {'; '.join(vrep.errors)}",
                )
            )

    if meta_report.state == ValidationState.MISSING:
        summary.alerts.append(
            AlertItem(
                repo_name=snapshot.repo_name,
                team_name=team_display_name,
                severity="warning",
                category="Missing Deliverable",
                message="Missing `project/metadata.json` (problem statement & project metadata not reported).",
            )
        )

    if prog_report.state == ValidationState.MISSING and task_report.state == ValidationState.MISSING:
        summary.alerts.append(
            AlertItem(
                repo_name=snapshot.repo_name,
                team_name=team_display_name,
                severity="warning",
                category="Missing Deliverable",
                message="Both `project/progress.json` and `tasks/tasks.json` are missing; progress is Not Reported.",
            )
        )

    if summary.task_metrics.overdue_tasks > 0:
        summary.alerts.append(
            AlertItem(
                repo_name=snapshot.repo_name,
                team_name=team_display_name,
                severity="warning",
                category="Overdue Task",
                message=f"{summary.task_metrics.overdue_tasks} task(s) are past their due date and not yet completed.",
            )
        )

    if summary.task_metrics.blocked_tasks > 0:
        summary.alerts.append(
            AlertItem(
                repo_name=snapshot.repo_name,
                team_name=team_display_name,
                severity="critical",
                category="Overdue Task",
                message=f"{summary.task_metrics.blocked_tasks} task(s) are currently marked as Blocked.",
            )
        )

    if summary.days_since_last_report is not None and summary.days_since_last_report > config.stale_progress_days:
        summary.alerts.append(
            AlertItem(
                repo_name=snapshot.repo_name,
                team_name=team_display_name,
                severity="warning",
                category="Stale Update",
                message=f"Progress report (`project/progress.json`) has not been updated in {summary.days_since_last_report} days.",
            )
        )

    if summary.days_since_last_commit is not None and summary.days_since_last_commit > config.stale_repo_commit_days:
        summary.alerts.append(
            AlertItem(
                repo_name=snapshot.repo_name,
                team_name=team_display_name,
                severity="info",
                category="Stale Update",
                message=f"No GitHub commits recorded in the last {summary.days_since_last_commit} days.",
            )
        )

    if summary.unresolved_action_items:
        overdue_ais = [
            ai for _, ai in summary.unresolved_action_items
            if ai.due_date and (parse_iso_date(ai.due_date) or today) < today
        ]
        if overdue_ais:
            summary.alerts.append(
                AlertItem(
                    repo_name=snapshot.repo_name,
                    team_name=team_display_name,
                    severity="critical",
                    category="Action Item",
                    message=f"{len(overdue_ais)} review action item(s) are overdue and unresolved.",
                )
            )
        else:
            summary.alerts.append(
                AlertItem(
                    repo_name=snapshot.repo_name,
                    team_name=team_display_name,
                    severity="info",
                    category="Action Item",
                    message=f"{len(summary.unresolved_action_items)} open review action item(s) pending resolution.",
                )
            )

    if any(a.severity == "critical" for a in summary.alerts):
        summary.attention_level = "Critical / Blocked"
    elif any(a.severity == "warning" for a in summary.alerts) or summary.hybrid_progress_pct is None:
        summary.attention_level = "Needs Attention"
    else:
        summary.attention_level = "On Track"

    return summary
