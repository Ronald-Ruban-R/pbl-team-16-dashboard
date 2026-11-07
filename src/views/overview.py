"""
Cohort & Team Overview View (`src/views/overview.py`).

Organized into four clean, consistent tabs:
1. `Team Cards`: Scannable status cards with quick workspace navigation.
2. `Comparison Matrix`: Searchable, filterable cohort-wide status table.
3. `Progress Charts`: Dual Reported vs. Verified progress and task breakdown charts.
4. `Alerts & Warnings`: Prioritized governance alerts and JSON validation diagnostics.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.config import DashboardConfig
from src.ui_theme import format_health_badge


def render_overview_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    config: DashboardConfig,
) -> None:
    """Render the Cohort / Team Overview page."""
    is_single = len(evaluations) == 1
    st.markdown("## Team Overview & Health Summary" if is_single else "## Cohort Overview & Team Comparison")
    st.caption(
        "Real-time repository health, reported vs. verified progress, and automated governance checks."
    )

    if not evaluations:
        st.info("No authorized team repositories available.")
        return

    accessible_evals = [ev for ev in evaluations.values() if ev.snapshot.accessible]
    on_track_count = sum(1 for ev in accessible_evals if ev.health_status == "On Track")
    avg_verified = (
        round(sum(ev.verified_progress_pct for ev in accessible_evals) / len(accessible_evals), 1)
        if accessible_evals
        else 0.0
    )
    total_open_tasks = sum(max(0, ev.total_tasks - ev.completed_tasks) for ev in accessible_evals)
    total_alerts = sum(len(ev.alerts) for ev in evaluations.values())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Connected Repositories", f"{len(accessible_evals)} / {len(evaluations)}")
    k2.metric("Teams On Track", f"{on_track_count} / {len(evaluations)}")
    k3.metric("Avg Verified Progress", f"{avg_verified:.1f}%")
    k4.metric("Active Alerts / Open Tasks", f"{total_alerts} alerts · {total_open_tasks} tasks")

    tab_cards, tab_matrix, tab_charts, tab_alerts = st.tabs(
        [
            "Team Cards",
            "Comparison Matrix",
            "Progress Charts",
            "Alerts & Validation",
        ]
    )

    # ------------------------------------------------------------------
    # Tab 1: Team Cards
    # ------------------------------------------------------------------
    with tab_cards:
        cols_per_row = 1 if is_single else 2
        repo_names = list(evaluations.keys())
        for i in range(0, len(repo_names), cols_per_row):
            row_cols = st.columns(cols_per_row)
            for col_idx, repo_name in enumerate(repo_names[i : i + cols_per_row]):
                ev = evaluations[repo_name]
                with row_cols[col_idx]:
                    with st.container(border=True):
                        h_col1, h_col2 = st.columns([2.2, 1])
                        with h_col1:
                            st.markdown(f"#### {ev.display_team_name}")
                            project_title = (
                                ev.metadata.project_title
                                if ev.metadata and ev.metadata.project_title
                                else "Project Title Not Set"
                            )
                            domain_label = (
                                ev.metadata.domain
                                if ev.metadata and ev.metadata.domain
                                else "General Engineering & Innovation"
                            )
                            st.caption(f"`{repo_name}` · {domain_label} · {project_title}")
                        with h_col2:
                            st.markdown(
                                f"<div style='text-align:right; font-weight:600; padding-top:4px;'>"
                                f"{format_health_badge(ev.health_status)}</div>",
                                unsafe_allow_html=True,
                            )

                        if not ev.snapshot.accessible:
                            st.error(ev.snapshot.error_message or "Repository inaccessible.")
                            continue

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Verified", f"{ev.verified_progress_pct:.0f}%")
                        m2.metric("Reported", f"{ev.reported_progress_pct:.0f}%")
                        m3.metric("Tasks Done", f"{ev.completed_tasks}/{ev.total_tasks}")
                        m4.metric(
                            "Last Commit",
                            f"{ev.days_since_last_commit}d ago"
                            if ev.days_since_last_commit is not None
                            else "N/A",
                        )

                        st.progress(
                            min(1.0, max(0.0, ev.verified_progress_pct / 100.0)),
                            text=f"Verified Completion: {ev.verified_progress_pct:.1f}%",
                        )

                        b_col1, b_col2 = st.columns([1.4, 1])
                        with b_col1:
                            phase_str = ev.progress.current_phase if ev.progress else "Phase Not Reported"
                            st.caption(f"Phase: **{phase_str}** · Members: **{len(ev.members)}**")
                        with b_col2:
                            if st.button(
                                f"Open {repo_name}",
                                key=f"open_ws_{repo_name}",
                                use_container_width=True,
                            ):
                                st.session_state["selected_repo"] = repo_name
                                nav_opts = st.session_state.get("_nav_options", [])
                                for target_page in (
                                    "Team Workspace & Profile",
                                    "Individual Team Workspace",
                                ):
                                    if target_page in nav_opts:
                                        st.session_state["active_page"] = target_page
                                        st.rerun()

    # ------------------------------------------------------------------
    # Tab 2: Comparison Matrix
    # ------------------------------------------------------------------
    with tab_matrix:
        rows = []
        for repo_name, ev in evaluations.items():
            rows.append(
                {
                    "Repository": repo_name,
                    "Team Name": ev.display_team_name,
                    "Domain": ev.metadata.domain if ev.metadata else "Not Specified",
                    "Health": format_health_badge(ev.health_status),
                    "Verified (%)": ev.verified_progress_pct,
                    "Reported (%)": ev.reported_progress_pct,
                    "Discrepancy (%)": ev.progress_discrepancy_pct,
                    "Tasks (Done/Total)": f"{ev.completed_tasks}/{ev.total_tasks}",
                    "Overdue Tasks": len(ev.overdue_tasks),
                    "Blocked Tasks": ev.blocked_tasks,
                    "Open Action Items": len(ev.unresolved_action_items),
                    "Last Commit (Days)": (
                        ev.days_since_last_commit if ev.days_since_last_commit is not None else "-"
                    ),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------
    # Tab 3: Progress Charts
    # ------------------------------------------------------------------
    with tab_charts:
        if not accessible_evals:
            st.info("No accessible repositories available to chart.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### Reported vs. Verified Progress (%)")
                chart_df = pd.DataFrame(
                    [
                        {
                            "Team": ev.display_team_name,
                            "Reported Progress (%)": ev.reported_progress_pct,
                            "Verified Progress (%)": ev.verified_progress_pct,
                        }
                        for ev in accessible_evals
                    ]
                )
                fig = go.Figure()
                fig.add_trace(
                    go.Bar(
                        x=chart_df["Team"],
                        y=chart_df["Reported Progress (%)"],
                        name="Reported (%)",
                        marker_color="#64748B",
                    )
                )
                fig.add_trace(
                    go.Bar(
                        x=chart_df["Team"],
                        y=chart_df["Verified Progress (%)"],
                        name="Verified (%)",
                        marker_color="#2563EB",
                    )
                )
                fig.update_layout(
                    barmode="group",
                    yaxis=dict(range=[0, 105], title="Completion (%)"),
                    margin=dict(l=20, r=20, t=20, b=20),
                    height=340,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig, use_container_width=True)

            with c2:
                st.markdown("#### Task Status Distribution")
                task_rows = []
                for ev in accessible_evals:
                    not_started = max(
                        0,
                        ev.total_tasks
                        - ev.completed_tasks
                        - ev.in_progress_tasks
                        - ev.blocked_tasks
                        - ev.delayed_tasks,
                    )
                    for status_label, count_val in [
                        ("Completed", ev.completed_tasks),
                        ("In Progress", ev.in_progress_tasks),
                        ("Blocked", ev.blocked_tasks),
                        ("Delayed", ev.delayed_tasks),
                        ("Not Started", not_started),
                    ]:
                        task_rows.append(
                            {
                                "Team": ev.display_team_name,
                                "Status": status_label,
                                "Tasks": count_val,
                            }
                        )
                t_df = pd.DataFrame(task_rows)
                fig2 = px.bar(
                    t_df,
                    x="Team",
                    y="Tasks",
                    color="Status",
                    barmode="stack",
                    color_discrete_map={
                        "Completed": "#16A34A",
                        "In Progress": "#2563EB",
                        "Blocked": "#DC2626",
                        "Delayed": "#D97706",
                        "Not Started": "#94A3B8",
                    },
                )
                fig2.update_layout(
                    margin=dict(l=20, r=20, t=20, b=20),
                    height=340,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig2, use_container_width=True)

    # ------------------------------------------------------------------
    # Tab 4: Alerts & Schema Diagnostics
    # ------------------------------------------------------------------
    with tab_alerts:
        alert_rows = []
        for repo_name, ev in evaluations.items():
            for a in ev.alerts:
                sev_badge = (
                    "🔴 High"
                    if a.severity == "high"
                    else ("🟡 Medium" if a.severity == "medium" else "⚪ Low")
                )
                alert_rows.append(
                    {
                        "Repository": repo_name,
                        "Team": ev.display_team_name,
                        "Severity": sev_badge,
                        "Category": a.category,
                        "Details": a.message,
                    }
                )
        if alert_rows:
            st.markdown("#### Automated Governance & Freshness Alerts")
            st.dataframe(pd.DataFrame(alert_rows), use_container_width=True, hide_index=True)
        else:
            st.success("✓ All repositories are healthy with no active risk alerts.")

        val_rows = []
        for repo_name, ev in evaluations.items():
            for v in ev.validation_issues:
                val_rows.append(
                    {
                        "Repository": repo_name,
                        "File": v.file_path,
                        "Level": v.severity.upper(),
                        "Diagnostic": v.message,
                    }
                )
        if val_rows:
            with st.expander(f"Metadata & Template Notices ({len(val_rows)})", expanded=False):
                st.dataframe(pd.DataFrame(val_rows), use_container_width=True, hide_index=True)
