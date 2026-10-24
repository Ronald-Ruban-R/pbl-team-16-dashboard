"""
Individual Team Workspace View.

Organized with a compact header bar and 5 clean tabs (Project Brief & Members,
Progress & Commits, Categorized Project Files, Repository README, and Metadata Health)
so nothing feels crowded while every single detail remains accessible in one click.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.config import CONVENTION_FILES
from src.security import AccessControlManager, AuthenticatedUser, sanitize_markdown_for_display


def render_team_workspace_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
) -> None:
    """Render the clean, decluttered workspace for a selected team."""
    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("You are not authorized to access any team repositories.")
        return

    default_repo = st.session_state.get("selected_repo")
    if default_repo not in authorized_repos:
        default_repo = authorized_repos[0]

    if len(authorized_repos) > 1:
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
    else:
        selected_repo = authorized_repos[0]
        st.session_state["selected_repo"] = selected_repo
        top_col1, top_col2 = st.columns([3, 1])
        with top_col1:
            t_title = evaluations[selected_repo].metadata.team_name if evaluations[selected_repo].metadata else selected_repo
            st.markdown(f"## 🚀 {t_title} (`{selected_repo}`)")

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
    # Compact Top KPI Strip
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

    # ------------------------------------------------------------------
    # Organized Workspace Tabs
    # ------------------------------------------------------------------
    tab_brief, tab_progress, tab_files, tab_readme, tab_health = st.tabs(
        [
            "📋 Project Brief & Team Roster",
            "📈 Progress Updates & Commits",
            "🗂️ Project Files by Category",
            "📖 Repository README",
            "🛡️ Metadata Health",
        ]
    )

    # ------------------------------------------------------------------
    # Tab 1: Project Brief, Problem Statement & Team Roster
    # ------------------------------------------------------------------
    with tab_brief:
        meta = ev.metadata
        if meta:
            with st.container(border=True):
                st.markdown(f"#### {meta.project_title}")
                p1, p2, p3, p4 = st.columns(4)
                p1.caption(f"**Team:** {meta.team_name} (`{ev.repo_name}`)")
                p2.caption(f"**Domain:** {meta.domain}")
                p3.caption(f"**Schedule:** {meta.start_date or 'TBD'} → {meta.target_completion_date or 'TBD'}")
                p4.caption(
                    f"**Mentors:** {meta.lead_mentor or 'Assigned Mentor'}"
                    f"{f', {meta.co_mentor}' if meta.co_mentor else ''}"
                )

                st.markdown("**Problem Statement**")
                st.info(meta.problem_statement)

                with st.expander("🎯 View Project Objectives & Expected Outcomes", expanded=False):
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
                        "ID": m.member_id,
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
                        "Overdue": task_stats.get("overdue", 0),
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
        u_col, c_col = st.columns([1.15, 1])
        with u_col:
            with st.container(border=True):
                st.markdown("#### Latest Progress Report (`project/progress.json`)")
                if ev.progress:
                    st.caption(
                        f"Last Updated: **{ev.progress.last_updated or 'Unknown'}** • "
                        f"Phase: **{ev.progress.current_phase}**"
                    )
                    if ev.progress.summary:
                        st.write(ev.progress.summary)

                    st.markdown("**Completed Since Previous Update**")
                    if ev.progress.accomplishments_since_last_update:
                        for item in ev.progress.accomplishments_since_last_update:
                            st.markdown(f"- ✅ {item}")
                    else:
                        st.caption("None reported.")

                    st.markdown("**Current Blockers**")
                    if ev.progress.blockers:
                        for b in ev.progress.blockers:
                            st.markdown(f"- 🚨 {b}")
                    else:
                        st.caption("No active blockers reported.")

                    st.markdown("**Next Steps**")
                    if ev.progress.next_steps:
                        for ns in ev.progress.next_steps:
                            st.markdown(f"- ➡️ {ns}")
                    else:
                        st.caption("None listed.")
                else:
                    st.warning("`project/progress.json` is not available for this team.")

        with c_col:
            with st.container(border=True):
                st.markdown("#### Recent GitHub Commits (Separate from Progress)")
                st.caption("Commits reflect repository activity, not task completion.")
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
            st.markdown("#### Open Review Action Items")
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
        if ev.custom_top_folders:
            st.caption(
                "Custom top-level folders discovered: "
                + ", ".join(f"`{f}/`" for f in ev.custom_top_folders)
            )

        cat_col1, cat_col2 = st.columns([1.5, 2])
        with cat_col1:
            non_empty_cats = [
                f"{cat} ({len(items)})"
                for cat, items in ev.categorized_files.items()
                if items
            ]
            selected_cat_label = (
                st.selectbox("Artifact Category", options=non_empty_cats)
                if non_empty_cats
                else None
            )

        with cat_col2:
            file_search = st.text_input(
                "Filter files by name or path",
                value="",
                placeholder="Type filename or path...",
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
        else:
            st.info("No files discovered in repository tree.")

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
        st.caption(
            "Validation status of optional convention JSON files (`VALID`, `MISSING`, or `MALFORMED`)."
        )
        health_rows = [
            {
                "Metadata File": fpath,
                "Status": vrep.state.value.upper(),
                "Errors": "; ".join(vrep.errors) if vrep.errors else "None",
                "Warnings": "; ".join(vrep.warnings) if vrep.warnings else "None",
            }
            for fpath, vrep in sorted(ev.validation_reports.items())
        ]
        st.dataframe(pd.DataFrame(health_rows), use_container_width=True, hide_index=True)


def _render_file_table_with_preview_link(repo_name: str, files: list) -> None:
    if not files:
        st.caption("No files in this category.")
        return

    rows = [
        {
            "File Name": f.name,
            "Path": f.path,
            "Format": f.extension or "file",
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

    c_sel, c_btn = st.columns([3, 1])
    with c_sel:
        preview_target = st.selectbox(
            "Preview file in Repository Explorer",
            options=[""] + [f.path for f in files],
            format_func=lambda p: "Select a file to preview..." if p == "" else p,
            key=f"ws_preview_{repo_name}_{len(files)}",
            label_visibility="collapsed",
        )
    with c_btn:
        if st.button(
            "Open Preview",
            key=f"btn_ws_open_{repo_name}_{len(files)}",
            disabled=not bool(preview_target),
            use_container_width=True,
        ):
            folder = preview_target.rsplit("/", 1)[0] if "/" in preview_target else ""
            st.session_state["selected_repo"] = repo_name
            st.session_state["explorer_path"] = folder
            st.session_state["explorer_selected_file"] = preview_target
            st.session_state["active_page"] = "Repository Explorer"
            st.rerun()
