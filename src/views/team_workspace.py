"""
Individual Team Workspace View.

Displays a single team's complete profile, problem statement, objectives, member roles
and responsibilities, accomplishments since the last update, categorized project files
(including custom folders), task/milestone progress, recent GitHub commits, and metadata
validation health.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary, is_evidence_verified_in_repo
from src.config import CONVENTION_FILES
from src.security import AccessControlManager, AuthenticatedUser, sanitize_markdown_for_display
from src.validators import ValidationState


def render_team_workspace_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
) -> None:
    """Render the dedicated workspace for a selected team."""
    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("You are not authorized to access any team repositories.")
        return

    default_repo = st.session_state.get("selected_repo")
    if default_repo not in authorized_repos:
        default_repo = authorized_repos[0]

    top_col1, top_col2 = st.columns([3, 1])
    with top_col1:
        selected_repo = st.selectbox(
            "Select Team Workspace",
            options=authorized_repos,
            index=authorized_repos.index(default_repo),
            format_func=lambda r: (
                f"{r} — {evaluations[r].metadata.team_name}"
                if evaluations[r].metadata
                else r
            ),
        )
        st.session_state["selected_repo"] = selected_repo

    # Server-side RBAC enforcement
    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    with top_col2:
        st.write("")
        st.link_button("Open Private GitHub Repo ↗", ev.snapshot.html_url, use_container_width=True)

    if not ev.snapshot.accessible:
        st.error(
            f"Repository `{selected_repo}` is currently inaccessible: {ev.snapshot.error_message}"
        )
        return

    # ------------------------------------------------------------------
    # Section 1: Team Profile & Problem Statement
    # ------------------------------------------------------------------
    with st.container(border=True):
        meta = ev.metadata
        if meta:
            st.markdown(f"### {meta.project_title}")
            p1, p2, p3, p4 = st.columns(4)
            p1.markdown(f"**Team:** {meta.team_name} (`{ev.repo_name}`)")
            p2.markdown(f"**Domain:** {meta.domain}")
            p3.markdown(f"**Timeline:** {meta.start_date or 'TBD'} → {meta.target_completion_date or 'TBD'}")
            p4.markdown(f"**Mentors:** {meta.lead_mentor or 'Assigned Mentor'}{f', {meta.co_mentor}' if meta.co_mentor else ''}")

            st.markdown("**Problem Statement**")
            st.info(meta.problem_statement)

            obj_col, out_col = st.columns(2)
            with obj_col:
                st.markdown("**Project Objectives**")
                if meta.objectives:
                    for obj in meta.objectives:
                        st.markdown(f"- {obj}")
                else:
                    st.caption("No objectives listed in `project/metadata.json`.")
            with out_col:
                st.markdown("**Expected Outcomes**")
                if meta.expected_outcomes:
                    for out in meta.expected_outcomes:
                        st.markdown(f"- {out}")
                else:
                    st.caption("No expected outcomes listed in `project/metadata.json`.")
        else:
            st.warning(
                f"`{CONVENTION_FILES['metadata']}` is missing or malformed in `{selected_repo}`. "
                "Displaying repository-level information."
            )
            if ev.snapshot.description:
                st.markdown(f"**Repository Description:** {ev.snapshot.description}")

    # ------------------------------------------------------------------
    # Section 2: Progress Snapshot & Recent Update vs. GitHub Activity
    # ------------------------------------------------------------------
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Hybrid Progress", ev.progress_display_status)
    k2.metric(
        "Reported Tasks Done",
        f"{ev.task_metrics.completed_tasks}/{ev.task_metrics.total_tasks}"
        if ev.task_metrics.status_label == "Reported"
        else ev.task_metrics.status_label,
    )
    k3.metric(
        "Evidence-Verified %",
        f"{ev.task_metrics.verified_completion_pct:.1f}%"
        if ev.task_metrics.verified_completion_pct is not None
        else "Not Reported",
    )
    k4.metric("Overdue / Blocked", f"{ev.task_metrics.overdue_tasks} / {ev.task_metrics.blocked_tasks}")
    k5.metric("Current Review", ev.current_review_label)

    tab_profile, tab_progress, tab_files, tab_readme, tab_health = st.tabs(
        [
            "👥 Members & Responsibilities",
            "📈 Progress, Updates & Commits",
            "🗂️ Categorized Project Artifacts",
            "📖 Repository README",
            "🛡️ Metadata Validation Health",
        ]
    )

    # ------------------------------------------------------------------
    # Tab 1: Members & Individual Responsibilities
    # ------------------------------------------------------------------
    with tab_profile:
        st.markdown("#### Team Members & Assigned Responsibilities")
        resp_by_id = {r.member_id: r for r in ev.responsibilities}
        resp_by_name = {r.member_name.lower(): r for r in ev.responsibilities}

        if ev.members:
            member_rows = []
            for m in ev.members:
                r_match = resp_by_id.get(m.member_id) or resp_by_name.get(m.name.lower())
                task_stats = ev.task_metrics.member_task_breakdown.get(m.name, {})
                member_rows.append(
                    {
                        "Member ID": m.member_id,
                        "Name": m.name,
                        "GitHub": f"@{m.github_username}" if m.github_username else "-",
                        "Role": m.role,
                        "Discipline": m.discipline or "-",
                        "Primary Responsibility Areas": (
                            ", ".join(r_match.primary_areas) if r_match and r_match.primary_areas else "Not Specified"
                        ),
                        "Owned Deliverables": (
                            ", ".join(r_match.deliverables_owned)
                            if r_match and r_match.deliverables_owned
                            else "Not Specified"
                        ),
                        "Tasks (Done/Total)": f"{task_stats.get('completed', 0)}/{task_stats.get('total', 0)}",
                        "Overdue Tasks": task_stats.get("overdue", 0),
                    }
                )
            st.dataframe(pd.DataFrame(member_rows), use_container_width=True, hide_index=True)
        elif ev.responsibilities:
            resp_rows = [
                {
                    "Member ID": r.member_id,
                    "Name": r.member_name,
                    "Primary Areas": ", ".join(r.primary_areas),
                    "Deliverables Owned": ", ".join(r.deliverables_owned),
                    "Notes": r.notes or "",
                }
                for r in ev.responsibilities
            ]
            st.dataframe(pd.DataFrame(resp_rows), use_container_width=True, hide_index=True)
        else:
            st.info(
                "Neither `team/members.json` nor `team/responsibilities.json` has been submitted in this repository yet."
            )

    # ------------------------------------------------------------------
    # Tab 2: Student-Reported Progress vs. Recent GitHub Activity
    # ------------------------------------------------------------------
    with tab_progress:
        u_col, c_col = st.columns([1.2, 1])
        with u_col:
            st.markdown("#### Latest Student-Reported Update (`project/progress.json`)")
            if ev.progress:
                st.caption(
                    f"Last Reported: **{ev.progress.last_updated or 'Unknown'}** | "
                    f"Current Phase: **{ev.progress.current_phase}**"
                )
                if ev.progress.summary:
                    st.write(ev.progress.summary)

                st.markdown("**Completed Since Previous Update:**")
                if ev.progress.accomplishments_since_last_update:
                    for item in ev.progress.accomplishments_since_last_update:
                        st.markdown(f"- ✅ {item}")
                else:
                    st.caption("None reported.")

                st.markdown("**Current Blockers:**")
                if ev.progress.blockers:
                    for b in ev.progress.blockers:
                        st.markdown(f"- 🚨 {b}")
                else:
                    st.caption("No active blockers reported.")

                st.markdown("**Next Steps:**")
                if ev.progress.next_steps:
                    for ns in ev.progress.next_steps:
                        st.markdown(f"- ➡️ {ns}")
                else:
                    st.caption("None listed.")
            else:
                st.warning("`project/progress.json` is not available for this team.")

        with c_col:
            st.markdown("#### Recent GitHub Commit Activity (Separate from Completion)")
            st.caption(
                "Repository commits indicate engineering activity but do not automatically mark tasks complete."
            )
            if ev.snapshot.recent_commits:
                commit_rows = [
                    {
                        "SHA": c.short_sha,
                        "Date": c.committed_date[:10] if c.committed_date else "",
                        "Author": c.author_name,
                        "Message": c.message,
                        "Link": c.html_url,
                    }
                    for c in ev.snapshot.recent_commits[:10]
                ]
                st.dataframe(
                    pd.DataFrame(commit_rows),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Link": st.column_config.LinkColumn("Commit", display_text="View ↗"),
                    },
                )
            else:
                st.info("No commits found in this repository.")

        if ev.unresolved_action_items:
            st.markdown("#### Unresolved Review Action Items")
            ai_rows = [
                {
                    "Review": f"Review {r_num}",
                    "Action ID": ai.action_id,
                    "Description": ai.description,
                    "Assigned To": ai.assigned_to,
                    "Due Date": ai.due_date or "TBD",
                    "Status": ai.status,
                }
                for r_num, ai in ev.unresolved_action_items
            ]
            st.dataframe(pd.DataFrame(ai_rows), use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------
    # Tab 3: Categorized Project Artifacts & Custom Folders
    # ------------------------------------------------------------------
    with tab_files:
        st.markdown("#### Categorized Project Files & Custom Folders")
        if ev.custom_top_folders:
            st.info(
                "Custom top-level folders discovered in repository: "
                + ", ".join(f"`{f}/`" for f in ev.custom_top_folders)
            )

        cat_col1, cat_col2 = st.columns([1.5, 2])
        with cat_col1:
            non_empty_cats = [
                f"{cat} ({len(items)})"
                for cat, items in ev.categorized_files.items()
                if items
            ]
            if not non_empty_cats:
                st.warning("No files discovered in repository tree.")
                selected_cat_label = None
            else:
                selected_cat_label = st.selectbox("Select Artifact Category", options=non_empty_cats)

        with cat_col2:
            file_search = st.text_input(
                "Search files across repository",
                value="",
                placeholder="Search by filename or folder path...",
            ).strip().lower()

        if file_search:
            matching_files = [
                e for e in ev.snapshot.tree_entries
                if e.item_type == "file" and file_search in e.path.lower()
            ]
            st.caption(f"Showing {len(matching_files)} file(s) matching `'{file_search}'`:")
            _render_file_table_with_preview_link(selected_repo, matching_files)
        elif selected_cat_label:
            cat_name = selected_cat_label.rsplit(" (", 1)[0]
            cat_items = ev.categorized_files.get(cat_name, [])
            _render_file_table_with_preview_link(selected_repo, cat_items)

    # ------------------------------------------------------------------
    # Tab 4: Repository README
    # ------------------------------------------------------------------
    with tab_readme:
        readme_res = ev.snapshot.convention_raw_files.get(CONVENTION_FILES["readme"])
        if readme_res and readme_res.exists and readme_res.text_content:
            st.caption(f"Source: `{CONVENTION_FILES['readme']}` ([Open on GitHub ↗]({readme_res.html_url}))")
            st.markdown(sanitize_markdown_for_display(readme_res.text_content))
        else:
            st.info("No `README.md` found at the root of this repository.")

    # ------------------------------------------------------------------
    # Tab 5: Metadata Validation Health
    # ------------------------------------------------------------------
    with tab_health:
        st.markdown("#### Structured Metadata Validation Report")
        st.caption(
            "Shows which optional convention files exist in the repository and whether they pass JSON schema validation."
        )
        health_rows = []
        for fpath, vrep in sorted(ev.validation_reports.items()):
            health_rows.append(
                {
                    "Metadata File": fpath,
                    "Validation State": vrep.state.value.upper(),
                    "Errors": "; ".join(vrep.errors) if vrep.errors else "None",
                    "Warnings": "; ".join(vrep.warnings) if vrep.warnings else "None",
                }
            )
        st.dataframe(pd.DataFrame(health_rows), use_container_width=True, hide_index=True)


def _render_file_table_with_preview_link(repo_name: str, files: list) -> None:
    if not files:
        st.caption("No files in this view.")
        return

    rows = [
        {
            "File Name": f.name,
            "Path": f.path,
            "Extension": f.extension or "file",
            "Size (Bytes)": f.size,
            "GitHub Link": f.html_url,
        }
        for f in files
    ]
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "GitHub Link": st.column_config.LinkColumn("GitHub", display_text="Open ↗"),
        },
    )

    preview_target = st.selectbox(
        "Quick-open a file in the Repository Explorer Previewer",
        options=[""] + [f.path for f in files],
        format_func=lambda p: "Select a file to preview..." if p == "" else p,
        key=f"ws_preview_{repo_name}_{len(files)}",
    )
    if preview_target:
        if st.button("Open in Repository Explorer", key=f"btn_ws_open_{repo_name}_{preview_target}"):
            folder = preview_target.rsplit("/", 1)[0] if "/" in preview_target else ""
            st.session_state["selected_repo"] = repo_name
            st.session_state["explorer_path"] = folder
            st.session_state["explorer_selected_file"] = preview_target
            st.session_state["active_page"] = "Repository Explorer"
            st.rerun()
