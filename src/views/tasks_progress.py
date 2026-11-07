"""
Tasks, Member Contributions, Milestone Weights & Live GitHub Sync View (`src/views/tasks_progress.py`).

Organized into 4 clean, consistent tabs:
1. `Task Board & Filters`: Searchable, filterable task tracker with evidence verification indicators.
2. `Member Contributions`: Per-member workload, completion rate, and verified task breakdown.
3. `Milestone Weights`: Custom local milestone weighting and reported vs. verified comparison.
4. `Edit Tasks, Progress & Milestones`: Owner-only interactive editors for `tasks/tasks.json` and `project/progress.json`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
import plotly.express as px
import streamlit as st

from src.analytics import TeamEvaluationSummary, is_evidence_verified_in_repo
from src.config import DashboardConfig
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser
from src.storage import MentorLocalStore
from src.ui_theme import format_bool_indicator, format_task_status
from src.validators import VALID_TASK_PRIORITIES, VALID_TASK_STATUSES


def render_tasks_progress_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
    local_store: MentorLocalStore,
    github_client: GitHubCohortClient | None = None,
    config: DashboardConfig | None = None,
) -> None:
    """Render the Tasks, Member Contributions & Live GitHub Sync page."""
    st.markdown("## Tasks, Member Contributions & Progress Sync")
    st.caption(
        "Track itemized task execution, verify repository evidence links, analyze member contributions, "
        "and commit task or progress updates directly to GitHub."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    selected_repo = (
        authorized_repos[0]
        if len(authorized_repos) == 1
        else st.selectbox(
            "Select Team",
            options=authorized_repos,
            format_func=lambda r: f"{r} — {evaluations[r].display_team_name}",
            key="tasks_repo_select",
        )
    )
    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    if not ev.snapshot.accessible:
        st.error(f"Repository `{selected_repo}` is unavailable: {ev.snapshot.error_message}")
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Tasks", ev.total_tasks)
    k2.metric("Completed Tasks", f"{ev.completed_tasks} ({ev.task_completion_pct:.0f}%)")
    k3.metric("Verified Task Progress", f"{ev.verified_task_completion_pct:.1f}%")
    k4.metric("Overdue / Blocked", f"{len(ev.overdue_tasks)} overdue · {ev.blocked_tasks} blocked")

    tab_board, tab_members, tab_weights, tab_edit = st.tabs(
        [
            "Task Board & Filters",
            "Member Contributions",
            "Milestone Weights",
            "Edit Tasks, Progress & Milestones",
        ]
    )

    repo_paths_lower = {
        e.path.strip("/").lower() for e in ev.snapshot.tree_entries if e.item_type == "file"
    }

    # ------------------------------------------------------------------
    # Tab 1: Task Board & Filters
    # ------------------------------------------------------------------
    with tab_board:
        if not ev.tasks:
            st.info(
                f"No tasks recorded in `tasks/tasks.json` for `{selected_repo}`. "
                "Team Leads (`role = \"owner\"`) can add tasks in the 'Edit Tasks, Progress & Milestones' tab."
            )
        else:
            f1, f2, f3 = st.columns(3)
            assignees = sorted({t.assigned_to for t in ev.tasks if t.assigned_to})
            with f1:
                status_filter = st.multiselect(
                    "Filter by Status",
                    options=list(VALID_TASK_STATUSES),
                    default=[],
                    placeholder="All Statuses",
                )
            with f2:
                assignee_filter = st.selectbox(
                    "Filter by Assignee",
                    options=["All Assignees"] + assignees,
                )
            with f3:
                prio_filter = st.selectbox(
                    "Filter by Priority",
                    options=["All Priorities"] + list(VALID_TASK_PRIORITIES),
                )

            overdue_ids = {t.task_id for t in ev.overdue_tasks}
            filtered_rows = []
            for t in ev.tasks:
                if status_filter and t.status not in status_filter:
                    continue
                if assignee_filter != "All Assignees" and t.assigned_to != assignee_filter:
                    continue
                if prio_filter != "All Priorities" and t.priority != prio_filter:
                    continue

                verified = is_evidence_verified_in_repo(t.evidence_link, repo_paths_lower)
                filtered_rows.append(
                    {
                        "ID": t.task_id,
                        "Task Title": t.title,
                        "Assignee": t.assigned_to,
                        "Priority": t.priority,
                        "Status": format_task_status(t.status),
                        "Due Date": (
                            f"▲ {t.due_date} (Overdue)"
                            if t.task_id in overdue_ids
                            else (t.due_date or "-")
                        ),
                        "Milestone": t.related_milestone or "-",
                        "Evidence": t.evidence_link or "-",
                        "Repo Verification": (
                            format_bool_indicator(verified, "Verified", "Unverified")
                            if t.status == "Completed"
                            else "-"
                        ),
                    }
                )

            st.dataframe(pd.DataFrame(filtered_rows), use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------
    # Tab 2: Member Contributions
    # ------------------------------------------------------------------
    with tab_members:
        if not ev.member_stats:
            st.info("No member task statistics available yet.")
        else:
            mem_rows = [
                {
                    "Member": ms.member_name,
                    "Role": ms.role,
                    "Assigned": ms.assigned_count,
                    "Completed": ms.completed_count,
                    "Verified Completed": ms.verified_completed_count,
                    "In Progress": ms.in_progress_count,
                    "Blocked": ms.blocked_count,
                    "Overdue": ms.overdue_count,
                    "Completion Rate (%)": ms.completion_rate_pct,
                }
                for ms in ev.member_stats
            ]
            m_df = pd.DataFrame(mem_rows)
            st.dataframe(m_df, use_container_width=True, hide_index=True)

            fig = px.bar(
                m_df,
                x="Member",
                y=["Completed", "In Progress", "Blocked"],
                barmode="group",
                title="Task Execution Breakdown by Team Member",
                color_discrete_map={
                    "Completed": "#16A34A",
                    "In Progress": "#2563EB",
                    "Blocked": "#DC2626",
                },
            )
            fig.update_layout(height=320, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------------
    # Tab 3: Milestone Weights & Progress Discrepancy
    # ------------------------------------------------------------------
    with tab_weights:
        st.markdown("#### Milestone Progress & Custom Weighting")
        if ev.progress and ev.progress.milestones:
            saved_weights = local_store.get_setting(f"milestone_weights::{selected_repo}", default={}) or {}
            ms_rows = [
                {
                    "ID": m.milestone_id,
                    "Milestone": m.title,
                    "Status": format_task_status(m.status),
                    "Repo Weight (%)": m.weight,
                    "Active Weight (%)": saved_weights.get(m.milestone_id, m.weight),
                    "Completion (%)": m.completion_pct,
                    "Evidence Path": m.evidence_path or "-",
                }
                for m in ev.progress.milestones
            ]
            st.dataframe(pd.DataFrame(ms_rows), use_container_width=True, hide_index=True)

            if user.can_write_feedback(selected_repo):
                with st.expander("Customize Local Milestone Evaluation Weights", expanded=False):
                    with st.form(f"custom_ms_weights_{selected_repo}"):
                        new_weights: Dict[str, float] = {}
                        cols = st.columns(min(4, len(ev.progress.milestones)))
                        for idx, m in enumerate(ev.progress.milestones):
                            col = cols[idx % len(cols)]
                            new_weights[m.milestone_id] = col.number_input(
                                f"{m.milestone_id} Weight (%)",
                                min_value=0.0,
                                max_value=100.0,
                                value=float(saved_weights.get(m.milestone_id, m.weight)),
                                step=5.0,
                            )
                        if st.form_submit_button("Save Custom Weights Locally"):
                            local_store.set_setting(f"milestone_weights::{selected_repo}", new_weights)
                            st.success("Saved custom milestone weights.")
                            st.rerun()
        else:
            st.info("No milestones defined in `project/progress.json` yet.")

    # ------------------------------------------------------------------
    # Tab 4: Owner-Only Live GitHub Editors (Tasks, Progress & Milestones)
    # ------------------------------------------------------------------
    with tab_edit:
        _render_tasks_and_progress_editors(
            edit_repo=selected_repo,
            ev_edit=ev,
            user=user,
            github_client=github_client,
            local_store=local_store,
        )


def _render_tasks_and_progress_editors(
    edit_repo: str,
    ev_edit: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient | None,
    local_store: MentorLocalStore,
) -> None:
    if not user.can_edit_repo_metadata(edit_repo):
        st.info(
            f"Signed in as `{user.username}` (`role = \"{user.role.value}\"`). "
            "You have **read-only** access. Only Team Leads (`role = \"owner\"` in Secrets) "
            "can add or update `tasks/tasks.json` and `project/progress.json`."
        )
        return

    if github_client is None or not github_client.auth.is_configured:
        st.warning("Configure a GitHub token (`[github].token`) in Secrets to commit changes to GitHub.")
        return

    st.caption(
        f"Team Lead Write Mode (`role = \"owner\"`): Commit updates directly to `tasks/tasks.json` and "
        f"`project/progress.json` in `{edit_repo}`."
    )

    sub_section = st.radio(
        "Select Section to Update",
        options=[
            "1. Tasks (tasks/tasks.json)",
            "2. Weekly Progress Summary (project/progress.json)",
            "3. Milestones (project/progress.json)",
        ],
        horizontal=True,
        key=f"tp_edit_sec_{edit_repo}",
    )

    if sub_section.startswith("1."):
        _render_tasks_json_editor(edit_repo, ev_edit, user, github_client, local_store)
    elif sub_section.startswith("2."):
        _render_progress_summary_editor(edit_repo, ev_edit, user, github_client, local_store)
    else:
        _render_milestones_json_editor(edit_repo, ev_edit, user, github_client, local_store)


def _render_tasks_json_editor(
    edit_repo: str,
    ev_edit: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore,
) -> None:
    existing_ids = [t.task_id for t in ev_edit.tasks]
    mode_options = ["Add New Task"]
    if existing_ids:
        mode_options.extend(["Update Existing Task", "Delete Task"])

    mode = st.radio("Task Operation", options=mode_options, horizontal=True, key=f"task_op_{edit_repo}")

    if mode == "Delete Task" and existing_ids:
        del_tid = st.selectbox(
            "Select Task to Delete",
            options=existing_ids,
            format_func=lambda tid: next(
                (f"{t.task_id}: {t.title} ({t.assigned_to})" for t in ev_edit.tasks if t.task_id == tid),
                tid,
            ),
        )
        if st.button(f"Delete Task `{del_tid}` & Commit to GitHub"):
            remaining = [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "description": t.description,
                    "assigned_to": t.assigned_to,
                    "priority": t.priority,
                    "status": t.status,
                    "start_date": t.start_date,
                    "due_date": t.due_date,
                    "completed_date": t.completed_date,
                    "related_milestone": t.related_milestone,
                    "related_review": t.related_review,
                    "evidence_link": t.evidence_link,
                    "last_updated": t.last_updated,
                    "weight": t.weight,
                }
                for t in ev_edit.tasks
                if t.task_id != del_tid
            ]
            ok, msg = github_client.commit_structured_json(
                repo_name=edit_repo,
                file_path="tasks/tasks.json",
                json_payload={"tasks": remaining},
                commit_message=f"chore(tasks): delete task {del_tid} by {user.username}",
                branch=ev_edit.snapshot.default_branch,
            )
            local_store.log_audit_event(user.username, user.role.value, "delete_task_json", edit_repo, msg)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        return

    selected_existing = None
    if mode == "Update Existing Task" and existing_ids:
        chosen_id = st.selectbox(
            "Select Task to Edit",
            options=existing_ids,
            format_func=lambda tid: next(
                (f"{t.task_id}: {t.title} ({t.assigned_to} | {t.status})" for t in ev_edit.tasks if t.task_id == tid),
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
            "Assigned To",
            value=(
                selected_existing.assigned_to
                if selected_existing
                else (member_names[0] if member_names else "")
            ),
            placeholder="Team member name",
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

        fc1, fc2, fc3, fc4 = st.columns(4)
        t_start = fc1.text_input(
            "Start Date (YYYY-MM-DD)",
            value=selected_existing.start_date or "" if selected_existing else "",
        )
        t_due = fc2.text_input(
            "Due Date (YYYY-MM-DD)",
            value=selected_existing.due_date or "" if selected_existing else "",
        )
        t_ms = fc3.text_input(
            "Related Milestone",
            value=selected_existing.related_milestone or "M1" if selected_existing else "M1",
        )
        t_weight = fc4.number_input(
            "Task Weight",
            min_value=0.1,
            max_value=10.0,
            value=float(selected_existing.weight if selected_existing else 1.0),
            step=0.5,
        )

        t_ev = st.text_input(
            "Repository Evidence Path or URL",
            value=selected_existing.evidence_link or "" if selected_existing else "",
            placeholder="e.g., research/literature_review.md or src/sensor_node.py",
        )

        if st.form_submit_button("Commit Tasks to `tasks/tasks.json` on GitHub"):
            if not t_id.strip() or not t_title.strip():
                st.error("Task ID and Task Title are required.")
            else:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                comp_date = (
                    today_str
                    if t_status == "Completed"
                    else (selected_existing.completed_date if selected_existing else None)
                )
                new_task_dict = {
                    "task_id": t_id.strip(),
                    "title": t_title.strip(),
                    "description": t_desc.strip(),
                    "assigned_to": t_assignee.strip() or "Unassigned",
                    "priority": t_prio,
                    "status": t_status,
                    "start_date": t_start.strip() or None,
                    "due_date": t_due.strip() or None,
                    "completed_date": comp_date,
                    "related_milestone": t_ms.strip() or None,
                    "related_review": selected_existing.related_review if selected_existing else 1,
                    "evidence_link": t_ev.strip() or None,
                    "last_updated": today_str,
                    "weight": t_weight,
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
                    commit_message=f"chore(tasks): update task {t_id.strip()} ({t_status}) by {user.username}",
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
                    st.success(f"{msg} Both dashboards are now synchronized.")
                    st.rerun()
                else:
                    st.error(msg)


def _default_milestones_list(prog) -> List[Dict]:
    if prog and prog.milestones:
        return [
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
    return [
        {
            "milestone_id": "M1",
            "title": "Problem Validation & Literature Review",
            "status": "Not Started",
            "weight": 20.0,
            "completion_pct": 0.0,
            "due_date": None,
            "completed_date": None,
            "evidence_path": "research/",
        },
        {
            "milestone_id": "M2",
            "title": "Architecture & System Design",
            "status": "Not Started",
            "weight": 25.0,
            "completion_pct": 0.0,
            "due_date": None,
            "completed_date": None,
            "evidence_path": "documentation/",
        },
        {
            "milestone_id": "M3",
            "title": "Prototype Implementation & Testing",
            "status": "Not Started",
            "weight": 30.0,
            "completion_pct": 0.0,
            "due_date": None,
            "completed_date": None,
            "evidence_path": "datasets/",
        },
        {
            "milestone_id": "M4",
            "title": "Final Evaluation & Handover",
            "status": "Not Started",
            "weight": 25.0,
            "completion_pct": 0.0,
            "due_date": None,
            "completed_date": None,
            "evidence_path": "deliverables/",
        },
    ]


def _render_progress_summary_editor(
    edit_repo: str,
    ev_edit: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore,
) -> None:
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
        if st.form_submit_button(f"Commit Progress Summary to `{edit_repo}` on GitHub"):
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            prog_payload = {
                "last_updated": today_str,
                "current_phase": cur_phase.strip(),
                "overall_reported_pct": rep_pct,
                "summary": summary_txt.strip(),
                "accomplishments_since_last_update": [x.strip() for x in acc_txt.splitlines() if x.strip()],
                "blockers": [x.strip() for x in blk_txt.splitlines() if x.strip()],
                "next_steps": [x.strip() for x in nxt_txt.splitlines() if x.strip()],
                "milestones": _default_milestones_list(prog),
            }
            ok, msg = github_client.commit_structured_json(
                repo_name=edit_repo,
                file_path="project/progress.json",
                json_payload=prog_payload,
                commit_message=f"chore(progress): update progress ({rep_pct:.0f}%) by {user.username}",
                branch=ev_edit.snapshot.default_branch,
            )
            local_store.log_audit_event(user.username, user.role.value, "commit_progress_json", edit_repo, msg)
            if ok:
                st.success(f"{msg} Both dashboards are now synchronized.")
                st.rerun()
            else:
                st.error(msg)


def _render_milestones_json_editor(
    edit_repo: str,
    ev_edit: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore,
) -> None:
    prog = ev_edit.progress
    current_ms = _default_milestones_list(prog)
    existing_mids = [m["milestone_id"] for m in current_ms]

    pick_m = st.selectbox(
        "Select Milestone to Edit (or '+ Add New Milestone')",
        options=existing_mids + ["+ Add New Milestone"],
        format_func=lambda x: (
            x
            if x.startswith("+")
            else next(
                (f"{m['milestone_id']}: {m['title']} ({m['status']}, {m['weight']}%)" for m in current_ms if m["milestone_id"] == x),
                x,
            )
        ),
    )
    sel_m = None if pick_m.startswith("+") else next((m for m in current_ms if m["milestone_id"] == pick_m), None)

    with st.form(f"milestone_json_form_{edit_repo}"):
        c1, c2, c3 = st.columns([1, 2.5, 1.2])
        m_id = c1.text_input("Milestone ID", value=sel_m["milestone_id"] if sel_m else f"M{len(current_ms) + 1}")
        m_title = c2.text_input("Milestone Title", value=sel_m["title"] if sel_m else "")
        m_status = c3.selectbox(
            "Status",
            options=list(VALID_TASK_STATUSES),
            index=(
                list(VALID_TASK_STATUSES).index(sel_m["status"])
                if sel_m and sel_m["status"] in VALID_TASK_STATUSES
                else 0
            ),
        )

        c4, c5, c6, c7 = st.columns(4)
        m_weight = c4.number_input(
            "Weight (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(sel_m["weight"] if sel_m else 25.0),
            step=5.0,
        )
        m_pct = c5.number_input(
            "Completion (%)",
            min_value=0.0,
            max_value=100.0,
            value=float(sel_m.get("completion_pct") or 0.0) if sel_m else 0.0,
            step=5.0,
        )
        m_due = c6.text_input("Due Date (YYYY-MM-DD)", value=sel_m.get("due_date") or "" if sel_m else "")
        m_ev = c7.text_input(
            "Evidence Path",
            value=sel_m.get("evidence_path") or "" if sel_m else "deliverables/",
        )

        if st.form_submit_button(f"Save Milestone to `project/progress.json` in `{edit_repo}`"):
            if not m_id.strip() or not m_title.strip():
                st.error("Milestone ID and Title are required.")
            else:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                new_m = {
                    "milestone_id": m_id.strip(),
                    "title": m_title.strip(),
                    "status": m_status,
                    "weight": m_weight,
                    "completion_pct": 100.0 if m_status == "Completed" else m_pct,
                    "due_date": m_due.strip() or None,
                    "completed_date": (
                        today_str
                        if m_status == "Completed"
                        else (sel_m.get("completed_date") if sel_m else None)
                    ),
                    "evidence_path": m_ev.strip() or None,
                }
                updated_ms = []
                replaced = False
                for m in current_ms:
                    if m["milestone_id"] == m_id.strip():
                        updated_ms.append(new_m)
                        replaced = True
                    else:
                        updated_ms.append(m)
                if not replaced:
                    updated_ms.append(new_m)

                prog_payload = {
                    "last_updated": today_str,
                    "current_phase": prog.current_phase if prog else "In Progress",
                    "overall_reported_pct": (
                        prog.overall_reported_pct
                        if prog and prog.overall_reported_pct is not None
                        else 0.0
                    ),
                    "summary": prog.summary if prog else "",
                    "accomplishments_since_last_update": (
                        prog.accomplishments_since_last_update if prog else []
                    ),
                    "blockers": prog.blockers if prog else [],
                    "next_steps": prog.next_steps if prog else [],
                    "milestones": updated_ms,
                }
                ok, msg = github_client.commit_structured_json(
                    repo_name=edit_repo,
                    file_path="project/progress.json",
                    json_payload=prog_payload,
                    commit_message=f"chore(milestones): update milestone {m_id.strip()} in project/progress.json by {user.username}",
                    branch=ev_edit.snapshot.default_branch,
                )
                local_store.log_audit_event(user.username, user.role.value, "commit_milestone_json", edit_repo, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
