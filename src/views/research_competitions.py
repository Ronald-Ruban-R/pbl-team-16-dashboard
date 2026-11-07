"""
Research, Documentation, Datasets & Competitions Tracker (`src/views/research_competitions.py`).

Indexes and compares artifacts across:
- Research & Literature (`research/`, `literature/`, `papers/`)
- Technical Documentation (`documentation/`, `docs/`, `architecture/`)
- Datasets & Experiments (`datasets/`, `data/`, `experiments/`)
- Competitions & Achievements (`competitions/`, `hackathons/`, `awards/`)
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.security import AccessControlManager, AuthenticatedUser


TRACKED_ARTIFACT_CATEGORIES = (
    "Research & Literature",
    "Technical Documentation",
    "Datasets & Experiments",
    "Competitions & Achievements",
    "Deliverables & Releases",
)


def render_research_competitions_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
) -> None:
    """Render the Research, Documentation & Competitions artifact tracker."""
    st.markdown("## Research, Technical Docs & Competitions")
    st.caption(
        "Track literature reviews, architecture specifications, experimental datasets, and competition entries across repositories."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    # Summary counts across authorized teams
    total_research = 0
    total_docs = 0
    total_datasets = 0
    total_comp = 0
    for r in authorized_repos:
        cat_map = evaluations[r].categorized_files
        total_research += len(cat_map.get("Research & Literature", []))
        total_docs += len(cat_map.get("Technical Documentation", []))
        total_datasets += len(cat_map.get("Datasets & Experiments", []))
        total_comp += len(cat_map.get("Competitions & Achievements", []))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Research & Literature Files", total_research)
    m2.metric("Technical Documentation", total_docs)
    m3.metric("Datasets & Experiments", total_datasets)
    m4.metric("Competitions & Awards", total_comp)

    tab_artifacts, tab_summary = st.tabs(
        [
            "Artifact Directory",
            "Category Breakdown by Team",
        ]
    )

    with tab_artifacts:
        f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.4])
        with f_col1:
            selected_team = (
                authorized_repos[0]
                if len(authorized_repos) == 1
                else st.selectbox(
                    "Filter by Team",
                    options=["All Authorized Teams"] + authorized_repos,
                    format_func=lambda r: (
                        r if r == "All Authorized Teams" else f"{r} — {evaluations[r].display_team_name}"
                    ),
                )
            )
        with f_col2:
            selected_category = st.selectbox(
                "Filter by Category",
                options=["All Categories"] + list(TRACKED_ARTIFACT_CATEGORIES),
            )
        with f_col3:
            keyword = st.text_input("Search Filename", value="", placeholder="e.g., survey, architecture, dataset").strip().lower()

        target_repos = authorized_repos if selected_team == "All Authorized Teams" else [selected_team]
        for r in target_repos:
            access_manager.authorize_repo_access(user, r)

        artifact_rows: List[Dict[str, str]] = []
        for r in target_repos:
            ev = evaluations[r]
            if not ev.snapshot.accessible:
                continue
            for cat_name, entries in ev.categorized_files.items():
                if selected_category != "All Categories" and cat_name != selected_category:
                    continue
                for entry in entries:
                    if keyword and keyword not in entry.path.lower():
                        continue
                    artifact_rows.append(
                        {
                            "Repository": r,
                            "Team": ev.display_team_name,
                            "Category": cat_name,
                            "File Name": entry.name,
                            "Repository Path": entry.path,
                            "Size (KB)": f"{entry.size / 1024.0:.1f}",
                            "GitHub URL": entry.html_url,
                        }
                    )

        if not artifact_rows:
            st.info(
                "No matching artifacts found. Upload files into `research/`, `documentation/`, "
                "`datasets/`, or `competitions/` in your repository."
            )
        else:
            st.dataframe(
                pd.DataFrame(artifact_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "GitHub URL": st.column_config.LinkColumn("GitHub Link", display_text="Open File ↗"),
                },
            )

    with tab_summary:
        matrix_rows = []
        for r in authorized_repos:
            ev = evaluations[r]
            cat_map = ev.categorized_files
            matrix_rows.append(
                {
                    "Repository": r,
                    "Team Name": ev.display_team_name,
                    "Research & Literature": len(cat_map.get("Research & Literature", [])),
                    "Technical Documentation": len(cat_map.get("Technical Documentation", [])),
                    "Datasets & Experiments": len(cat_map.get("Datasets & Experiments", [])),
                    "Competitions & Achievements": len(cat_map.get("Competitions & Achievements", [])),
                    "Deliverables & Releases": len(cat_map.get("Deliverables & Releases", [])),
                    "Meeting Notes": len(cat_map.get("Meeting Notes & Reports", [])),
                }
            )
        st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True, hide_index=True)
