"""
Individual Team Workspace View.

Includes 6 clean, emoji-free tabs:
1. `Project Brief & Team Roster`
2. `Progress Updates & Commits`
3. `Project Files by Category`
4. `Repository README`
5. `Metadata Health`
6. `Edit Project & Team Info` (Strictly for `role = "owner"` to edit and commit
   `project/metadata.json`, `team/members.json`, and `team/responsibilities.json`
   directly from the dashboard without touching raw JSON files; `student` role is read-only).
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.config import CONVENTION_FILES
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser, sanitize_markdown_for_display
from src.storage import MentorLocalStore


def render_team_workspace_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
    github_client: GitHubCohortClient | None = None,
    local_store: MentorLocalStore | None = None,
) -> None:
    """Render the clean, emoji-free workspace for a selected team."""
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
            t_title = (
                evaluations[selected_repo].metadata.team_name
                if evaluations[selected_repo].metadata
                else selected_repo
            )
            st.markdown(f"## {t_title} (`{selected_repo}`)")

    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    with top_col2:
        st.write("")
        st.link_button("Open Private GitHub Repo", ev.snapshot.html_url, use_container_width=True)

    if not ev.snapshot.accessible:
        st.error(
            f"Repository `{selected_repo}` is currently inaccessible: {ev.snapshot.error_message}"
        )
        return

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

    tab_brief, tab_progress, tab_files, tab_readme, tab_health, tab_edit = st.tabs(
        [
            "Project Brief & Team Roster",
            "Progress Updates & Commits",
            "Project Files by Category",
            "Repository README",
            "Metadata Health",
            "Edit Project & Team Info",
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
                p3.caption(f"**Schedule:** {meta.start_date or 'TBD'} to {meta.target_completion_date or 'TBD'}")
                p4.caption(
                    f"**Mentors:** {meta.lead_mentor or 'Assigned Mentor'}"
                    f"{f', {meta.co_mentor}' if meta.co_mentor else ''}"
                )

                st.markdown("**Problem Statement**")
                st.info(meta.problem_statement)

                with st.expander("View Project Objectives & Expected Outcomes", expanded=False):
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
                "Use the 'Edit Project & Team Info' tab to initialize it."
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
                "Neither `team/members.json` nor `team/responsibilities.json` has been submitted yet."
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
                        f"Last Updated: **{ev.progress.last_updated or 'Unknown'}** | "
                        f"Phase: **{ev.progress.current_phase}**"
                    )
                    if ev.progress.summary:
                        st.write(ev.progress.summary)

                    st.markdown("**Completed Since Previous Update**")
                    if ev.progress.accomplishments_since_last_update:
                        for item in ev.progress.accomplishments_since_last_update:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("None reported.")

                    st.markdown("**Current Blockers**")
                    if ev.progress.blockers:
                        for b in ev.progress.blockers:
                            st.markdown(f"- {b}")
                    else:
                        st.caption("No active blockers reported.")

                    st.markdown("**Next Steps**")
                    if ev.progress.next_steps:
                        for ns in ev.progress.next_steps:
                            st.markdown(f"- {ns}")
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
                            "Link": st.column_config.LinkColumn("Commit", display_text="View"),
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
            st.caption(f"Source: `{CONVENTION_FILES['readme']}` ([Open on GitHub]({readme_res.html_url}))")
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

    # ------------------------------------------------------------------
    # Tab 6: Interactive Editor for project/metadata.json, team/members.json & team/responsibilities.json
    # Strictly gated to `role = "owner"` (Team Lead / Organization Owner); students are read-only.
    # ------------------------------------------------------------------
    with tab_edit:
        if not user.can_edit_repo_metadata(selected_repo):
            st.info(
                "Read-Only Mode: Only Team Leads / Owners (`role = \"owner\"` in Secrets) can edit "
                "and commit project or team metadata files. Team members (`role = \"student\"`) have read-only access."
            )
        elif github_client is None:
            st.error("GitHub client is not initialized.")
        else:
            st.caption(
                f"Select a file below to add or edit entries directly in `{selected_repo}` on GitHub without editing raw JSON."
            )
            file_choice = st.radio(
                "Select File to Edit",
                options=[
                    "Project Metadata (project/metadata.json)",
                    "Team Members (team/members.json)",
                    "Member Responsibilities (team/responsibilities.json)",
                ],
                horizontal=True,
                key=f"ws_edit_radio_{selected_repo}",
            )

            if file_choice.startswith("Project Metadata"):
                _render_metadata_editor(selected_repo, ev, user, github_client, local_store)
            elif file_choice.startswith("Team Members"):
                _render_members_editor(selected_repo, ev, user, github_client, local_store)
            else:
                _render_responsibilities_editor(selected_repo, ev, user, github_client, local_store)


def _render_metadata_editor(
    repo_name: str,
    ev: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore | None,
) -> None:
    meta = ev.metadata
    with st.form(f"form_edit_metadata_{repo_name}"):
        st.markdown("##### Edit `project/metadata.json`")
        c1, c2, c3 = st.columns(3)
        team_id = c1.text_input("Team ID", value=meta.team_id if meta else repo_name)
        team_name = c2.text_input("Team Name", value=meta.team_name if meta else "")
        domain = c3.text_input("Domain", value=meta.domain if meta else "")

        project_title = st.text_input("Project Title", value=meta.project_title if meta else "")
        problem_statement = st.text_area(
            "Problem Statement",
            value=meta.problem_statement if meta else "",
            height=90,
        )

        o1, o2 = st.columns(2)
        objectives_txt = o1.text_area(
            "Objectives (one per line)",
            value="\n".join(meta.objectives) if meta and meta.objectives else "",
            height=90,
        )
        outcomes_txt = o2.text_area(
            "Expected Outcomes (one per line)",
            value="\n".join(meta.expected_outcomes) if meta and meta.expected_outcomes else "",
            height=90,
        )

        d1, d2, d3, d4 = st.columns(4)
        start_date = d1.text_input("Start Date (YYYY-MM-DD)", value=meta.start_date or "" if meta else "")
        target_date = d2.text_input("Target Completion (YYYY-MM-DD)", value=meta.target_completion_date or "" if meta else "")
        lead_mentor = d3.text_input("Lead Mentor", value=meta.lead_mentor or "" if meta else "")
        co_mentor = d4.text_input("Co-Mentor", value=meta.co_mentor or "" if meta else "")

        tags_txt = st.text_input(
            "Tags (comma-separated)",
            value=", ".join(meta.tags) if meta and meta.tags else "",
        )

        if st.form_submit_button(f"Commit `project/metadata.json` to `{repo_name}`"):
            if not team_id.strip() or not team_name.strip() or not project_title.strip() or not domain.strip() or not problem_statement.strip():
                st.error("Team ID, Team Name, Project Title, Domain, and Problem Statement are required.")
            else:
                payload = {
                    "team_id": team_id.strip(),
                    "team_name": team_name.strip(),
                    "project_title": project_title.strip(),
                    "domain": domain.strip(),
                    "problem_statement": problem_statement.strip(),
                    "objectives": [x.strip() for x in objectives_txt.splitlines() if x.strip()],
                    "expected_outcomes": [x.strip() for x in outcomes_txt.splitlines() if x.strip()],
                    "start_date": start_date.strip() or None,
                    "target_completion_date": target_date.strip() or None,
                    "lead_mentor": lead_mentor.strip() or None,
                    "co_mentor": co_mentor.strip() or None,
                    "tags": [t.strip() for t in tags_txt.split(",") if t.strip()],
                }
                ok, msg = github_client.commit_structured_json(
                    repo_name=repo_name,
                    file_path="project/metadata.json",
                    json_payload=payload,
                    commit_message=f"chore(metadata): update project/metadata.json by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                if local_store:
                    local_store.log_audit_event(user.username, user.role.value, "commit_metadata_json", repo_name, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)


def _render_members_editor(
    repo_name: str,
    ev: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore | None,
) -> None:
    st.markdown("##### Edit `team/members.json`")
    existing_ids = [m.member_id for m in ev.members]
    action = st.radio(
        "Action",
        options=["Add or Update Member", "Remove Member"] if existing_ids else ["Add or Update Member"],
        horizontal=True,
        key=f"mem_action_{repo_name}",
    )

    if action == "Remove Member" and existing_ids:
        rem_id = st.selectbox(
            "Select Member to Remove",
            options=existing_ids,
            format_func=lambda mid: next((f"{m.member_id}: {m.name} ({m.role})" for m in ev.members if m.member_id == mid), mid),
        )
        if st.button(f"Remove Member `{rem_id}` and Commit to GitHub"):
            remaining = [
                {
                    "member_id": m.member_id,
                    "name": m.name,
                    "github_username": m.github_username,
                    "role": m.role,
                    "discipline": m.discipline,
                    "email": m.email,
                }
                for m in ev.members
                if m.member_id != rem_id
            ]
            ok, msg = github_client.commit_structured_json(
                repo_name=repo_name,
                file_path="team/members.json",
                json_payload={"members": remaining},
                commit_message=f"chore(team): remove member {rem_id} by {user.username}",
                branch=ev.snapshot.default_branch,
            )
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        return

    sel_member = None
    if existing_ids:
        pick = st.selectbox(
            "Select Existing Member to Edit (or choose '+ New Member')",
            options=["+ New Member"] + existing_ids,
            format_func=lambda x: x if x == "+ New Member" else next((f"{m.member_id}: {m.name}" for m in ev.members if m.member_id == x), x),
        )
        if pick != "+ New Member":
            sel_member = next((m for m in ev.members if m.member_id == pick), None)

    default_mid = sel_member.member_id if sel_member else f"M{len(ev.members) + 1}"
    with st.form(f"form_edit_members_{repo_name}"):
        c1, c2, c3 = st.columns(3)
        m_id = c1.text_input("Member ID", value=default_mid)
        m_name = c2.text_input("Full Name", value=sel_member.name if sel_member else "")
        m_gh = c3.text_input("GitHub Username", value=sel_member.github_username or "" if sel_member else "")

        c4, c5, c6 = st.columns(3)
        m_role = c4.text_input("Project Role", value=sel_member.role if sel_member else "Team Member")
        m_disc = c5.text_input("Discipline / Department", value=sel_member.discipline or "" if sel_member else "")
        m_email = c6.text_input("Email (Optional)", value=sel_member.email or "" if sel_member else "")

        if st.form_submit_button(f"Save Member to `team/members.json` in `{repo_name}`"):
            if not m_id.strip() or not m_name.strip():
                st.error("Member ID and Full Name are required.")
            else:
                new_entry = {
                    "member_id": m_id.strip(),
                    "name": m_name.strip(),
                    "github_username": m_gh.strip().lstrip("@") or None,
                    "role": m_role.strip() or "Team Member",
                    "discipline": m_disc.strip() or None,
                    "email": m_email.strip() or None,
                }
                updated: List[Dict] = []
                replaced = False
                for m in ev.members:
                    if m.member_id == m_id.strip():
                        updated.append(new_entry)
                        replaced = True
                    else:
                        updated.append(
                            {
                                "member_id": m.member_id,
                                "name": m.name,
                                "github_username": m.github_username,
                                "role": m.role,
                                "discipline": m.discipline,
                                "email": m.email,
                            }
                        )
                if not replaced:
                    updated.append(new_entry)

                ok, msg = github_client.commit_structured_json(
                    repo_name=repo_name,
                    file_path="team/members.json",
                    json_payload={"members": updated},
                    commit_message=f"chore(team): update member {m_id.strip()} in team/members.json by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                if local_store:
                    local_store.log_audit_event(user.username, user.role.value, "commit_members_json", repo_name, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)


def _render_responsibilities_editor(
    repo_name: str,
    ev: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore | None,
) -> None:
    st.markdown("##### Edit `team/responsibilities.json`")
    existing_ids = [r.member_id for r in ev.responsibilities]
    sel_resp = None
    if existing_ids:
        pick = st.selectbox(
            "Select Member Responsibility Record to Edit (or '+ New Responsibility Record')",
            options=["+ New Responsibility Record"] + existing_ids,
            format_func=lambda x: x if x.startswith("+") else next((f"{r.member_id}: {r.member_name}" for r in ev.responsibilities if r.member_id == x), x),
        )
        if not pick.startswith("+"):
            sel_resp = next((r for r in ev.responsibilities if r.member_id == pick), None)

    default_rid = sel_resp.member_id if sel_resp else (ev.members[0].member_id if ev.members else f"M{len(ev.responsibilities) + 1}")
    default_rname = sel_resp.member_name if sel_resp else (ev.members[0].name if ev.members else "")

    with st.form(f"form_edit_resp_{repo_name}"):
        c1, c2 = st.columns([1, 2])
        r_id = c1.text_input("Member ID", value=default_rid)
        r_name = c2.text_input("Member Full Name", value=default_rname)

        a1, a2 = st.columns(2)
        areas_txt = a1.text_area(
            "Primary Responsibility Areas (one per line)",
            value="\n".join(sel_resp.primary_areas) if sel_resp else "",
            height=90,
        )
        delivs_txt = a2.text_area(
            "Deliverables Owned (one path or title per line)",
            value="\n".join(sel_resp.deliverables_owned) if sel_resp else "",
            height=90,
        )
        notes_txt = st.text_input("Notes (Optional)", value=sel_resp.notes or "" if sel_resp else "")

        if st.form_submit_button(f"Save Responsibility to `team/responsibilities.json` in `{repo_name}`"):
            if not r_id.strip() or not r_name.strip():
                st.error("Member ID and Member Full Name are required.")
            else:
                new_rec = {
                    "member_id": r_id.strip(),
                    "member_name": r_name.strip(),
                    "primary_areas": [x.strip() for x in areas_txt.splitlines() if x.strip()],
                    "deliverables_owned": [x.strip() for x in delivs_txt.splitlines() if x.strip()],
                    "notes": notes_txt.strip() or "",
                }
                updated: List[Dict] = []
                replaced = False
                for r in ev.responsibilities:
                    if r.member_id == r_id.strip():
                        updated.append(new_rec)
                        replaced = True
                    else:
                        updated.append(
                            {
                                "member_id": r.member_id,
                                "member_name": r.member_name,
                                "primary_areas": r.primary_areas,
                                "deliverables_owned": r.deliverables_owned,
                                "notes": r.notes or "",
                            }
                        )
                if not replaced:
                    updated.append(new_rec)

                ok, msg = github_client.commit_structured_json(
                    repo_name=repo_name,
                    file_path="team/responsibilities.json",
                    json_payload={"responsibilities": updated},
                    commit_message=f"chore(team): update responsibilities for {r_id.strip()} by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                if local_store:
                    local_store.log_audit_event(user.username, user.role.value, "commit_responsibilities_json", repo_name, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)


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
            "GitHub Link": st.column_config.LinkColumn("GitHub", display_text="Open"),
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
