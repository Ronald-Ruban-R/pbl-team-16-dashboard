"""
Progress Calculation, Evidence Verification, Risk Detection, and Team Evaluation Engine.

Computes:
- Dual progress metrics:
  1. Reported Progress (`project/progress.json`)
  2. Verified Progress (weighted milestones + task completion + review deliverables verified in the repository tree)
- Member contribution matrix (assigned, completed, in-progress, blocked, overdue, verified tasks)
- Automated alerts (stale progress, stale commits, overdue tasks, unverified claims, missing required files)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from src.config import (
    CONVENTION_FILES,
    RECOMMENDED_CATEGORY_FOLDERS,
    DashboardConfig,
    format_repo_display_name,
)
from src.github_client import RepoFileEntry, RepositorySnapshot
from src.validators import (
    ActionItemRecord,
    ProgressRecord,
    ProjectMetadata,
    ResponsibilityRecord,
    ReviewRecord,
    TaskItem,
    TeamMember,
    TimelineEvent,
    ValidationIssue,
    parse_progress,
    parse_project_metadata,
    parse_responsibilities,
    parse_review,
    parse_tasks,
    parse_team_members,
    parse_timeline,
)


def parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 date (`YYYY-MM-DD` or full timestamp) into a UTC-aware datetime."""
    if not date_str or not str(date_str).strip():
        return None
    s = str(date_str).strip()
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def is_evidence_verified_in_repo(evidence_ref: Optional[str], repo_paths_lower: Set[str]) -> bool:
    """
    Return True if `evidence_ref` is an external URL (`https://...`) or matches an existing
    file or directory prefix in `repo_paths_lower`.
    """
    if not evidence_ref or not str(evidence_ref).strip():
        return False
    ref = str(evidence_ref).strip()
    if ref.startswith(("https://", "http://")):
        return True
    clean = ref.strip("/").lower()
    if not clean:
        return False
    if clean in repo_paths_lower:
        return True
    prefix = clean + "/"
    return any(p.startswith(prefix) for p in repo_paths_lower)


@dataclass
class AlertItem:
    """Automated risk or governance alert for a team repository."""

    severity: str  # "high", "medium", "low"
    category: str
    message: str


@dataclass
class MemberTaskStats:
    """Per-member task execution and verification breakdown."""

    member_name: str
    role: str
    assigned_count: int = 0
    completed_count: int = 0
    in_progress_count: int = 0
    blocked_count: int = 0
    overdue_count: int = 0
    verified_completed_count: int = 0
    completion_rate_pct: float = 0.0


@dataclass
class TeamEvaluationSummary:
    """Comprehensive evaluated state of a single team repository."""

    repo_name: str
    snapshot: RepositorySnapshot
    metadata: Optional[ProjectMetadata] = None
    members: List[TeamMember] = field(default_factory=list)
    responsibilities: List[ResponsibilityRecord] = field(default_factory=list)
    progress: Optional[ProgressRecord] = None
    timeline: List[TimelineEvent] = field(default_factory=list)
    tasks: List[TaskItem] = field(default_factory=list)
    reviews: Dict[int, ReviewRecord] = field(default_factory=dict)
    readme_text: Optional[str] = None

    reported_progress_pct: float = 0.0
    verified_progress_pct: float = 0.0
    progress_discrepancy_pct: float = 0.0
    milestone_completion_pct: float = 0.0
    task_completion_pct: float = 0.0
    verified_task_completion_pct: float = 0.0
    deliverable_verification_pct: float = 0.0

    total_tasks: int = 0
    completed_tasks: int = 0
    in_progress_tasks: int = 0
    blocked_tasks: int = 0
    delayed_tasks: int = 0
    overdue_tasks: List[TaskItem] = field(default_factory=list)
    unverified_completed_tasks: List[TaskItem] = field(default_factory=list)
    unresolved_action_items: List[ActionItemRecord] = field(default_factory=list)

    days_since_last_commit: Optional[int] = None
    days_since_progress_update: Optional[int] = None
    health_status: str = "Needs Attention"  # "On Track", "Needs Attention", "At Risk"

    categorized_files: Dict[str, List[RepoFileEntry]] = field(default_factory=dict)
    convention_file_presence: Dict[str, bool] = field(default_factory=dict)
    member_stats: List[MemberTaskStats] = field(default_factory=list)
    alerts: List[AlertItem] = field(default_factory=list)
    validation_issues: List[ValidationIssue] = field(default_factory=list)

    @property
    def display_team_name(self) -> str:
        """Return a guaranteed clean, placeholder-free team display name."""
        if self.metadata and self.metadata.team_name:
            return self.metadata.team_name
        return format_repo_display_name(self.repo_name)


def categorize_repository_files(tree_entries: List[RepoFileEntry]) -> Dict[str, List[RepoFileEntry]]:
    """Group repository files into standard PBL categories plus custom top-level folders."""
    categories: Dict[str, List[RepoFileEntry]] = {cat: [] for cat in RECOMMENDED_CATEGORY_FOLDERS}
    folder_to_cat: Dict[str, str] = {}
    for cat, prefixes in RECOMMENDED_CATEGORY_FOLDERS.items():
        for p in prefixes:
            folder_to_cat[p.lower()] = cat

    for entry in tree_entries:
        if entry.item_type != "file":
            continue
        parts = entry.path.strip("/").split("/")
        if len(parts) == 1:
            categories.setdefault("Root Files", []).append(entry)
            continue
        top_folder = parts[0].lower()
        matched_cat = folder_to_cat.get(top_folder)
        if matched_cat:
            categories[matched_cat].append(entry)
        else:
            custom_label = f"Custom Folder: {parts[0]}"
            categories.setdefault(custom_label, []).append(entry)

    return {k: v for k, v in categories.items() if v}


def evaluate_team_repository(
    snapshot: RepositorySnapshot,
    config: DashboardConfig,
    custom_milestone_weights: Optional[Dict[str, float]] = None,
    reference_now: Optional[datetime] = None,
) -> TeamEvaluationSummary:
    """Evaluate a `RepositorySnapshot` into a `TeamEvaluationSummary`."""
    now = reference_now or datetime.now(timezone.utc)
    repo_name = snapshot.repo_name
    summary = TeamEvaluationSummary(repo_name=repo_name, snapshot=snapshot)

    if not snapshot.accessible:
        summary.health_status = "At Risk"
        summary.alerts.append(
            AlertItem(
                severity="high",
                category="Repository Connectivity",
                message=snapshot.error_message or f"Repository `{repo_name}` is unreachable.",
            )
        )
        return summary

    for label, rel_path in CONVENTION_FILES.items():
        f_res = snapshot.convention_raw_files.get(rel_path)
        summary.convention_file_presence[rel_path] = bool(f_res and f_res.exists)

    readme_res = snapshot.convention_raw_files.get(CONVENTION_FILES["readme"])
    if readme_res and readme_res.exists and readme_res.text_content:
        summary.readme_text = readme_res.text_content

    meta_res = snapshot.convention_raw_files.get(CONVENTION_FILES["metadata"])
    if meta_res and meta_res.exists:
        meta_obj, meta_issues = parse_project_metadata(
            meta_res.text_content, repo_name=repo_name, file_path=CONVENTION_FILES["metadata"]
        )
        summary.metadata = meta_obj
        summary.validation_issues.extend(meta_issues)

    mem_res = snapshot.convention_raw_files.get(CONVENTION_FILES["members"])
    if mem_res and mem_res.exists:
        members_list, mem_issues = parse_team_members(
            mem_res.text_content, file_path=CONVENTION_FILES["members"]
        )
        summary.members = members_list
        summary.validation_issues.extend(mem_issues)

    resp_res = snapshot.convention_raw_files.get(CONVENTION_FILES["responsibilities"])
    if resp_res and resp_res.exists:
        resp_list, resp_issues = parse_responsibilities(
            resp_res.text_content, file_path=CONVENTION_FILES["responsibilities"]
        )
        summary.responsibilities = resp_list
        summary.validation_issues.extend(resp_issues)

    prog_res = snapshot.convention_raw_files.get(CONVENTION_FILES["progress"])
    if prog_res and prog_res.exists:
        prog_obj, prog_issues = parse_progress(
            prog_res.text_content, file_path=CONVENTION_FILES["progress"]
        )
        summary.progress = prog_obj
        summary.validation_issues.extend(prog_issues)

    tl_res = snapshot.convention_raw_files.get(CONVENTION_FILES["timeline"])
    if tl_res and tl_res.exists:
        tl_list, tl_issues = parse_timeline(
            tl_res.text_content, file_path=CONVENTION_FILES["timeline"]
        )
        summary.timeline = tl_list
        summary.validation_issues.extend(tl_issues)

    tasks_res = snapshot.convention_raw_files.get(CONVENTION_FILES["tasks"])
    if tasks_res and tasks_res.exists:
        t_list, t_issues = parse_tasks(
            tasks_res.text_content, file_path=CONVENTION_FILES["tasks"]
        )
        summary.tasks = t_list
        summary.validation_issues.extend(t_issues)

    for rel_path, f_res in snapshot.convention_raw_files.items():
        if rel_path.startswith("reviews/") and rel_path.endswith(".json") and f_res.exists:
            default_num = 1
            for d_rev in config.reviews:
                if d_rev.default_file_path.lower() == rel_path.lower():
                    default_num = d_rev.review_number
                    break
            rev_obj, rev_issues = parse_review(
                f_res.text_content, default_review_number=default_num, file_path=rel_path
            )
            summary.validation_issues.extend(rev_issues)
            if rev_obj:
                summary.reviews[rev_obj.review_number] = rev_obj

    summary.categorized_files = categorize_repository_files(snapshot.tree_entries)
    repo_paths_lower: Set[str] = {
        e.path.strip("/").lower() for e in snapshot.tree_entries if e.item_type == "file"
    }

    # Task metrics
    summary.total_tasks = len(summary.tasks)
    total_task_weight = 0.0
    completed_task_weight = 0.0
    verified_task_weight = 0.0

    for t in summary.tasks:
        w = max(0.1, float(t.weight or 1.0))
        total_task_weight += w
        if t.status == "Completed":
            summary.completed_tasks += 1
            completed_task_weight += w
            if is_evidence_verified_in_repo(t.evidence_link, repo_paths_lower):
                verified_task_weight += w
            else:
                summary.unverified_completed_tasks.append(t)
        elif t.status == "In Progress":
            summary.in_progress_tasks += 1
            completed_task_weight += 0.35 * w
            verified_task_weight += 0.25 * w
        elif t.status == "Blocked":
            summary.blocked_tasks += 1
        elif t.status == "Delayed":
            summary.delayed_tasks += 1

        if t.status != "Completed" and t.due_date:
            due_dt = parse_iso_date(t.due_date)
            if due_dt and due_dt < now:
                summary.overdue_tasks.append(t)

    if total_task_weight > 0:
        summary.task_completion_pct = round((completed_task_weight / total_task_weight) * 100.0, 1)
        summary.verified_task_completion_pct = round((verified_task_weight / total_task_weight) * 100.0, 1)

    # Milestone metrics
    if summary.progress and summary.progress.milestones:
        ms_total_w = 0.0
        ms_earned_w = 0.0
        for m in summary.progress.milestones:
            mw = (
                float(custom_milestone_weights[m.milestone_id])
                if custom_milestone_weights and m.milestone_id in custom_milestone_weights
                else max(0.0, float(m.weight))
            )
            ms_total_w += mw
            pct = 100.0 if m.status == "Completed" else float(m.completion_pct or 0.0)
            if m.status == "Completed" and m.evidence_path:
                if not is_evidence_verified_in_repo(m.evidence_path, repo_paths_lower):
                    pct = min(pct, 60.0)
            ms_earned_w += mw * (pct / 100.0)
        if ms_total_w > 0:
            summary.milestone_completion_pct = round((ms_earned_w / ms_total_w) * 100.0, 1)

    # Review deliverable verification
    total_req_deliv = 0
    verified_req_deliv = 0
    for rev in summary.reviews.values():
        for d in rev.deliverables:
            if d.required:
                total_req_deliv += 1
                if d.submitted and is_evidence_verified_in_repo(d.artifact_path, repo_paths_lower):
                    verified_req_deliv += 1
        for ai in rev.action_items:
            if ai.status != "Completed":
                summary.unresolved_action_items.append(ai)

    if total_req_deliv > 0:
        summary.deliverable_verification_pct = round((verified_req_deliv / total_req_deliv) * 100.0, 1)

    # Reported vs Verified overall progress
    if summary.progress and summary.progress.overall_reported_pct is not None:
        summary.reported_progress_pct = round(float(summary.progress.overall_reported_pct), 1)
    else:
        summary.reported_progress_pct = summary.task_completion_pct

    components: List[Tuple[float, float]] = []
    if summary.progress and summary.progress.milestones:
        components.append((summary.milestone_completion_pct, 0.45))
    if summary.total_tasks > 0:
        components.append((summary.verified_task_completion_pct, 0.35))
    if total_req_deliv > 0:
        components.append((summary.deliverable_verification_pct, 0.20))

    if components:
        w_sum = sum(w for _, w in components)
        summary.verified_progress_pct = round(sum(val * w for val, w in components) / w_sum, 1)
    else:
        summary.verified_progress_pct = 0.0

    summary.progress_discrepancy_pct = round(
        summary.reported_progress_pct - summary.verified_progress_pct, 1
    )

    # Per-member contribution statistics
    member_map: Dict[str, MemberTaskStats] = {}
    for m in summary.members:
        member_map[m.name.lower()] = MemberTaskStats(member_name=m.name, role=m.role)

    overdue_ids = {t.task_id for t in summary.overdue_tasks}
    for t in summary.tasks:
        assignee_key = (t.assigned_to or "Unassigned").strip().lower()
        if assignee_key not in member_map:
            member_map[assignee_key] = MemberTaskStats(
                member_name=t.assigned_to or "Unassigned",
                role="Contributor",
            )
        st_obj = member_map[assignee_key]
        st_obj.assigned_count += 1
        if t.status == "Completed":
            st_obj.completed_count += 1
            if is_evidence_verified_in_repo(t.evidence_link, repo_paths_lower):
                st_obj.verified_completed_count += 1
        elif t.status == "In Progress":
            st_obj.in_progress_count += 1
        elif t.status == "Blocked":
            st_obj.blocked_count += 1
        if t.task_id in overdue_ids:
            st_obj.overdue_count += 1

    for st_obj in member_map.values():
        if st_obj.assigned_count > 0:
            st_obj.completion_rate_pct = round(
                (st_obj.completed_count / st_obj.assigned_count) * 100.0, 1
            )
    summary.member_stats = list(member_map.values())

    # Freshness & Risk Alerts
    latest_commit_dt: Optional[datetime] = None
    if snapshot.recent_commits:
        latest_commit_dt = parse_iso_date(snapshot.recent_commits[0].committed_date)
    if not latest_commit_dt and snapshot.pushed_at:
        latest_commit_dt = parse_iso_date(snapshot.pushed_at)

    if latest_commit_dt:
        summary.days_since_last_commit = max(0, (now - latest_commit_dt).days)
        if summary.days_since_last_commit > config.stale_repo_commit_days:
            summary.alerts.append(
                AlertItem(
                    severity="high",
                    category="Stale Repository",
                    message=f"No commits pushed in {summary.days_since_last_commit} days (threshold: {config.stale_repo_commit_days}d).",
                )
            )

    if summary.progress and summary.progress.last_updated:
        prog_dt = parse_iso_date(summary.progress.last_updated)
        if prog_dt:
            summary.days_since_progress_update = max(0, (now - prog_dt).days)
            if summary.days_since_progress_update > config.stale_progress_days:
                summary.alerts.append(
                    AlertItem(
                        severity="medium",
                        category="Stale Progress Report",
                        message=f"`project/progress.json` last updated {summary.days_since_progress_update} days ago.",
                    )
                )

    if not summary.metadata:
        summary.alerts.append(
            AlertItem(
                severity="medium",
                category="Missing Metadata",
                message="`project/metadata.json` is missing or unreadable.",
            )
        )

    if summary.overdue_tasks:
        summary.alerts.append(
            AlertItem(
                severity="high" if len(summary.overdue_tasks) >= 3 else "medium",
                category="Overdue Tasks",
                message=f"{len(summary.overdue_tasks)} task(s) are past their due date.",
            )
        )

    if summary.blocked_tasks > 0:
        summary.alerts.append(
            AlertItem(
                severity="medium",
                category="Blocked Tasks",
                message=f"{summary.blocked_tasks} task(s) are currently marked as Blocked.",
            )
        )

    if summary.unverified_completed_tasks:
        summary.alerts.append(
            AlertItem(
                severity="low",
                category="Unverified Evidence",
                message=f"{len(summary.unverified_completed_tasks)} completed task(s) lack a verified file path in the repository.",
            )
        )

    if summary.progress_discrepancy_pct >= 25.0:
        summary.alerts.append(
            AlertItem(
                severity="medium",
                category="Progress Discrepancy",
                message=(
                    f"Reported progress ({summary.reported_progress_pct:.0f}%) exceeds verified "
                    f"progress ({summary.verified_progress_pct:.0f}%) by {summary.progress_discrepancy_pct:.0f}%."
                ),
            )
        )

    high_alerts = sum(1 for a in summary.alerts if a.severity == "high")
    med_alerts = sum(1 for a in summary.alerts if a.severity == "medium")
    if high_alerts > 0 or med_alerts >= 3:
        summary.health_status = "At Risk"
    elif med_alerts > 0 or len(summary.alerts) >= 2:
        summary.health_status = "Needs Attention"
    else:
        summary.health_status = "On Track"

    return summary
