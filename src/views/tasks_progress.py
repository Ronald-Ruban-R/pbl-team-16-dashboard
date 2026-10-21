"""
Team 16 Progress, Task Control & Live GitHub Synchronization View.

Allows the Team 16 Lead (and authorized team editors) to:
1. Track all tasks, milestones, individual teammate workloads, and evidence verification.
2. Add new tasks, update task statuses (`Not Started`, `In Progress`, `Blocked`, `Completed`),
   reassign tasks to teammates, and link evidence files directly from the browser UI—committing
   the updated `tasks/tasks.json` straight to `PBL-Cohort-X-Teams-13-18/pbl-team-16` on GitHub
   so both the Team 16 Dashboard and the Mentor Dashboard update simultaneously.
3. Update weekly progress summaries, blockers, next steps, and milestone completion percentages
   (`project/progress.json`) directly in GitHub.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import (
    TeamEvaluationSummary,
    is_evidence_verified_in_repo,
)
from src.config import DashboardConfig
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser
from src.storage import MentorLocalStore
from src.validators import VALID_TASK_PRIORITIES, VALID_TASK_STATUSES, parse_iso_date


def render_tasks_progress_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
    local_store: MentorLocalStore,
    github_client: GitHubCohortClient | None = None,
    config: DashboardConfig | None = None,
) -> None:
    """Render the Team 16 Progress, Task Control, and Live GitHub Sync view."""
    st.subheader("Team 16 Progress, Milestones & Interactive Task Control")
    st.caption(
        "Any task or progress update committed here updates `pbl-team-16` on GitHub directly, "
        "synchronizing both your Team 16 Dashboard and the Mentor Dashboard simultaneously."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repository available.")
        return

    selected_repo = authorized_repos[0] if len(authorized_repos) == 1 else st.selectbox("Select Repository", options=authorized_repos)
    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    if not ev.snapshot.accessible:
        st.error(f"Repository `{selected_repo}` is currently inaccessible: {ev.snapshot.error_message}")
        return

    # ------------------------------------------------------------------
    # Section 1: Team Lead Interactive Task Manager (Two-Way GitHub Sync)
    # ------------------------------------------------------------------
    if user.can_write_feedback(selected_repo) and github_client is not None:
        c_form1, c_form2 = st.columns(2)

        with c_form1:
            with st.expander("➕ Add or Update a Task in GitHub (`tasks/tasks.json`)", expanded=False):
                existing_ids = [t.task_id for t in ev.tasks]
                mode = st.radio(
                    "Action",
                    options=["Update Existing Task", "Create New Task"] if existing_ids else ["Create New Task"],
                    horizontal=True,
                    key="t16_task_mode",
                )

                selected_existing = None
                if mode == "Update Existing Task" and existing_ids:
                    chosen_id = st.selectbox(
                        "Select Task to Edit",
                        options=existing_ids,
                        format_func=lambda tid: next(
                            (f"{t.task_id}: {t.title} ({t.assigned_to} — {t.status})" for t in ev.tasks if t.task_id == tid),
                            tid,
                        ),
                    )
                    selected_existing = next((t for t in ev.tasks if t.task_id == chosen_id), None)

                member_names = [m.name for m in ev.members] if ev.members else []
                default_id = selected_existing.task_id if selected_existing else f"T-{101 + len(ev.tasks)}"

                with st.form("t16_task_editor_form"):
                    t_id = st.text_input("Task ID", value=default_id)
                    t_title = st.text_input(
                        "Task Title",
                        value=selected_existing.title if selected_existing else "",
                        placeholder="e.g., Implement sensor data acquisition module",
                    )
                    t_desc = st.text_area(
                        "Description",
                        value=selected_existing.description if selected_existing else "",
                        height=68,
                    )
                    fa1, fa2 = st.columns(2)
                    t_assignee = fa1.text_input(
                        "Assigned To (Teammate Name)",
                        value=(
                            selected_existing.assigned_to
                            if selected_existing
                            else (member_names[0] if member_names else "")
                        ),
                    )
                    t_prio = fa2.selectbox(
                        "Priority",
                        options=list(VALID_TASK_PRIORITIES),
                        index=(
                            list(VALID_TASK_PRIORITIES).index(selected_existing.priority)
                            if selected_existing and selected_existing.priority in VALID_TASK_PRIORITIES
                            else 1
                        ),
                    )

                    fb1, fb2, fb3 = st.columns(3)
                    t_status = fb1.selectbox(
                        "Status",
                        options=list(VALID_TASK_STATUSES),
                        index=(
                            list(VALID_TASK_STATUSES).index(selected_existing.status)
                            if selected_existing and selected_existing.status in VALID_TASK_STATUSES
                            else 0
                        ),
                    )
                    t_start = fb2.text_input(
                        "Start Date (YYYY-MM-DD)",
                        value=selected_existing.start_date or "" if selected_existing else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    )
                    t_due = fb3.text_input(
                        "Due Date (YYYY-MM-DD)",
                        value=selected_existing.due_date or "" if selected_existing else "",
                    )

                    fc1, fc2, fc3 = st.columns(3)
                    t_ms = fc1.text_input(
                        "Related Milestone",
                        value=selected_existing.related_milestone or "M1" if selected_existing else "M1",
                    )
                    t_rev = fc2.text_input(
                        "Related Review",
                        value=selected_existing.related_review or "review-1" if selected_existing else "review-1",
                    )
                    t_ev = fc3.text_input(
                        "Evidence Path in Repo",
                        value=selected_existing.evidence_link or "" if selected_existing else "",
                        placeholder="e.g., documentation/design.pdf",
                    )

                    save_task_btn = st.form_submit_button("🚀 Commit Task Update to GitHub (`pbl-team-16`)")
                    if save_task_btn:
                        if not t_id.strip() or not t_title.strip():
                            st.error("Task ID and Task Title are required.")
                        else:
                            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                            new_task_dict = {
                                "task_id": t_id.strip(),
                                "title": t_title.strip(),
                                "description": t_desc.strip(),
                                "assigned_to": t_assignee.strip() or "Unassigned",
                                "priority": t_prio,
                                "status": t_status,
                                "start_date": t_start.strip() or None,
                                "due_date": t_due.strip() or None,
                                "completed_date": today_str if t_status == "Completed" else None,
                                "related_milestone": t_ms.strip() or None,
                                "related_review": t_rev.strip() or None,
                                "evidence_link": t_ev.strip() or None,
                                "last_updated": today_str,
                                "weight": selected_existing.weight if selected_existing else 1.0,
                            }
                            updated_list = []
                            replaced = False
                            for item in ev.tasks:
                                if item.task_id == t_id.strip():
                                    updated_list.append(new_task_dict)
                                    replaced = True
                                else:
                                    updated_list.append(
                                        {
                                            "task_id": item.task_id,
                                            "title": item.title,
                                            "description": item.description,
                                            "assigned_to": item.assigned_to,
                                            "priority": item.priority,
                                            "status": item.status,
                                            "start_date": item.start_date,
                                            "due_date": item.due_date,
                                            "completed_date": item.completed_date,
                                            "related_milestone": item.related_milestone,
                                            "related_review": item.related_review,
                                            "evidence_link": item.evidence_link,
                                            "last_updated": item.last_updated,
                                            "weight": item.weight,
                                        }
                                    )
                            if not replaced:
                                updated_list.append(new_task_dict)

                            ok, msg = github_client.commit_structured_json(
                                repo_name=selected_repo,
                                file_path="tasks/tasks.json",
                                json_payload={"tasks": updated_list},
                                commit_message=f"chore(tasks): update task {t_id.strip()} ({t_status}) via Team 16 Dashboard",
                                branch=ev.snapshot.default_branch,
                            )
                            local_store.log_audit_event(
                                username=user.username,
                                role=user.role.value,
                                action="commit_tasks_json",
                                target_repo=selected_repo,
                                details=f"Task {t_id.strip()} -> {t_status}: {msg}",
                            )
                            if ok:
                                st.success(f"{msg} Both your Team 16 Dashboard and the Mentor Dashboard are now synced!")
                                st.rerun()
                            else:
                                st.error(msg)

        with c_form2:
            with st.expander("📈 Update Team 16 Weekly Progress & Blockers (`project/progress.json`)", expanded=False):
                prog = ev.progress
                with st.form("t16_progress_editor_form"):
                    cur_phase = st.text_input(
                        "Current Project Phase",
                        value=prog.current_phase if prog else "Phase 1: Problem Scoping & Design",
                    )
                    rep_pct = st.slider(
                        "Overall Reported Progress (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(prog.overall_reported_pct if prog and prog.overall_reported_pct is not None else 0.0),
                        step=5.0,
                    )
                    summary_txt = st.text_area(
                        "Executive Summary",
                        value=prog.summary if prog else "",
                        height=68,
                    )
                    acc_txt = st.text_area(
                        "Completed Since Last Update (one per line)",
                        value="\n".join(prog.accomplishments_since_last_update) if prog else "",
                        height=68,
                    )
                    blk_txt = st.text_area(
                        "Current Blockers (one per line)",
                        value="\n".join(prog.blockers) if prog else "",
                        height=68,
                    )
                    nxt_txt = st.text_area(
                        "Next Steps (one per line)",
                        value="\n".join(prog.next_steps) if prog else "",
                        height=68,
                    )
                    save_prog_btn = st.form_submit_button("🚀 Commit Progress Update to GitHub (`pbl-team-16`)")
                    if save_prog_btn:
                        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                        existing_milestones = (
                            [
                                {
                                    "milestone_id": m.milestone_id,
                                    "title": m.title,
                                    "status": m.status,
                                    "weight": m.weight,
                                    "completion_pct": m.completion_pct,
                                    "due_date": m.due_date,
                                    "completed_date": m.completed_date,
                                    "evidence_path": m.evidence_path,
                                }
                                for m in prog.milestones
                            ]
                            if prog and prog.milestones
                            else [
                                {"milestone_id": "M1", "title": "Problem Validation & Literature Review", "status": "Not Started", "weight": 20.0, "completion_pct": 0.0, "due_date": None, "completed_date": None, "evidence_path": "research/"},
                                {"milestone_id": "M2", "title": "Architecture & System Design", "status": "Not Started", "weight": 25.0, "completion_pct": 0.0, "due_date": None, "completed_date": None, "evidence_path": "documentation/"},
                                {"milestone_id": "M3", "title": "Prototype Implementation & Testing", "status": "Not Started", "weight": 30.0, "completion_pct": 0.0, "due_date": None, "completed_date": None, "evidence_path": "datasets/"},
                                {"milestone_id": "M4", "title": "Final Evaluation & Handover", "status": "Not Started", "weight": 25.0, "completion_pct": 0.0, "due_date": None, "completed_date": None, "evidence_path": "deliverables/"},
                            ]
                        )
                        prog_payload = {
                            "last_updated": today_str,
                            "current_phase": cur_phase.strip(),
                            "overall_reported_pct": rep_pct,
                            "summary": summary_txt.strip(),
                            "accomplishments_since_last_update": [x.strip() for x in acc_txt.splitlines() if x.strip()],
                            "blockers": [x.strip() for x in blk_txt.splitlines() if x.strip()],
                            "next_steps": [x.strip() for x in nxt_txt.splitlines() if x.strip()],
                            "milestones": existing_milestones,
                        }
                        ok, msg = github_client.commit_structured_json(
                            repo_name=selected_repo,
                            file_path="project/progress.json",
                            json_payload=prog_payload,
                            commit_message=f"chore(progress): update progress ({rep_pct:.0f}%) via Team 16 Dashboard",
                            branch=ev.snapshot.default_branch,
                        )
                        if ok:
                            st.success(f"{msg} Both dashboards are now synced!")
                            st.rerun()
                        else:
                            st.error(msg)

    # ------------------------------------------------------------------
    # Section 2: Milestone Weighting & Hybrid Progress Summary
    # ------------------------------------------------------------------
    st.markdown("#### Milestone Completion & Evidence Verification Summary")
    mm = ev.milestone_metrics
    tm = ev.task_metrics
    ms_rows = [
        {
            "Repository": selected_repo,
            "Hybrid Progress": ev.progress_display_status,
            "Milestone Weight Sum": f"{mm.raw_weight_sum:.1f}%" if mm.total_milestones > 0 else "No Milestones",
            "Weights Valid (100%)": "✅ Yes" if mm.weights_valid_100 else ("⚠️ Normalized" if mm.total_milestones > 0 else "N/A"),
            "Weighted Milestone %": f"{mm.weighted_completion_pct:.1f}%" if mm.weighted_completion_pct is not None else "Not Reported",
            "Reported Task %": f"{tm.reported_completion_pct:.1f}%" if tm.reported_completion_pct is not None else "Not Reported",
            "Evidence-Verified Task %": f"{tm.verified_completion_pct:.1f}%" if tm.verified_completion_pct is not None else "Not Reported",
        }
    ]
    st.dataframe(pd.DataFrame(ms_rows), use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------
    # Section 3: Filterable Task Table
    # ------------------------------------------------------------------
    st.markdown("#### Team 16 Task Tracker")
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        sel_statuses = st.multiselect("Task Status", options=list(VALID_TASK_STATUSES), default=list(VALID_TASK_STATUSES))
    with f2:
        sel_prios = st.multiselect("Priority", options=list(VALID_TASK_PRIORITIES), default=list(VALID_TASK_PRIORITIES))
    with f3:
        evidence_filter = st.selectbox(
            "Evidence Verification Filter",
            options=["All Tasks", "Verified Evidence in Repo Only", "Missing / Unverified Evidence Only"],
        )
    with f4:
        overdue_only = st.checkbox("Show Overdue Tasks Only", value=False)

    today = datetime.now(timezone.utc).date()
    repo_paths_lower = {
        e.path.strip("/").lower() for e in ev.snapshot.tree_entries if e.item_type == "file"
    }
    task_rows: List[Dict] = []
    for t in ev.tasks:
        if t.status not in sel_statuses or t.priority not in sel_prios:
            continue
        verified = is_evidence_verified_in_repo(t.evidence_link, repo_paths_lower)
        if evidence_filter == "Verified Evidence in Repo Only" and not verified:
            continue
        if evidence_filter == "Missing / Unverified Evidence Only" and verified:
            continue

        due_dt = parse_iso_date(t.due_date)
        is_overdue = bool(t.status != "Completed" and due_dt and due_dt < today)
        if overdue_only and not is_overdue:
            continue

        ev_url = ""
        if t.evidence_link:
            if t.evidence_link.startswith(("https://", "http://")):
                ev_url = t.evidence_link
            else:
                ev_url = f"{ev.snapshot.html_url}/blob/{ev.snapshot.default_branch}/{t.evidence_link.lstrip('/')}"

        task_rows.append(
            {
                "Task ID": t.task_id,
                "Title": t.title,
                "Assigned To": t.assigned_to,
                "Priority": t.priority,
                "Status": t.status,
                "Due Date": t.due_date or "-",
                "Overdue": "⚠️ Overdue" if is_overdue else "No",
                "Milestone": t.related_milestone or "-",
                "Review": t.related_review or "-",
                "Evidence Path": t.evidence_link or "None",
                "Evidence Verified": "✅ Verified" if verified else "❌ Unverified",
                "Last Updated": t.last_updated or "-",
                "GitHub Evidence URL": ev_url,
            }
        )

    if not task_rows:
        st.info("No tasks match the current filter criteria.")
    else:
        st.dataframe(
            pd.DataFrame(task_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "GitHub Evidence URL": st.column_config.LinkColumn("Evidence Link", display_text="Open Evidence ↗"),
            },
        )

    # ------------------------------------------------------------------
    # Section 4: Individual Teammate Workload Matrix
    # ------------------------------------------------------------------
    st.markdown("#### Individual Teammate Workload & Completion Matrix")
    member_rows: List[Dict] = []
    for assignee, counts in ev.task_metrics.member_task_breakdown.items():
        total_m = counts.get("total", 0)
        done_m = counts.get("completed", 0)
        pct_m = round((done_m / total_m) * 100.0, 1) if total_m > 0 else 0.0
        member_rows.append(
            {
                "Team Member": assignee,
                "Total Assigned": total_m,
                "Completed": done_m,
                "In Progress": counts.get("in_progress", 0),
                "Blocked": counts.get("blocked", 0),
                "Not Started": counts.get("not_started", 0),
                "Overdue": counts.get("overdue", 0),
                "Individual Completion %": f"{pct_m:.1f}%",
            }
        )
    if member_rows:
        st.dataframe(pd.DataFrame(member_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No member task records available yet.")
