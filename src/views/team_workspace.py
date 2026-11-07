"""
Individual Team Workspace View (`src/views/team_workspace.py`).

Organized into 6 clean, consistent tabs:
1. `Project Brief & Team Roster`
2. `Progress Updates & Commits`
3. `Project Files by Category`
4. `Repository README`
5. `Metadata Health`
6. `Edit Project & Team Info` (Strictly for `role = "owner"` to edit and commit
   `project/metadata.json`, `team/members.json`, and `team/responsibilities.json`
   directly from the dashboard; `student` role is strictly read-only).
"""

from __future__ import annotations

from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.config import CONVENTION_FILES, format_repo_display_name
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser, sanitize_markdown_for_display
from src.storage import MentorLocalStore
from src.ui_theme import format_bool_indicator, format_health_badge, format_task_status


def render_team_workspace_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
    github_client: GitHubCohortClient | None = None,
    local_store: MentorLocalStore | None = None,
) -> None:
    """Render the workspace for a selected team."""
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
                format_func=lambda r: f"{r} — {evaluations[r].display_team_name}",
            )
            st.session_state["selected_repo"] = selected_repo
    else:
        selected_repo = authorized_repos[0]
        st.session_state["selected_repo"] = selected_repo

    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    h_col1, h_col2 = st.columns([3, 1])
    with h_col1:
        st.markdown(f"## {ev.display_team_name}")
        domain_str = (
            ev.metadata.domain
            if ev.metadata and ev.metadata.domain
            else "General Engineering & Innovation"
        )
        title_str = (
            ev.metadata.project_title
            if ev.metadata and ev.metadata.project_title
            else f"{ev.display_team_name} Project"
        )
        st.caption(
            f"Repository: [`{ev.snapshot.org}/{selected_repo}`]({ev.snapshot.html_url}) · "
            f"Domain: **{domain_str}** · Project: **{title_str}**"
        )
    with h_col2:
        st.markdown(
            f"<div style='text-align:right; font-weight:600; font-size:1.05rem; padding-top:0.6rem;'>"
            f"{format_health_badge(ev.health_status)}</div>",
            unsafe_allow_html=True,
        )

    if not ev.snapshot.accessible:
        st.error(f"Repository `{selected_repo}` is unavailable: {ev.snapshot.error_message}")
        return

    k1, k2, k3, k4 = st.columns(4)
    k1.metric(
        "Verified Progress",
        f"{ev.verified_progress_pct:.1f}%",
        delta=f"{ev.verified_progress_pct - ev.reported_progress_pct:+.1f}% vs reported",
    )
    k2.metric("Reported Progress", f"{ev.reported_progress_pct:.1f}%")
    k3.metric("Tasks Completed", f"{ev.completed_tasks} / {ev.total_tasks}")
    k4.metric(
        "Last Commit",
        f"{ev.days_since_last_commit}d ago" if ev.days_since_last_commit is not None else "N/A",
    )

    tab_brief, tab_updates, tab_files, tab_readme, tab_health, tab_edit = st.tabs(
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
    # Tab 1: Project Brief, Objectives, Roster & Responsibilities
    # ------------------------------------------------------------------
    with tab_brief:
        b_col1, b_col2 = st.columns([1.35, 1])
        with b_col1:
            with st.container(border=True):
                st.markdown("#### Project Scope & Problem Statement")
                if ev.metadata:
                    st.markdown(f"**Project Title:** {ev.metadata.project_title}")
                    st.markdown(f"**Domain:** {ev.metadata.domain}")
                    st.markdown("**Problem Statement:**")
                    st.write(ev.metadata.problem_statement)

                    if ev.metadata.objectives:
                        st.markdown("**Key Objectives:**")
                        for obj in ev.metadata.objectives:
                            st.markdown(f"- {obj}")

                    if ev.metadata.expected_outcomes:
                        st.markdown("**Expected Outcomes:**")
                        for out in ev.metadata.expected_outcomes:
                            st.markdown(f"- {out}")

                    meta_footer = []
                    if ev.metadata.lead_mentor:
                        meta_footer.append(f"**Lead Mentor:** {ev.metadata.lead_mentor}")
                    if ev.metadata.co_mentor:
                        meta_footer.append(f"**Co-Mentor:** {ev.metadata.co_mentor}")
                    if ev.metadata.start_date or ev.metadata.target_completion_date:
                        meta_footer.append(
                            f"**Schedule:** {ev.metadata.start_date or 'TBD'} → {ev.metadata.target_completion_date or 'TBD'}"
                        )
                    if meta_footer:
                        st.caption(" · ".join(meta_footer))
                    if ev.metadata.tags:
                        st.caption("Tags: " + ", ".join(f"`{t}`" for t in ev.metadata.tags))
                else:
                    st.info(
                        "`project/metadata.json` is not configured yet. Team Leads (`role = \"owner\"`) "
                        "can fill it out in the 'Edit Project & Team Info' tab."
                    )

        with b_col2:
            with st.container(border=True):
                st.markdown(f"#### Team Roster ({len(ev.members)} Members)")
                if ev.members:
                    roster_rows = [
                        {
                            "ID": m.member_id,
                            "Name": m.name,
                            "Role": m.role,
                            "GitHub": f"@{m.github_username}" if m.github_username else "-",
                            "Discipline": m.discipline or "-",
                        }
                        for m in ev.members
                    ]
                    st.dataframe(pd.DataFrame(roster_rows), use_container_width=True, hide_index=True)
                else:
                    st.info(
                        "No team members recorded yet. Use the 'Edit Project & Team Info' tab to add your team roster."
                    )

        st.markdown("#### Individual Responsibilities Matrix")
        if ev.responsibilities:
            resp_rows = [
                {
                    "ID": r.member_id,
                    "Member": r.name,
                    "Primary Area": r.primary_area,
                    "Key Responsibilities": "; ".join(r.responsibilities) if r.responsibilities else "-",
                    "Owned Deliverables": ", ".join(r.owned_deliverables) if r.owned_deliverables else "-",
                    "Backup Owner": r.backup_owner or "-",
                }
                for r in ev.responsibilities
            ]
            st.dataframe(pd.DataFrame(resp_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No responsibility records configured in `team/responsibilities.json` yet.")

    # ------------------------------------------------------------------
    # Tab 2: Weekly Progress Updates, Milestones & Recent Commits
    # ------------------------------------------------------------------
    with tab_updates:
        u_col1, u_col2 = st.columns([1.2, 1])
        with u_col1:
            st.markdown("#### Latest Progress Report (`project/progress.json`)")
            if ev.progress:
                with st.container(border=True):
                    st.caption(
                        f"Current Phase: **{ev.progress.current_phase}** · "
                        f"Last Updated: `{ev.progress.last_updated or 'Not dated'}`"
                    )
                    if ev.progress.summary:
                        st.write(ev.progress.summary)
                    p_c1, p_c2, p_c3 = st.columns(3)
                    with p_c1:
                        st.markdown("**Completed Recently**")
                        if ev.progress.accomplishments_since_last_update:
                            for item in ev.progress.accomplishments_since_last_update:
                                st.markdown(f"- {item}")
                        else:
                            st.caption("None listed.")
                    with p_c2:
                        st.markdown("**Current Blockers**")
                        if ev.progress.blockers:
                            for b in ev.progress.blockers:
                                st.markdown(f"- {b}")
                        else:
                            st.caption("No active blockers.")
                    with p_c3:
                        st.markdown("**Next Steps**")
                        if ev.progress.next_steps:
                            for n in ev.progress.next_steps:
                                st.markdown(f"- {n}")
                        else:
                            st.caption("None listed.")

                if ev.progress.milestones:
                    st.markdown("#### Milestone Breakdown")
                    ms_rows = [
                        {
                            "ID": m.milestone_id,
                            "Milestone": m.title,
                            "Status": format_task_status(m.status),
                            "Weight (%)": m.weight,
                            "Completion (%)": m.completion_pct,
                            "Due Date": m.due_date or "-",
                            "Evidence": m.evidence_path or "-",
                        }
                        for m in ev.progress.milestones
                    ]
                    st.dataframe(pd.DataFrame(ms_rows), use_container_width=True, hide_index=True)
            else:
                st.info("`project/progress.json` has not been submitted yet.")

        with u_col2:
            st.markdown("#### Recent GitHub Commits")
            if ev.snapshot.recent_commits:
                commit_rows = [
                    {
                        "SHA": c.short_sha,
                        "Message": c.message,
                        "Author": c.author_name,
                        "Date (UTC)": c.committed_date[:10] if c.committed_date else "-",
                    }
                    for c in ev.snapshot.recent_commits
                ]
                st.dataframe(pd.DataFrame(commit_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No commits found on the default branch.")

    # ------------------------------------------------------------------
    # Tab 3: Project Files by Category
    # ------------------------------------------------------------------
    with tab_files:
        if not ev.categorized_files:
            st.info("No files found in the repository tree.")
        else:
            for cat_name, entries in ev.categorized_files.items():
                with st.expander(f"{cat_name} ({len(entries)} files)", expanded=False):
                    cat_rows = [
                        {
                            "File": e.name,
                            "Path": e.path,
                            "Size (KB)": round(e.size / 1024.0, 1),
                            "GitHub URL": e.html_url,
                        }
                        for e in entries
                    ]
                    st.dataframe(
                        pd.DataFrame(cat_rows),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "GitHub URL": st.column_config.LinkColumn("GitHub", display_text="Open ↗"),
                        },
                    )

    # ------------------------------------------------------------------
    # Tab 4: Repository README
    # ------------------------------------------------------------------
    with tab_readme:
        if ev.readme_text:
            with st.container(border=True):
                st.markdown(sanitize_markdown_for_display(ev.readme_text))
        else:
            st.info("`README.md` is missing or empty in this repository.")

    # ------------------------------------------------------------------
    # Tab 5: Metadata Health & Convention Checklist
    # ------------------------------------------------------------------
    with tab_health:
        st.markdown("#### Standard PBL Convention Files")
        conv_rows = []
        for key, rel_path in CONVENTION_FILES.items():
            exists = ev.convention_file_presence.get(rel_path, False)
            conv_rows.append(
                {
                    "File Key": key,
                    "Repository Path": rel_path,
                    "Status": format_bool_indicator(exists, "Present", "Missing"),
                }
            )
        st.dataframe(pd.DataFrame(conv_rows), use_container_width=True, hide_index=True)

        if ev.validation_issues:
            st.markdown("#### Validation & Template Diagnostics")
            v_rows = [
                {
                    "File": v.file_path,
                    "Severity": v.severity.upper(),
                    "Message": v.message,
                }
                for v in ev.validation_issues
            ]
            st.dataframe(pd.DataFrame(v_rows), use_container_width=True, hide_index=True)
        else:
            st.success("✓ All present JSON files pass schema validation with no placeholder warnings.")

    # ------------------------------------------------------------------
    # Tab 6: Owner-Only Interactive Editors for Metadata, Roster & Responsibilities
    # ------------------------------------------------------------------
    with tab_edit:
        _render_workspace_json_editors(
            selected_repo=selected_repo,
            ev=ev,
            user=user,
            github_client=github_client,
            local_store=local_store,
        )


def _render_workspace_json_editors(
    selected_repo: str,
    ev: TeamEvaluationSummary,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient | None,
    local_store: MentorLocalStore | None,
) -> None:
    if not user.can_edit_repo_metadata(selected_repo):
        st.info(
            f"Signed in as `{user.username}` (`role = \"{user.role.value}\"`). "
            "You have **read-only** access. Only Team Leads (`role = \"owner\"` in Secrets) "
            "can edit and commit `project/metadata.json`, `team/members.json`, and `team/responsibilities.json`."
        )
        return

    if github_client is None or not github_client.auth.is_configured:
        st.warning("Configure a GitHub token (`[github].token`) in Secrets to commit changes to GitHub.")
        return

    st.caption(
        f"Team Lead Write Mode (`role = \"owner\"`): Update project metadata, team members, and "
        f"responsibilities directly in `{selected_repo}` without editing raw JSON."
    )

    section = st.radio(
        "Select File to Edit",
        options=[
            "1. Project Metadata (project/metadata.json)",
            "2. Team Members (team/members.json)",
            "3. Responsibilities (team/responsibilities.json)",
        ],
        horizontal=True,
        key=f"ws_edit_section_{selected_repo}",
    )

    if section.startswith("1."):
        meta = ev.metadata
        default_team_name = meta.team_name if meta else format_repo_display_name(selected_repo)
        default_title = meta.project_title if meta else f"{default_team_name} Project"
        default_domain = meta.domain if meta else "General Engineering & Innovation"
        default_prob = (
            meta.problem_statement
            if meta and meta.problem_statement != "Problem statement not yet submitted."
            else ""
        )

        with st.form(f"meta_editor_form_{selected_repo}"):
            c1, c2 = st.columns(2)
            t_name = c1.text_input("Team Display Name", value=default_team_name)
            p_title = c2.text_input("Project Title", value=default_title)

            c3, c4, c5 = st.columns(3)
            dom_val = c3.text_input("Project Domain", value=default_domain)
            start_val = c4.text_input(
                "Start Date (YYYY-MM-DD)",
                value=meta.start_date or "" if meta else "",
                placeholder="2026-08-01",
            )
            end_val = c5.text_input(
                "Target Completion Date (YYYY-MM-DD)",
                value=meta.target_completion_date or "" if meta else "",
                placeholder="2026-12-15",
            )

            c6, c7, c8 = st.columns(3)
            lead_m = c6.text_input("Lead Mentor", value=meta.lead_mentor if meta else "")
            co_m = c7.text_input("Co-Mentor", value=meta.co_mentor if meta else "")
            tags_str = c8.text_input(
                "Tags (comma-separated)",
                value=", ".join(meta.tags) if meta and meta.tags else "",
                placeholder="IoT, Edge AI, Automation",
            )

            prob_val = st.text_area(
                "Problem Statement",
                value=default_prob,
                height=90,
                placeholder="Describe the core problem, target users, and proposed engineering approach...",
            )

            o_col, e_col = st.columns(2)
            obj_str = o_col.text_area(
                "Key Objectives (1 per line)",
                value="\n".join(meta.objectives) if meta and meta.objectives else "",
                height=95,
            )
            out_str = e_col.text_area(
                "Expected Outcomes (1 per line)",
                value="\n".join(meta.expected_outcomes) if meta and meta.expected_outcomes else "",
                height=95,
            )

            if st.form_submit_button("Commit Metadata to `project/metadata.json` on GitHub"):
                payload = {
                    "team_id": selected_repo,
                    "team_name": t_name.strip() or format_repo_display_name(selected_repo),
                    "project_title": p_title.strip() or f"{format_repo_display_name(selected_repo)} Project",
                    "domain": dom_val.strip() or "General Engineering & Innovation",
                    "problem_statement": prob_val.strip(),
                    "objectives": [x.strip() for x in obj_str.splitlines() if x.strip()],
                    "expected_outcomes": [x.strip() for x in out_str.splitlines() if x.strip()],
                    "start_date": start_val.strip() or None,
                    "target_completion_date": end_val.strip() or None,
                    "lead_mentor": lead_m.strip(),
                    "co_mentor": co_m.strip(),
                    "tags": [x.strip() for x in tags_str.split(",") if x.strip()],
                }
                ok, msg = github_client.commit_structured_json(
                    repo_name=selected_repo,
                    file_path="project/metadata.json",
                    json_payload=payload,
                    commit_message=f"chore(metadata): update project/metadata.json by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                if local_store:
                    local_store.log_audit_event(user.username, user.role.value, "commit_metadata_json", selected_repo, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    elif section.startswith("2."):
        existing_members = [
            {
                "member_id": m.member_id,
                "name": m.name,
                "github_username": m.github_username,
                "role": m.role,
                "discipline": m.discipline,
                "email": m.email,
                "skills": list(m.skills),
            }
            for m in ev.members
        ]
        m_ids = [m["member_id"] for m in existing_members]
        m_actions = ["Add New Member"]
        if m_ids:
            m_actions.extend(["Update Existing Member", "Remove Member"])

        m_mode = st.radio("Member Action", options=m_actions, horizontal=True, key=f"mem_mode_{selected_repo}")

        if m_mode == "Remove Member" and m_ids:
            rem_id = st.selectbox(
                "Select Member to Remove",
                options=m_ids,
                format_func=lambda mid: next(
                    (f"{m['member_id']}: {m['name']} ({m['role']})" for m in existing_members if m["member_id"] == mid),
                    mid,
                ),
            )
            if st.button(f"Remove Member `{rem_id}` & Commit to GitHub"):
                updated_members = [m for m in existing_members if m["member_id"] != rem_id]
                ok, msg = github_client.commit_structured_json(
                    repo_name=selected_repo,
                    file_path="team/members.json",
                    json_payload={"members": updated_members},
                    commit_message=f"chore(team): remove member {rem_id} by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                if local_store:
                    local_store.log_audit_event(user.username, user.role.value, "remove_member_json", selected_repo, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            return

        sel_mem = None
        if m_mode == "Update Existing Member" and m_ids:
            chosen_mid = st.selectbox(
                "Select Member to Edit",
                options=m_ids,
                format_func=lambda mid: next(
                    (f"{m['member_id']}: {m['name']} ({m['role']})" for m in existing_members if m["member_id"] == mid),
                    mid,
                ),
            )
            sel_mem = next((m for m in existing_members if m["member_id"] == chosen_mid), None)

        default_mid = sel_mem["member_id"] if sel_mem else f"M{len(existing_members) + 1}"

        with st.form(f"member_editor_form_{selected_repo}"):
            c1, c2, c3 = st.columns([1, 2, 1.5])
            m_id = c1.text_input("Member ID", value=default_mid)
            m_name = c2.text_input("Full Name", value=sel_mem["name"] if sel_mem else "")
            m_role = c3.text_input("Role", value=sel_mem["role"] if sel_mem else "Team Member")

            c4, c5, c6 = st.columns(3)
            m_gh = c4.text_input("GitHub Username", value=sel_mem["github_username"] if sel_mem else "")
            m_disc = c5.text_input("Department / Discipline", value=sel_mem["discipline"] if sel_mem else "")
            m_email = c6.text_input("Email Address", value=sel_mem["email"] if sel_mem else "")

            m_skills = st.text_input(
                "Skills (comma-separated)",
                value=", ".join(sel_mem["skills"]) if sel_mem and sel_mem["skills"] else "",
                placeholder="Python, Embedded C, PCB Design",
            )

            btn_label = "Update Member & Commit to GitHub" if sel_mem else "Add Member & Commit to GitHub"
            if st.form_submit_button(btn_label):
                if not m_id.strip() or not m_name.strip():
                    st.error("Member ID and Full Name are required.")
                else:
                    new_mem = {
                        "member_id": m_id.strip(),
                        "name": m_name.strip(),
                        "github_username": m_gh.strip().lstrip("@"),
                        "role": m_role.strip() or "Team Member",
                        "discipline": m_disc.strip(),
                        "email": m_email.strip(),
                        "skills": [s.strip() for s in m_skills.split(",") if s.strip()],
                    }
                    updated_members = []
                    replaced = False
                    for item in existing_members:
                        if item["member_id"] == m_id.strip():
                            updated_members.append(new_mem)
                            replaced = True
                        else:
                            updated_members.append(item)
                    if not replaced:
                        updated_members.append(new_mem)

                    ok, msg = github_client.commit_structured_json(
                        repo_name=selected_repo,
                        file_path="team/members.json",
                        json_payload={"members": updated_members},
                        commit_message=f"chore(team): update member {m_name.strip()} in team/members.json by {user.username}",
                        branch=ev.snapshot.default_branch,
                    )
                    if local_store:
                        local_store.log_audit_event(user.username, user.role.value, "commit_members_json", selected_repo, msg)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    else:
        existing_resps = [
            {
                "member_id": r.member_id,
                "name": r.name,
                "primary_area": r.primary_area,
                "responsibilities": list(r.responsibilities),
                "owned_deliverables": list(r.owned_deliverables),
                "backup_owner": r.backup_owner,
            }
            for r in ev.responsibilities
        ]
        r_ids = [r["member_id"] for r in existing_resps]
        pick_r = st.selectbox(
            "Select Responsibility Record to Edit (or '+ Add New Record')",
            options=r_ids + ["+ Add New Responsibility Record"],
            format_func=lambda rid: (
                rid
                if rid.startswith("+")
                else next(
                    (f"{r['member_id']}: {r['name']} — {r['primary_area']}" for r in existing_resps if r["member_id"] == rid),
                    rid,
                )
            ),
        )
        sel_r = None if pick_r.startswith("+") else next((r for r in existing_resps if r["member_id"] == pick_r), None)

        with st.form(f"resp_editor_form_{selected_repo}"):
            c1, c2, c3 = st.columns([1, 1.8, 1.8])
            r_id = c1.text_input("Member ID", value=sel_r["member_id"] if sel_r else f"M{len(existing_resps) + 1}")
            r_name = c2.text_input("Member Name", value=sel_r["name"] if sel_r else "")
            r_area = c3.text_input(
                "Primary Ownership Area",
                value=sel_r["primary_area"] if sel_r else "",
                placeholder="e.g., Sensor Firmware & Edge Inference",
            )

            c4, c5 = st.columns(2)
            r_list = c4.text_area(
                "Responsibilities (1 per line)",
                value="\n".join(sel_r["responsibilities"]) if sel_r else "",
                height=90,
            )
            r_deliv = c5.text_area(
                "Owned Deliverables / Paths (1 per line)",
                value="\n".join(sel_r["owned_deliverables"]) if sel_r else "",
                height=90,
            )
            r_backup = st.text_input("Backup Owner", value=sel_r["backup_owner"] if sel_r else "")

            if st.form_submit_button("Commit Responsibilities to `team/responsibilities.json` on GitHub"):
                if not r_id.strip() or not r_name.strip():
                    st.error("Member ID and Member Name are required.")
                else:
                    new_r = {
                        "member_id": r_id.strip(),
                        "name": r_name.strip(),
                        "primary_area": r_area.strip() or "General Execution",
                        "responsibilities": [x.strip() for x in r_list.splitlines() if x.strip()],
                        "owned_deliverables": [x.strip() for x in r_deliv.splitlines() if x.strip()],
                        "backup_owner": r_backup.strip(),
                    }
                    updated_resps = []
                    replaced = False
                    for item in existing_resps:
                        if item["member_id"] == r_id.strip():
                            updated_resps.append(new_r)
                            replaced = True
                        else:
                            updated_resps.append(item)
                    if not replaced:
                        updated_resps.append(new_r)

                    ok, msg = github_client.commit_structured_json(
                        repo_name=selected_repo,
                        file_path="team/responsibilities.json",
                        json_payload={"responsibilities": updated_resps},
                        commit_message=f"chore(team): update responsibilities for {r_name.strip()} by {user.username}",
                        branch=ev.snapshot.default_branch,
                    )
                    if local_store:
                        local_store.log_audit_event(user.username, user.role.value, "commit_responsibilities_json", selected_repo, msg)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
