"""
Timeline & Milestone Management View.

Combines:
- Project start and target completion dates (`project/metadata.json`)
- Planned milestones (`project/progress.json`)
- Chronological events & competitions (`project/timeline.json`)
- Task deadlines (`tasks/tasks.json`)
- Review dates (`reviews/review-*.json`)

Explicitly distinguishes Planned Dates from Actual Completion Dates and highlights
schedule slippage in days.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.security import AccessControlManager, AuthenticatedUser
from src.validators import parse_iso_date


def render_timeline_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
) -> None:
    """Render the Chronological Timeline & Schedule Slippage view."""
    st.subheader("Chronological Timeline, Milestones & Schedule Slippage")
    st.caption(
        "Unified schedule across planned milestones, review deadlines, competition dates, and task due dates, "
        "distinguishing planned dates from actual completion dates."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    scope = st.selectbox(
        "Timeline Scope",
        options=["All Authorized Teams"] + authorized_repos,
        key="timeline_scope_select",
    )
    target_repos = authorized_repos if scope == "All Authorized Teams" else [scope]
    for r in target_repos:
        access_manager.authorize_repo_access(user, r)

    cat_filter = st.multiselect(
        "Event Types",
        options=["Milestone", "Review", "Competition", "Deliverable", "Task Deadline"],
        default=["Milestone", "Review", "Competition", "Deliverable", "Task Deadline"],
    )

    today = datetime.now(timezone.utc).date()
    timeline_rows: List[Dict[str, Any]] = []

    for r in target_repos:
        ev = evaluations[r]
        if not ev.snapshot.accessible:
            continue

        # 1. Events from `project/timeline.json`
        for item in ev.timeline_events:
            cat = item.category if item.category in ("Milestone", "Review", "Competition", "Deliverable") else "Milestone"
            if cat not in cat_filter:
                continue
            p_dt = parse_iso_date(item.planned_date)
            a_dt = parse_iso_date(item.actual_date)
            slip_days = (a_dt - p_dt).days if (p_dt and a_dt) else (
                (today - p_dt).days if (p_dt and item.status != "Completed" and today > p_dt) else 0
            )
            timeline_rows.append(
                {
                    "Repository": r,
                    "Category": cat,
                    "Event / Milestone": item.title,
                    "Planned Date": item.planned_date or "TBD",
                    "Actual Date": item.actual_date or ("Pending" if item.status != "Completed" else "Not Recorded"),
                    "Status": item.status,
                    "Schedule Variance (Days)": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                    "Delay / Change Notes": item.delay_reason or "",
                    "Evidence": item.evidence_path or "",
                    "_sort_date": item.planned_date or "9999-12-31",
                }
            )

        # 2. Milestones from `project/progress.json`
        if ev.progress and "Milestone" in cat_filter:
            for m in ev.progress.milestones:
                p_dt = parse_iso_date(m.due_date)
                a_dt = parse_iso_date(m.completed_date)
                slip_days = (a_dt - p_dt).days if (p_dt and a_dt) else (
                    (today - p_dt).days if (p_dt and m.status != "Completed" and today > p_dt) else 0
                )
                timeline_rows.append(
                    {
                        "Repository": r,
                        "Category": "Milestone",
                        "Event / Milestone": f"[{m.milestone_id}] {m.title}",
                        "Planned Date": m.due_date or "TBD",
                        "Actual Date": m.completed_date or ("Pending" if m.status != "Completed" else "Not Recorded"),
                        "Status": m.status,
                        "Schedule Variance (Days)": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                        "Delay / Change Notes": f"Weight: {m.weight:.0f}%",
                        "Evidence": m.evidence_path or "",
                        "_sort_date": m.due_date or "9999-12-31",
                    }
                )

        # 3. Reviews from `reviews/review-*.json`
        if "Review" in cat_filter:
            for r_num, rev in sorted(ev.reviews.items()):
                planned_str = rev.submission_deadline or rev.scheduled_date
                p_dt = parse_iso_date(planned_str)
                a_dt = parse_iso_date(rev.submitted_at)
                slip_days = (a_dt - p_dt).days if (p_dt and a_dt) else 0
                timeline_rows.append(
                    {
                        "Repository": r,
                        "Category": "Review",
                        "Event / Milestone": f"Review {r_num}: {rev.review_name}",
                        "Planned Date": planned_str or "TBD",
                        "Actual Date": rev.submitted_at or "Pending",
                        "Status": rev.submission_status,
                        "Schedule Variance (Days)": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                        "Delay / Change Notes": "",
                        "Evidence": f"reviews/review-{r_num}.json",
                        "_sort_date": planned_str or "9999-12-31",
                    }
                )

        # 4. Task deadlines from `tasks/tasks.json`
        if "Task Deadline" in cat_filter:
            for t in ev.tasks:
                p_dt = parse_iso_date(t.due_date)
                a_dt = parse_iso_date(t.completed_date)
                slip_days = (a_dt - p_dt).days if (p_dt and a_dt) else (
                    (today - p_dt).days if (p_dt and t.status != "Completed" and today > p_dt) else 0
                )
                timeline_rows.append(
                    {
                        "Repository": r,
                        "Category": "Task Deadline",
                        "Event / Milestone": f"[{t.task_id}] {t.title} ({t.assigned_to})",
                        "Planned Date": t.due_date or "TBD",
                        "Actual Date": t.completed_date or ("Pending" if t.status != "Completed" else "Not Recorded"),
                        "Status": t.status,
                        "Schedule Variance (Days)": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                        "Delay / Change Notes": f"Priority: {t.priority}",
                        "Evidence": t.evidence_link or "",
                        "_sort_date": t.due_date or "9999-12-31",
                    }
                )

    timeline_rows.sort(key=lambda x: (x["_sort_date"], x["Repository"]))

    if not timeline_rows:
        st.info("No chronological timeline events, milestones, or deadlines have been reported yet.")
        return

    display_df = pd.DataFrame(timeline_rows).drop(columns=["_sort_date"])
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    # Summary of delayed / overdue items
    delayed_items = [r for r in timeline_rows if "delay" in str(r["Schedule Variance (Days)"])]
    if delayed_items:
        st.warning(f"**Schedule Slippage Detected:** {len(delayed_items)} milestone(s) or task(s) show a delay relative to planned dates.")
