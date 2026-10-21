"""
Research, Datasets, Technical Documentation & Competition Tracking View.

Organizes and filters team research, literature reviews, datasets, experimental records,
competition entries, certificates, and technical documentation across all six teams
without fabricating citations or requiring mentors to download every file.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.security import AccessControlManager, AuthenticatedUser


def render_research_competitions_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
) -> None:
    """Render the Research, Datasets & Competition Tracker view."""
    st.subheader("Research, Datasets, Technical Docs & Competition Tracker")
    st.caption(
        "Centralized index of literature reviews, datasets, experiments, technical documentation, and "
        "competition records discovered across team repositories. Never fabricates citations or awards."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    c1, c2, c3 = st.columns([1.5, 1.5, 2])
    with c1:
        selected_repos = st.multiselect(
            "Filter by Team Repository",
            options=authorized_repos,
            default=authorized_repos,
        )
    with c2:
        categories = [
            "Literature Review / Research",
            "Dataset / Experiment",
            "Competition / Certificate",
            "Technical Documentation",
        ]
        selected_cats = st.multiselect(
            "Filter by Category",
            options=categories,
            default=categories,
        )
    with c3:
        keyword = st.text_input(
            "Search by filename, path, or topic",
            value="",
            placeholder="e.g., ieee, benchmark, dataset, hackathon, certificate...",
        ).strip().lower()

    for r in selected_repos:
        access_manager.authorize_repo_access(user, r)

    rows: List[Dict[str, Any]] = []
    for r in selected_repos:
        ev = evaluations[r]
        if not ev.snapshot.accessible:
            continue
        team_name = ev.metadata.team_name if ev.metadata else r
        domain = ev.metadata.domain if ev.metadata else "Not Reported"

        for item in ev.research_and_competition_items:
            if item.category not in selected_cats:
                continue
            if keyword and keyword not in f"{item.title} {item.file_path} {team_name} {domain}".lower():
                continue
            rows.append(
                {
                    "Repository": r,
                    "Team Name": team_name,
                    "Domain": domain,
                    "Category": item.category,
                    "Artifact Name": item.title,
                    "Repository Path": item.file_path,
                    "Details": item.summary or "",
                    "GitHub URL": item.html_url,
                }
            )

    # Summary KPI cards by category
    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Research & Literature Files",
        sum(1 for r in rows if r["Category"] == "Literature Review / Research"),
    )
    k2.metric(
        "Datasets & Experiments",
        sum(1 for r in rows if r["Category"] == "Dataset / Experiment"),
    )
    k3.metric(
        "Competitions & Certificates",
        sum(1 for r in rows if r["Category"] == "Competition / Certificate"),
    )
    k4.metric(
        "Technical Documentation",
        sum(1 for r in rows if r["Category"] == "Technical Documentation"),
    )

    if not rows:
        st.info(
            "No research, dataset, technical documentation, or competition files matched the current filters."
        )
        return

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "GitHub URL": st.column_config.LinkColumn("GitHub Link", display_text="Open on GitHub ↗"),
        },
    )

    # Quick-preview selector
    st.markdown("#### Quick In-App Document Preview")
    preview_options = [f"{r['Repository']} :: {r['Repository Path']}" for r in rows]
    chosen = st.selectbox(
        "Select a research document, dataset, or certificate to preview in the Repository Explorer",
        options=[""] + preview_options,
        format_func=lambda x: "Choose an artifact to preview..." if x == "" else x,
    )
    if chosen:
        if st.button("Open Artifact in Repository Explorer"):
            repo_target, path_target = chosen.split(" :: ", 1)
            folder = path_target.rsplit("/", 1)[0] if "/" in path_target else ""
            st.session_state["selected_repo"] = repo_target
            st.session_state["explorer_path"] = folder
            st.session_state["explorer_selected_file"] = path_target
            st.session_state["active_page"] = "Repository Explorer"
            st.rerun()
