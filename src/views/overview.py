"""
Overall Mentor Dashboard & All-Teams Cohort Comparison View.

Organized into clean, uncluttered tabs so the mentor sees high-level KPIs immediately
and can switch smoothly between Team Cards, the Comparison Matrix, Visual Charts, and
Cohort Alerts without endless vertical scrolling.
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import AlertItem, TeamEvaluationSummary
from src.config import DashboardConfig


def _attention_badge(level: str) -> str:
    mapping = {
        "On Track": "🟢 On Track",
        "Needs Attention": "🟡 Needs Attention",
        "Critical / Blocked": "🔴 Critical / Blocked",
        "Unavailable": "⚫ Unavailable",
    }
    return mapping.get(level, level)


def render_overview_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    config: DashboardConfig,
) -> None:
    """Render the decluttered Overall Cohort Mentor Dashboard."""
    st.markdown("## 🧭 Cohort Executive Overview")
    st.caption(
        f"Organization: `{config.github_org}` • Project completion is calculated strictly from "
        "reported tasks and milestones (kept separate from GitHub commit activity)."
    )

    total_teams = len(evaluations)
    accessible_teams = sum(1 for e in evaluations.values() if e.snapshot.accessible)
    on_track_teams = sum(1 for e in evaluations.values() if e.attention_level == "On Track")
    needs_attention_teams = sum(
        1 for e in evaluations.values() if e.attention_level in ("Needs Attention", "Critical / Blocked")
    )
    total_overdue_tasks = sum(e.task_metrics.overdue_tasks for e in evaluations.values())
    total_unresolved_ais = sum(len(e.unresolved_action_items) for e in evaluations.values())

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Teams", total_teams)
    col2.metric("Connected", f"{accessible_teams}/{total_teams}")
    col3.metric("On Track", on_track_teams)
    col4.metric("Need Attention", needs_attention_teams)
    col5.metric("Overdue Tasks", total_overdue_tasks)
    col6.metric("Open Action Items", total_unresolved_ais)

    # ------------------------------------------------------------------
    # Collapsible Filter & Sort Bar (keeps the main view clean)
    # ------------------------------------------------------------------
    with st.expander("🔍 Search, Filter & Sort Teams", expanded=False):
        f_col1, f_col2, f_col3 = st.columns([2, 1.5, 1.5])
        with f_col1:
            search_query = st.text_input(
                "Search by team name, domain, or problem statement",
                value="",
                placeholder="e.g., Healthcare, pbl-team-14, Smart Grid...",
            ).strip().lower()
        with f_col2:
            status_filter = st.multiselect(
                "Attention Status",
                options=["On Track", "Needs Attention", "Critical / Blocked", "Unavailable"],
                default=["On Track", "Needs Attention", "Critical / Blocked", "Unavailable"],
            )
        with f_col3:
            sort_by = st.selectbox(
                "Sort Teams By",
                options=[
                    "Repository Name",
                    "Attention Priority",
                    "Reported Progress (High → Low)",
                    "Overdue Tasks (High → Low)",
                ],
            )

    rows: List[Dict] = []
    filtered_evals: List[TeamEvaluationSummary] = []

    for repo_name, ev in evaluations.items():
        if ev.attention_level not in status_filter:
            continue
        team_name = ev.metadata.team_name if ev.metadata else repo_name
        domain = ev.metadata.domain if ev.metadata else "Not Reported"
        title = ev.metadata.project_title if ev.metadata else "Not Reported"
        prob = ev.metadata.problem_statement if ev.metadata else ""

        if search_query:
            haystack = f"{repo_name} {team_name} {domain} {title} {prob}".lower()
            if search_query not in haystack:
                continue

        filtered_evals.append(ev)

        last_commit_str = (
            ev.snapshot.recent_commits[0].committed_date[:10]
            if ev.snapshot.recent_commits
            else (ev.snapshot.pushed_at[:10] if ev.snapshot.pushed_at else "No Commits")
        )
        rows.append(
            {
                "Repository": repo_name,
                "Team Name": team_name,
                "Domain": domain,
                "Project Title": title,
                "Attention Status": _attention_badge(ev.attention_level),
                "Progress Status": ev.progress_display_status,
                "Reported Task %": (
                    f"{ev.task_metrics.reported_completion_pct:.1f}%"
                    if ev.task_metrics.reported_completion_pct is not None
                    else "Not Reported"
                ),
                "Verified Evidence %": (
                    f"{ev.task_metrics.verified_completion_pct:.1f}%"
                    if ev.task_metrics.verified_completion_pct is not None
                    else "Not Reported"
                ),
                "Milestones (Done/Total)": (
                    f"{ev.milestone_metrics.completed_milestones}/{ev.milestone_metrics.total_milestones}"
                    if ev.milestone_metrics.status_label == "Reported"
                    else ev.milestone_metrics.status_label
                ),
                "Overdue Tasks": ev.task_metrics.overdue_tasks if ev.snapshot.accessible else "-",
                "Blocked Tasks": ev.task_metrics.blocked_tasks if ev.snapshot.accessible else "-",
                "Current Review": ev.current_review_label,
                "Open Action Items": len(ev.unresolved_action_items) if ev.snapshot.accessible else "-",
                "Last Progress Report": ev.last_reported_date or "Not Reported",
                "Last GitHub Push (Separate)": last_commit_str if ev.snapshot.accessible else "Unavailable",
                "GitHub URL": ev.snapshot.html_url,
                "_sort_progress": ev.hybrid_progress_pct if ev.hybrid_progress_pct is not None else -1.0,
                "_sort_overdue": ev.task_metrics.overdue_tasks,
                "_sort_attention": {
                    "Critical / Blocked": 0,
                    "Unavailable": 1,
                    "Needs Attention": 2,
                    "On Track": 3,
                }.get(ev.attention_level, 4),
            }
        )

    if sort_by == "Attention Priority":
        rows.sort(key=lambda r: (r["_sort_attention"], r["Repository"]))
    elif sort_by == "Reported Progress (High → Low)":
        rows.sort(key=lambda r: r["_sort_progress"], reverse=True)
    elif sort_by == "Overdue Tasks (High → Low)":
        rows.sort(key=lambda r: r["_sort_overdue"], reverse=True)
    else:
        rows.sort(key=lambda r: r["Repository"])

    all_alerts: List[AlertItem] = []
    for ev in filtered_evals:
        all_alerts.extend(ev.alerts)

    # ------------------------------------------------------------------
    # Organized Tabbed Workspace (No Cluttered Vertical Wall)
    # ------------------------------------------------------------------
    tab_cards, tab_matrix, tab_charts, tab_alerts = st.tabs(
        [
            f"🗂️ Team Cards ({len(filtered_evals)})",
            "📊 Comparison Matrix",
            "📈 Progress Charts",
            f"🔔 Alerts & Warnings ({len(all_alerts)})",
        ]
    )

    with tab_cards:
        if not filtered_evals:
            st.info("No teams match the current filter criteria.")
        else:
            card_cols = st.columns(3)
            for idx, ev in enumerate(filtered_evals):
                with card_cols[idx % 3]:
                    with st.container(border=True):
                        t_name = ev.metadata.team_name if ev.metadata else ev.repo_name
                        st.markdown(f"**{t_name}** (`{ev.repo_name}`)")
                        st.caption(
                            f"{_attention_badge(ev.attention_level)} • "
                            f"{ev.metadata.domain if ev.metadata else 'Domain Not Reported'}"
                        )
                        if ev.hybrid_progress_pct is not None:
                            st.progress(
                                min(1.0, max(0.0, ev.hybrid_progress_pct / 100.0)),
                                text=f"Progress: {ev.hybrid_progress_pct:.1f}%",
                            )
                        else:
                            st.progress(0.0, text=f"Progress: {ev.progress_display_status}")

                        c_a, c_b = st.columns(2)
                        c_a.caption(f"Review: **{ev.current_review_label}**")
                        c_b.caption(
                            f"Tasks: **{ev.task_metrics.completed_tasks}/{ev.task_metrics.total_tasks}** "
                            f"({ev.task_metrics.overdue_tasks} overdue)"
                        )

                        b1, b2, b3 = st.columns(3)
                        if b1.button("Workspace", key=f"nav_ws_{ev.repo_name}", use_container_width=True):
                            st.session_state["selected_repo"] = ev.repo_name
                            st.session_state["active_page"] = (
                                "Individual Team Workspace"
                                if "Individual Team Workspace" in st.session_state.get("_nav_options", [])
                                else "Team 16 Workspace & Profile"
                            )
                            st.rerun()
                        if b2.button("Files", key=f"nav_ex_{ev.repo_name}", use_container_width=True):
                            st.session_state["selected_repo"] = ev.repo_name
                            st.session_state["active_page"] = "Repository Explorer"
                            st.rerun()
                        b3.link_button("GitHub ↗", ev.snapshot.html_url, use_container_width=True)

    with tab_matrix:
        st.caption(
            "Side-by-side comparison of reported progress, verified repository evidence, milestones, "
            "and separate GitHub push dates."
        )
        if rows:
            display_df = pd.DataFrame(rows).drop(
                columns=["_sort_progress", "_sort_overdue", "_sort_attention"]
            )
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "GitHub URL": st.column_config.LinkColumn("GitHub Repo", display_text="Open Repo ↗"),
                },
            )
        else:
            st.info("No teams match the current filter criteria.")

    with tab_charts:
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            st.markdown("##### Reported vs. Evidence-Verified Task Completion (%)")
            chart_rows = [
                {
                    "Team": ev.repo_name,
                    "Reported Completion %": ev.task_metrics.reported_completion_pct,
                    "Evidence-Verified %": ev.task_metrics.verified_completion_pct or 0.0,
                }
                for ev in filtered_evals
                if ev.snapshot.accessible and ev.task_metrics.reported_completion_pct is not None
            ]
            if chart_rows:
                st.bar_chart(pd.DataFrame(chart_rows).set_index("Team"))
            else:
                st.info("No structured task completion percentages reported yet.")

        with chart_col2:
            st.markdown("##### Task Status Breakdown by Team")
            status_rows = [
                {
                    "Team": ev.repo_name,
                    "Completed": ev.task_metrics.completed_tasks,
                    "In Progress": ev.task_metrics.in_progress_tasks,
                    "Blocked": ev.task_metrics.blocked_tasks,
                    "Not Started": ev.task_metrics.not_started_tasks,
                }
                for ev in filtered_evals
                if ev.snapshot.accessible and ev.task_metrics.total_tasks > 0
            ]
            if status_rows:
                st.bar_chart(pd.DataFrame(status_rows).set_index("Team"))
            else:
                st.info("No structured `tasks/tasks.json` records available to chart.")

    with tab_alerts:
        if not all_alerts:
            st.success("All clear! No active alerts across the selected teams.")
        else:
            sev_filter = st.radio(
                "Filter alerts by severity",
                options=["All", "Critical Only", "Warnings & Critical"],
                horizontal=True,
            )
            for alert in all_alerts:
                if sev_filter == "Critical Only" and alert.severity != "critical":
                    continue
                if sev_filter == "Warnings & Critical" and alert.severity not in ("critical", "warning"):
                    continue
                prefix = f"**[{alert.repo_name} • {alert.category}]** {alert.message}"
                if alert.severity == "critical":
                    st.error(prefix)
                elif alert.severity == "warning":
                    st.warning(prefix)
                else:
                    st.info(prefix)
