"""
Timeline & Milestone Management View.

Organized into 2 clean, emoji-free tabs:
1. `Timeline & Schedule Variance`: Unified chronological schedule across `project/timeline.json`,
   milestones (`project/progress.json`), reviews (`reviews/*.json`), and task deadlines (`tasks/tasks.json`).
2. `Edit Timeline Events`: Strictly for `role = "owner"` (Team Lead) to add, update, or remove
   events in `project/timeline.json` directly in GitHub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser
from src.storage import MentorLocalStore
from src.validators import VALID_TASK_STATUSES, parse_iso_date


TIMELINE_CATEGORIES = ("Milestone", "Review", "Competition", "Deliverable", "Task")


def render_timeline_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
    github_client: GitHubCohortClient | None = None,
    local_store: MentorLocalStore | None = None,
) -> None:
    """Render the clean, emoji-free Chronological Timeline & Schedule Slippage view."""
    st.markdown("## Chronological Timeline & Schedule Variance")
    st.caption(
        "Unified schedule across planned milestones, review deadlines, competition dates, and task due dates, "
        "distinguishing planned dates from actual completion dates."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    if len(authorized_repos) > 1:
        scope = st.selectbox(
            "Timeline Scope",
            options=["All Authorized Teams"] + authorized_repos,
            key="timeline_scope_select",
        )
        target_repos = authorized_repos if scope == "All Authorized Teams" else [scope]
    else:
        target_repos = [authorized_repos[0]]

    for r in target_repos:
        access_manager.authorize_repo_access(user, r)

    tab_view, tab_edit = st.tabs(
        [
            "Timeline & Schedule Variance",
            "Edit Timeline Events (project/timeline.json)",
        ]
    )

    with tab_view:
        cat_filter = st.multiselect(
            "Filter by Event Category",
            options=["Milestone", "Review", "Competition", "Deliverable", "Task Deadline"],
            default=["Milestone", "Review", "Competition", "Deliverable", "Task Deadline"],
        )

        today = datetime.now(timezone.utc).date()
        timeline_rows: List[Dict[str, Any]] = []

        for r in target_repos:
            ev = evaluations[r]
            if not ev.snapshot.accessible:
                continue

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
                        "Schedule Variance": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                        "Delay / Change Notes": item.delay_reason or "",
                        "Evidence": item.evidence_path or "",
                        "_sort_date": item.planned_date or "9999-12-31",
                    }
                )

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
                            "Schedule Variance": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                            "Delay / Change Notes": f"Weight: {m.weight:.0f}%",
                            "Evidence": m.evidence_path or "",
                            "_sort_date": m.due_date or "9999-12-31",
                        }
                    )

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
                            "Schedule Variance": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                            "Delay / Change Notes": "",
                            "Evidence": f"reviews/review-{r_num}.json",
                            "_sort_date": planned_str or "9999-12-31",
                        }
                    )

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
                            "Schedule Variance": f"+{slip_days}d delay" if slip_days > 0 else ("On Time" if p_dt else "-"),
                            "Delay / Change Notes": f"Priority: {t.priority}",
                            "Evidence": t.evidence_link or "",
                            "_sort_date": t.due_date or "9999-12-31",
                        }
                    )

        timeline_rows.sort(key=lambda x: (x["_sort_date"], x["Repository"]))

        if not timeline_rows:
            st.info("No chronological timeline events, milestones, or deadlines have been reported yet.")
        else:
            display_df = pd.DataFrame(timeline_rows).drop(columns=["_sort_date"])
            if len(target_repos) == 1 and "Repository" in display_df.columns:
                display_df = display_df.drop(columns=["Repository"])
            st.dataframe(display_df, use_container_width=True, hide_index=True)

            delayed_items = [r for r in timeline_rows if "delay" in str(r["Schedule Variance"])]
            if delayed_items:
                st.warning(
                    f"Schedule Slippage Detected: {len(delayed_items)} milestone(s) or task(s) show a delay relative to planned dates."
                )

    with tab_edit:
        edit_repo = (
            target_repos[0]
            if len(target_repos) == 1
            else st.selectbox("Select Repository to Edit Timeline", options=target_repos, key="tl_edit_repo")
        )
        ev_tl = evaluations[edit_repo]

        if not user.can_edit_repo_metadata(edit_repo):
            st.info(
                "Read-Only Mode: Only Team Leads / Owners (`role = \"owner\"` in Secrets) can edit "
                "`project/timeline.json`. Team members (`role = \"student\"`) have read-only access."
            )
        elif github_client is None:
            st.error("GitHub client is not initialized.")
        elif not ev_tl.snapshot.accessible:
            st.error(f"Repository `{edit_repo}` is not accessible.")
        else:
            existing_ids = [e.event_id for e in ev_tl.timeline_events]
            action = st.radio(
                "Timeline Action",
                options=["Add or Update Event", "Delete Event"] if existing_ids else ["Add or Update Event"],
                horizontal=True,
                key=f"tl_action_{edit_repo}",
            )

            if action == "Delete Event" and existing_ids:
                del_id = st.selectbox(
                    "Select Event to Delete",
                    options=existing_ids,
                    format_func=lambda eid: next((f"{e.event_id}: {e.title} ({e.planned_date or 'TBD'})" for e in ev_tl.timeline_events if e.event_id == eid), eid),
                )
                if st.button(f"Delete Event `{del_id}` and Commit to GitHub"):
                    remaining = [
                        {
                            "event_id": e.event_id,
                            "title": e.title,
                            "category": e.category,
                            "planned_date": e.planned_date,
                            "actual_date": e.actual_date,
                            "status": e.status,
                            "delay_reason": e.delay_reason,
                            "evidence_path": e.evidence_path,
                        }
                        for e in ev_tl.timeline_events
                        if e.event_id != del_id
                    ]
                    ok, msg = github_client.commit_structured_json(
                        repo_name=edit_repo,
                        file_path="project/timeline.json",
                        json_payload={"events": remaining},
                        commit_message=f"chore(timeline): delete event {del_id} by {user.username}",
                        branch=ev_tl.snapshot.default_branch,
                    )
                    if local_store:
                        local_store.log_audit_event(user.username, user.role.value, "delete_timeline_event", edit_repo, msg)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                sel_ev = None
                if existing_ids:
                    pick = st.selectbox(
                        "Select Existing Event to Edit (or '+ New Timeline Event')",
                        options=["+ New Timeline Event"] + existing_ids,
                        format_func=lambda x: x if x.startswith("+") else next((f"{e.event_id}: {e.title}" for e in ev_tl.timeline_events if e.event_id == x), x),
                    )
                    if not pick.startswith("+"):
                        sel_ev = next((e for e in ev_tl.timeline_events if e.event_id == pick), None)

                default_eid = sel_ev.event_id if sel_ev else f"EV-{len(ev_tl.timeline_events) + 1}"
                with st.form(f"form_edit_timeline_{edit_repo}"):
                    c1, c2, c3 = st.columns([1, 2.5, 1.2])
                    e_id = c1.text_input("Event ID", value=default_eid)
                    e_title = c2.text_input("Event / Milestone Title", value=sel_ev.title if sel_ev else "")
                    e_cat = c3.selectbox(
                        "Category",
                        options=list(TIMELINE_CATEGORIES),
                        index=list(TIMELINE_CATEGORIES).index(sel_ev.category) if sel_ev and sel_ev.category in TIMELINE_CATEGORIES else 0,
                    )

                    c4, c5, c6 = st.columns(3)
                    e_planned = c4.text_input("Planned Date (YYYY-MM-DD)", value=sel_ev.planned_date or "" if sel_ev else "")
                    e_actual = c5.text_input("Actual Date (YYYY-MM-DD, Optional)", value=sel_ev.actual_date or "" if sel_ev else "")
                    e_status = c6.selectbox(
                        "Status",
                        options=list(VALID_TASK_STATUSES),
                        index=list(VALID_TASK_STATUSES).index(sel_ev.status) if sel_ev and sel_ev.status in VALID_TASK_STATUSES else 0,
                    )

                    c7, c8 = st.columns(2)
                    e_delay = c7.text_input("Delay / Schedule Change Reason (Optional)", value=sel_ev.delay_reason or "" if sel_ev else "")
                    e_ev = c8.text_input("Evidence Path in Repo", value=sel_ev.evidence_path or "" if sel_ev else "")

                    if st.form_submit_button(f"Commit Event to `project/timeline.json` in `{edit_repo}`"):
                        if not e_id.strip() or not e_title.strip():
                            st.error("Event ID and Title are required.")
                        else:
                            new_ev = {
                                "event_id": e_id.strip(),
                                "title": e_title.strip(),
                                "category": e_cat,
                                "planned_date": e_planned.strip() or None,
                                "actual_date": e_actual.strip() or None,
                                "status": e_status,
                                "delay_reason": e_delay.strip() or None,
                                "evidence_path": e_ev.strip() or None,
                            }
                            updated_evs = []
                            replaced = False
                            for item in ev_tl.timeline_events:
                                if item.event_id == e_id.strip():
                                    updated_evs.append(new_ev)
                                    replaced = True
                                else:
                                    updated_evs.append(
                                        {
                                            "event_id": item.event_id,
                                            "title": item.title,
                                            "category": item.category,
                                            "planned_date": item.planned_date,
                                            "actual_date": item.actual_date,
                                            "status": item.status,
                                            "delay_reason": item.delay_reason,
                                            "evidence_path": item.evidence_path,
                                        }
                                    )
                            if not replaced:
                                updated_evs.append(new_ev)

                            ok, msg = github_client.commit_structured_json(
                                repo_name=edit_repo,
                                file_path="project/timeline.json",
                                json_payload={"events": updated_evs},
                                commit_message=f"chore(timeline): update event {e_id.strip()} in project/timeline.json by {user.username}",
                                branch=ev_tl.snapshot.default_branch,
                            )
                            if local_store:
                                local_store.log_audit_event(user.username, user.role.value, "commit_timeline_json", edit_repo, msg)
                            if ok:
                                st.success(msg)
                                st.rerun()
                            else:
                                st.error(msg)
