"""
Team Progress, Milestones & Task Tracking View.

Organized into clean, focused tabs:
1. `✅ Task Tracker`: Filterable task table with repository evidence verification and direct GitHub links.
2. `🎯 Milestones & Weights`: Milestone completion matrix and custom weight configurator.
3. `👤 Member Workload`: Per-member task assignment and completion breakdown.
4. `✏️ Update Tasks & Progress in GitHub`: Interactive forms to add/update tasks (`tasks/tasks.json`)
   and weekly progress (`project/progress.json`) directly in GitHub when write-back is enabled.
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
    """Render the decluttered, tab-organized Team Progress & Task Tracking view."""
    st.markdown("## ✅ Progress, Milestones & Task Tracking")
    st.caption(
        "Combines student-reported progress (`project/progress.json` and `tasks/tasks.json`) with "
        "automated verification of linked repository evidence paths."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    if len(authorized_repos) > 1:
        scope_options = ["All Authorized Teams"] + authorized_repos
        selected_scope = st.selectbox("Select Scope", options=scope_options)
        target_repos = (
            authorized_repos
            if selected_scope == "All Authorized Teams"
            else [selected_scope]
        )
    else:
        target_repos = [authorized_repos[0]]

    for r in target_repos:
        access_manager.authorize_repo_access(user, r)

    # Top summary metrics across target_repos
    total_t = sum(evaluations[r].task_metrics.total_tasks for r in target_repos)
    done_t = sum(evaluations[r].task_metrics.completed_tasks for r in target_repos)
    inprog_t = sum(evaluations[r].task_metrics.in_progress_tasks for r in target_repos)
    overdue_t = sum(evaluations[r].task_metrics.overdue_tasks for r in target_repos)
    blocked_t = sum(evaluations[r].task_metrics.blocked_tasks for r in target_repos)
    verified_t = sum(evaluations[r].task_metrics.evidence_verified_tasks for r in target_repos)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Total Tasks", total_t)
    m2.metric("Completed", done_t)
    m3.metric("In Progress", inprog_t)
    m4.metric("Evidence Verified", verified_t)
    m5.metric("Overdue", overdue_t)
    m6.metric("Blocked", blocked_t)

    tab_tasks, tab_milestones, tab_members, tab_editor = st.tabs(
        [
            f"✅ Task Tracker ({total_t})",
            "🎯 Milestones & Weights",
            "👤 Member Workload",
            "✏️ Add / Update Tasks & Progress",
        ]
    )

    # ------------------------------------------------------------------
    # Tab 1: Filterable Task Tracker & Evidence Verification
    # ------------------------------------------------------------------
    with tab_tasks:
        with st.expander("🔍 Filter Tasks by Status, Priority, or Evidence Verification", expanded=False):
            f1, f2, f3, f4 = st.columns(4)
            with f1:
                sel_statuses = st.multiselect(
                    "Task Status",
                    options=list(VALID_TASK_STATUSES),
                    default=list(VALID_TASK_STATUSES),
                )
            with f2:
                sel_prios = st.multiselect(
                    "Priority",
                    options=list(VALID_TASK_PRIORITIES),
                    default=list(VALID_TASK_PRIORITIES),
                )
            with f3:
                evidence_filter = st.selectbox(
                    "Evidence Filter",
                    options=[
                        "All Tasks",
                        "Verified Evidence in Repo Only",
                        "Missing / Unverified Evidence Only",
                    ],
                )
            with f4:
                overdue_only = st.checkbox("Show Overdue Tasks Only", value=False)

        today = datetime.now(timezone.utc).date()
        task_rows: List[Dict] = []

        for r in target_repos:
            ev = evaluations[r]
            if not ev.snapshot.accessible or not ev.tasks:
                continue
            repo_paths_lower = {
                e.path.strip("/").lower() for e in ev.snapshot.tree_entries if e.item_type == "file"
            }
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

                row_item: Dict = {}
                if len(target_repos) > 1:
                    row_item["Repository"] = r
                row_item.update(
                    {
                        "Task ID": t.task_id,
                        "Title": t.title,
                        "Assigned To": t.assigned_to,
                        "Priority": t.priority,
                        "Status": t.status,
                        "Start Date": t.start_date or "-",
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
                task_rows.append(row_item)

        if not task_rows:
            st.info("No tasks match the current filter criteria (or `tasks/tasks.json` is not reported).")
        else:
            st.dataframe(
                pd.DataFrame(task_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "GitHub Evidence URL": st.column_config.LinkColumn(
                        "Evidence Link", display_text="Open Evidence ↗"
                    ),
                },
            )

    # ------------------------------------------------------------------
    # Tab 2: Milestone Completion & Weight Configuration
    # ------------------------------------------------------------------
    with tab_milestones:
        ms_rows: List[Dict] = []
        for r in target_repos:
            ev = evaluations[r]
            if not ev.snapshot.accessible:
                ms_rows.append(
                    {
                        "Repository": r,
                        "Progress Status": "Repository Unavailable",
                        "Milestone Weight Sum": "-",
                        "Weights Valid (100%)": "No",
                        "Weighted Milestone %": "Unavailable",
                        "Evidence-Verified Milestone %": "Unavailable",
                        "Reported Task %": "Unavailable",
                        "Evidence-Verified Task %": "Unavailable",
                    }
                )
                continue

            mm = ev.milestone_metrics
            tm = ev.task_metrics
            ms_rows.append(
                {
                    "Repository": r,
                    "Progress Status": ev.progress_display_status,
                    "Milestone Weight Sum": f"{mm.raw_weight_sum:.1f}%" if mm.total_milestones > 0 else "No Milestones",
                    "Weights Valid (100%)": "✅ Yes" if mm.weights_valid_100 else ("⚠️ Normalized" if mm.total_milestones > 0 else "N/A"),
                    "Weighted Milestone %": (
                        f"{mm.weighted_completion_pct:.1f}%"
                        if mm.weighted_completion_pct is not None
                        else "Not Reported"
                    ),
                    "Evidence-Verified Milestone %": (
                        f"{mm.verified_weighted_pct:.1f}%"
                        if mm.verified_weighted_pct is not None
                        else "Not Reported"
                    ),
                    "Reported Task %": (
                        f"{tm.reported_completion_pct:.1f}%"
                        if tm.reported_completion_pct is not None
                        else "Not Reported"
                    ),
                    "Evidence-Verified Task %": (
                        f"{tm.verified_completion_pct:.1f}%"
                        if tm.verified_completion_pct is not None
                        else "Not Reported"
                    ),
                }
            )
            if mm.weight_warning:
                st.warning(f"**[{r}]** {mm.weight_warning}")

        st.dataframe(pd.DataFrame(ms_rows), use_container_width=True, hide_index=True)

        # Single-team milestone detail table + custom weight configurator
        if len(target_repos) == 1:
            single_ev = evaluations[target_repos[0]]
            if single_ev.progress and single_ev.progress.milestones:
                st.markdown("##### Individual Milestones (`project/progress.json`)")
                m_detail_rows = [
                    {
                        "Milestone ID": m.milestone_id,
                        "Title": m.title,
                        "Status": m.status,
                        "Weight (%)": f"{m.weight:.1f}%",
                        "Completion (%)": f"{m.completion_pct:.1f}%" if m.completion_pct is not None else "0.0%",
                        "Due Date": m.due_date or "-",
                        "Completed Date": m.completed_date or "-",
                        "Evidence Path": m.evidence_path or "-",
                    }
                    for m in single_ev.progress.milestones
                ]
                st.dataframe(pd.DataFrame(m_detail_rows), use_container_width=True, hide_index=True)

                with st.expander("⚙️ Customize Milestone Weights", expanded=False):
                    saved_weights: Dict[str, float] = (
                        local_store.get_setting(f"milestone_weights::{single_ev.repo_name}", default={}) or {}
                    )
                    updated_weights: Dict[str, float] = {}
                    w_cols = st.columns(min(4, len(single_ev.progress.milestones)))
                    for idx, m in enumerate(single_ev.progress.milestones):
                        default_w = float(saved_weights.get(m.milestone_id, m.weight))
                        with w_cols[idx % len(w_cols)]:
                            updated_weights[m.milestone_id] = st.number_input(
                                f"{m.milestone_id}: {m.title[:28]}",
                                min_value=0.0,
                                max_value=100.0,
                                value=default_w,
                                step=5.0,
                                key=f"mw_{single_ev.repo_name}_{m.milestone_id}",
                            )
                    total_custom = sum(updated_weights.values())
                    st.caption(f"Configured Total Weight: **{total_custom:.1f}%** (Required: 100.0%)")
                    if abs(total_custom - 100.0) > 0.05:
                        st.error("Total milestone weights must equal 100.0% before saving.")
                    elif st.button("Save Custom Milestone Weights", key=f"save_mw_{single_ev.repo_name}"):
                        local_store.set_setting(
                            f"milestone_weights::{single_ev.repo_name}",
                            updated_weights,
                            updated_by=user.username,
                        )
                        local_store.log_audit_event(
                            username=user.username,
                            role=user.role.value,
                            action="update_milestone_weights",
                            target_repo=single_ev.repo_name,
                            details=f"Updated milestone weights: {updated_weights}",
                        )
                        st.success("Custom milestone weights saved.")
                        st.rerun()

    # ------------------------------------------------------------------
    # Tab 3: Individual Member Workload & Completion Breakdown
    # ------------------------------------------------------------------
    with tab_members:
        member_rows: List[Dict] = []
        for r in target_repos:
            ev = evaluations[r]
            for assignee, counts in ev.task_metrics.member_task_breakdown.items():
                total_m = counts.get("total", 0)
                done_m = counts.get("completed", 0)
                pct_m = round((done_m / total_m) * 100.0, 1) if total_m > 0 else 0.0
                row_m: Dict = {}
                if len(target_repos) > 1:
                    row_m["Repository"] = r
                row_m.update(
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
                member_rows.append(row_m)
        if member_rows:
            st.dataframe(pd.DataFrame(member_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No member task records available to summarize.")

    # ------------------------------------------------------------------
    # Tab 4: Live Two-Way GitHub Task & Progress Editor
    # ------------------------------------------------------------------
    with tab_editor:
        edit_repo = (
            target_repos[0]
            if len(target_repos) == 1
            else st.selectbox("Select Repository to Update", options=target_repos, key="editor_repo_sel")
        )
        ev_edit = evaluations[edit_repo]

        if not user.can_write_feedback(edit_repo) or github_client is None:
            st.info("Sign in with an `owner` or `mentor` account to commit task and progress updates to GitHub.")
        elif not ev_edit.snapshot.accessible:
            st.error(f"Repository `{edit_repo}` is not accessible.")
        else:
            st.caption(
                f"Updates committed here write directly to `{edit_repo}` on GitHub, keeping both the "
                "Team Dashboard and the Mentor Dashboard synchronized."
            )
            editor_mode = st.radio(
                "Select What to Update",
                options=["➕ Add or Edit a Task (`tasks/tasks.json`)", "📈 Update Weekly Progress (`project/progress.json`)"],
                horizontal=True,
            )

            if editor_mode.startswith("➕"):
                existing_ids = [t.task_id for t in ev_edit.tasks]
                mode = st.radio(
                    "Task Action",
                    options=["Update Existing Task", "Create New Task"] if existing_ids else ["Create New Task"],
                    horizontal=True,
                    key=f"task_mode_{edit_repo}",
                )
                selected_existing = None
                if mode == "Update Existing Task" and existing_ids:
                    chosen_id = st.selectbox(
                        "Select Task to Edit",
                        options=existing_ids,
                        format_func=lambda tid: next(
                            (f"{t.task_id}: {t.title} ({t.assigned_to} — {t.status})" for t in ev_edit.tasks if t.task_id == tid),
                            tid,
                        ),
                    )
                    selected_existing = next((t for t in ev_edit.tasks if t.task_id == chosen_id), None)

                member_names = [m.name for m in ev_edit.members] if ev_edit.members else []
                default_id = selected_existing.task_id if selected_existing else f"T-{101 + len(ev_edit.tasks)}"

                with st.form(f"task_editor_form_{edit_repo}"):
                    c_id, c_title = st.columns([1, 3])
                    t_id = c_id.text_input("Task ID", value=default_id)
                    t_title = c_title.text_input(
                        "Task Title",
                        value=selected_existing.title if selected_existing else "",
                        placeholder="e.g., Implement sensor data acquisition module",
                    )
                    t_desc = st.text_area(
                        "Description",
                        value=selected_existing.description if selected_existing else "",
                        height=70,
                    )
                    fa1, fa2, fb1 = st.columns(3)
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
                    t_status = fb1.selectbox(
                        "Status",
                        options=list(VALID_TASK_STATUSES),
                        index=(
                            list(VALID_TASK_STATUSES).index(selected_existing.status)
                            if selected_existing and selected_existing.status in VALID_TASK_STATUSES
                            else 0
                        ),
                    )

                    fb2, fb3, fc1, fc2 = st.columns(4)
                    t_start = fb2.text_input(
                        "Start Date (YYYY-MM-DD)",
                        value=selected_existing.start_date or "" if selected_existing else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    )
                    t_due = fb3.text_input(
                        "Due Date (YYYY-MM-DD)",
                        value=selected_existing.due_date or "" if selected_existing else "",
                    )
                    t_ms = fc1.text_input(
                        "Related Milestone",
                        value=selected_existing.related_milestone or "M1" if selected_existing else "M1",
                    )
                    t_rev = fc2.text_input(
                        "Related Review",
                        value=selected_existing.related_review or "review-1" if selected_existing else "review-1",
                    )
                    t_ev = st.text_input(
                        "Evidence Path in Repository (Required when status is Completed)",
                        value=selected_existing.evidence_link or "" if selected_existing else "",
                        placeholder="e.g., documentation/design.pdf or research/survey.md",
                    )

                    save_task_btn = st.form_submit_button(f"🚀 Commit Task Update to `{edit_repo}` on GitHub")
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
                            for item in ev_edit.tasks:
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
                                repo_name=edit_repo,
                                file_path="tasks/tasks.json",
                                json_payload={"tasks": updated_list},
                                commit_message=f"chore(tasks): update task {t_id.strip()} ({t_status}) via Dashboard",
                                branch=ev_edit.snapshot.default_branch,
                            )
                            local_store.log_audit_event(
                                username=user.username,
                                role=user.role.value,
                                action="commit_tasks_json",
                                target_repo=edit_repo,
                                details=f"Task {t_id.strip()} -> {t_status}: {msg}",
                            )
                            if ok:
                                st.success(f"{msg} Both dashboards are now synchronized!")
                                st.rerun()
                            else:
                                st.error(msg)
            else:
                prog = ev_edit.progress
                with st.form(f"progress_editor_form_{edit_repo}"):
                    p_col1, p_col2 = st.columns([2, 1])
                    cur_phase = p_col1.text_input(
                        "Current Project Phase",
                        value=prog.current_phase if prog else "Phase 1: Problem Scoping & Design",
                    )
                    rep_pct = p_col2.slider(
                        "Overall Reported Progress (%)",
                        min_value=0.0,
                        max_value=100.0,
                        value=float(prog.overall_reported_pct if prog and prog.overall_reported_pct is not None else 0.0),
                        step=5.0,
                    )
                    summary_txt = st.text_area(
                        "Executive Summary",
                        value=prog.summary if prog else "",
                        height=70,
                    )
                    a_col, b_col, n_col = st.columns(3)
                    acc_txt = a_col.text_area(
                        "Completed Since Last Update (1 per line)",
                        value="\n".join(prog.accomplishments_since_last_update) if prog else "",
                        height=95,
                    )
                    blk_txt = b_col.text_area(
                        "Current Blockers (1 per line)",
                        value="\n".join(prog.blockers) if prog else "",
                        height=95,
                    )
                    nxt_txt = n_col.text_area(
                        "Next Steps (1 per line)",
                        value="\n".join(prog.next_steps) if prog else "",
                        height=95,
                    )
                    save_prog_btn = st.form_submit_button(f"🚀 Commit Progress Update to `{edit_repo}` on GitHub")
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
                            repo_name=edit_repo,
                            file_path="project/progress.json",
                            json_payload=prog_payload,
                            commit_message=f"chore(progress): update progress ({rep_pct:.0f}%) via Dashboard",
                            branch=ev_edit.snapshot.default_branch,
                        )
                        if ok:
                            st.success(f"{msg} Both dashboards are now synchronized!")
                            st.rerun()
                        else:
                            st.error(msg)
