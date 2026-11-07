"""
Timeline, Schedule Variance & Interactive `project/timeline.json` Editor (`src/views/timeline.py`).

Organized into two clean tabs:
1. `Timeline & Schedule Variance`: Chronological schedule table and planned vs. actual variance analysis.
2. `Edit Timeline Events`: Owner-only interactive form to add, update, or delete events in `project/timeline.json`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary, parse_iso_date
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser
from src.storage import MentorLocalStore
from src.ui_theme import format_task_status
from src.validators import VALID_TASK_STATUSES, VALID_TIMELINE_TYPES


def render_timeline_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
    github_client: GitHubCohortClient | None = None,
    local_store: MentorLocalStore | None = None,
) -> None:
    """Render the Timeline & Milestones view with owner-only `project/timeline.json` editor."""
    st.markdown("## Project Timeline & Milestones")
    st.caption(
        "Monitor planned vs. actual milestone dates, schedule variance, and manage `project/timeline.json`."
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
            key="timeline_repo_select",
        )
    )
    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    if not ev.snapshot.accessible:
        st.error(f"Repository `{selected_repo}` is unavailable: {ev.snapshot.error_message}")
        return

    tab_schedule, tab_edit = st.tabs(
        [
            "Timeline & Schedule Variance",
            "Edit Timeline Events (project/timeline.json)",
        ]
    )

    with tab_schedule:
        if not ev.timeline:
            st.info(
                f"No timeline events found in `project/timeline.json` for `{selected_repo}`. "
                "Team Leads (`role = \"owner\"`) can add timeline events in the 'Edit Timeline Events' tab."
            )
        else:
            now = datetime.now(timezone.utc)
            completed_events = sum(1 for e in ev.timeline if e.status == "Completed")
            delayed_events = 0
            tl_rows = []
            for e in ev.timeline:
                p_dt = parse_iso_date(e.planned_date)
                a_dt = parse_iso_date(e.actual_date)
                variance_str = "-"
                if p_dt and a_dt:
                    diff_days = (a_dt - p_dt).days
                    if diff_days > 0:
                        variance_str = f"+{diff_days}d late"
                        delayed_events += 1
                    elif diff_days < 0:
                        variance_str = f"{abs(diff_days)}d early"
                    else:
                        variance_str = "On time"
                elif p_dt and e.status != "Completed" and p_dt < now:
                    overdue_days = (now - p_dt).days
                    variance_str = f"Overdue ({overdue_days}d)"
                    delayed_events += 1

                tl_rows.append(
                    {
                        "ID": e.event_id,
                        "Event / Milestone": e.title,
                        "Type": e.event_type,
                        "Planned Date": e.planned_date or "-",
                        "Actual Date": e.actual_date or "-",
                        "Status": format_task_status(e.status),
                        "Variance": variance_str,
                        "Owner": e.owner or "-",
                        "Description": e.description or "",
                    }
                )

            m1, m2, m3 = st.columns(3)
            m1.metric("Total Timeline Events", len(ev.timeline))
            m2.metric("Completed Events", f"{completed_events} / {len(ev.timeline)}")
            m3.metric("Delayed / Overdue Events", delayed_events)

            st.dataframe(pd.DataFrame(tl_rows), use_container_width=True, hide_index=True)

    with tab_edit:
        _render_timeline_editor(
            selected_repo=selected_repo,
            ev=ev,
            user=user,
            github_client=github_client,
            local_store=local_store,
        )


def _render_timeline_editor(
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
            "can add or edit events in `project/timeline.json`."
        )
        return

    if github_client is None or not github_client.auth.is_configured:
        st.warning("Configure a GitHub token (`[github].token`) in Secrets to commit timeline changes.")
        return

    st.caption(
        f"Team Lead Write Mode (`role = \"owner\"`): Add, update, or remove events in `project/timeline.json` for `{selected_repo}`."
    )

    existing_events = [
        {
            "event_id": e.event_id,
            "title": e.title,
            "event_type": e.event_type,
            "planned_date": e.planned_date,
            "actual_date": e.actual_date,
            "status": e.status,
            "description": e.description,
            "owner": e.owner,
        }
        for e in ev.timeline
    ]
    existing_ids = [e["event_id"] for e in existing_events]

    action_options = ["Add New Event"]
    if existing_ids:
        action_options.extend(["Update Existing Event", "Delete Event"])

    mode = st.radio(
        "Event Action",
        options=action_options,
        horizontal=True,
        key=f"tl_mode_{selected_repo}",
    )

    if mode == "Delete Event" and existing_ids:
        del_id = st.selectbox(
            "Select Event to Delete",
            options=existing_ids,
            format_func=lambda eid: next(
                (f"{e['event_id']}: {e['title']} ({e['planned_date'] or 'No date'})" for e in existing_events if e["event_id"] == eid),
                eid,
            ),
        )
        if st.button(f"Delete Event `{del_id}` & Commit to GitHub"):
            updated_list = [e for e in existing_events if e["event_id"] != del_id]
            ok, msg = github_client.commit_structured_json(
                repo_name=selected_repo,
                file_path="project/timeline.json",
                json_payload={"events": updated_list},
                commit_message=f"chore(timeline): delete event {del_id} by {user.username}",
                branch=ev.snapshot.default_branch,
            )
            if local_store:
                local_store.log_audit_event(user.username, user.role.value, "delete_timeline_event", selected_repo, msg)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        return

    sel_event = None
    if mode == "Update Existing Event" and existing_ids:
        chosen_id = st.selectbox(
            "Select Event to Edit",
            options=existing_ids,
            format_func=lambda eid: next(
                (f"{e['event_id']}: {e['title']} ({e['status']})" for e in existing_events if e["event_id"] == eid),
                eid,
            ),
        )
        sel_event = next((e for e in existing_events if e["event_id"] == chosen_id), None)

    default_id = sel_event["event_id"] if sel_event else f"E{len(existing_events) + 1}"

    with st.form(f"tl_editor_form_{selected_repo}"):
        c1, c2, c3 = st.columns([1, 2.5, 1.2])
        e_id = c1.text_input("Event ID", value=default_id)
        e_title = c2.text_input(
            "Event / Milestone Title",
            value=sel_event["title"] if sel_event else "",
            placeholder="e.g., Complete Architecture Specification",
        )
        e_type = c3.selectbox(
            "Event Type",
            options=list(VALID_TIMELINE_TYPES),
            index=(
                list(VALID_TIMELINE_TYPES).index(sel_event["event_type"])
                if sel_event and sel_event["event_type"] in VALID_TIMELINE_TYPES
                else 0
            ),
        )

        c4, c5, c6, c7 = st.columns(4)
        e_planned = c4.text_input(
            "Planned Date (YYYY-MM-DD)",
            value=sel_event.get("planned_date") or "" if sel_event else "",
            placeholder="2026-10-15",
        )
        e_actual = c5.text_input(
            "Actual Date (YYYY-MM-DD)",
            value=sel_event.get("actual_date") or "" if sel_event else "",
            placeholder="Leave blank if pending",
        )
        e_status = c6.selectbox(
            "Status",
            options=list(VALID_TASK_STATUSES),
            index=(
                list(VALID_TASK_STATUSES).index(sel_event["status"])
                if sel_event and sel_event["status"] in VALID_TASK_STATUSES
                else 0
            ),
        )
        e_owner = c7.text_input(
            "Owner / Lead",
            value=sel_event.get("owner") or "" if sel_event else "",
            placeholder="e.g., All Members",
        )

        e_desc = st.text_area(
            "Description / Notes",
            value=sel_event.get("description") or "" if sel_event else "",
            height=68,
        )

        if st.form_submit_button("Commit Timeline to `project/timeline.json` on GitHub"):
            if not e_id.strip() or not e_title.strip():
                st.error("Event ID and Title are required.")
            else:
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                actual_val = e_actual.strip() or (today_str if e_status == "Completed" else None)
                new_ev = {
                    "event_id": e_id.strip(),
                    "title": e_title.strip(),
                    "event_type": e_type,
                    "planned_date": e_planned.strip() or None,
                    "actual_date": actual_val,
                    "status": e_status,
                    "description": e_desc.strip(),
                    "owner": e_owner.strip(),
                }
                updated_list: List[Dict] = []
                replaced = False
                for item in existing_events:
                    if item["event_id"] == e_id.strip():
                        updated_list.append(new_ev)
                        replaced = True
                    else:
                        updated_list.append(item)
                if not replaced:
                    updated_list.append(new_ev)

                ok, msg = github_client.commit_structured_json(
                    repo_name=selected_repo,
                    file_path="project/timeline.json",
                    json_payload={"events": updated_list},
                    commit_message=f"chore(timeline): update event {e_id.strip()} by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                if local_store:
                    local_store.log_audit_event(user.username, user.role.value, "commit_timeline_json", selected_repo, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
