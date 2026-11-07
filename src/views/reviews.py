"""
Review Management, Submission Editor & Action Item Tracking View (`src/views/reviews.py`).

Organized into four clean, consistent tabs:
1. `Deliverables & Action Items`: Inspect a team's review submission, evidence links, and action items.
2. `Edit Review N JSON`: Owner-only interactive forms to create or update `reviews/review-N.json` directly on GitHub.
3. `Record Mentor Feedback`: Clean evaluation form to save feedback locally in SQLite or commit to GitHub.
4. `Review History & Cohort Matrix`: Cross-team Review 1–4 progression matrix and consecutive review comparison.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary, is_evidence_verified_in_repo
from src.config import DashboardConfig, ReviewDefinition
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser
from src.storage import MentorLocalStore
from src.ui_theme import format_bool_indicator, format_task_status
from src.validators import (
    VALID_SUBMISSION_STATUSES,
    VALID_TASK_STATUSES,
    ReviewRecord,
)


def render_reviews_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    config: DashboardConfig,
    github_client: GitHubCohortClient,
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
    local_store: MentorLocalStore,
) -> None:
    """Render the Review Management and JSON Editor view."""
    st.markdown("## Review Management & Action-Item Tracker")
    st.caption(
        "Inspect Review 1–4 deliverables, verify evidence in the repository, update review submissions, "
        "track action items, and record structured mentor feedback."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    sel_col1, sel_col2 = st.columns(2)
    with sel_col1:
        selected_repo = (
            authorized_repos[0]
            if len(authorized_repos) == 1
            else st.selectbox(
                "Select Team",
                options=authorized_repos,
                format_func=lambda r: f"{r} — {evaluations[r].display_team_name}",
                key="rev_team_select",
            )
        )
    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    review_numbers = sorted({r.review_number for r in config.reviews} | set(ev.reviews.keys()))
    with sel_col2:
        selected_rev_num = st.selectbox(
            "Select Review Stage",
            options=review_numbers,
            format_func=lambda n: next(
                (rd.title for rd in config.reviews if rd.review_number == n),
                f"Review {n}",
            ),
        )

    if not ev.snapshot.accessible:
        st.error(f"Repository `{selected_repo}` is currently unavailable: {ev.snapshot.error_message}")
        return

    repo_rev: ReviewRecord | None = ev.reviews.get(selected_rev_num)
    saved_draft = local_store.get_feedback_draft(selected_repo, selected_rev_num)
    rev_def = next((rd for rd in config.reviews if rd.review_number == selected_rev_num), None)
    repo_paths_lower = {
        e.path.strip("/").lower() for e in ev.snapshot.tree_entries if e.item_type == "file"
    }

    tab_inspect, tab_edit_sub, tab_evaluate, tab_matrix = st.tabs(
        [
            f"Review {selected_rev_num} Deliverables & Action Items",
            f"Edit Review {selected_rev_num} JSON",
            f"Record Review {selected_rev_num} Feedback",
            "Review History & Cohort Matrix",
        ]
    )

    # ------------------------------------------------------------------
    # Tab 1: Deliverables, Evidence Verification & Action Items
    # ------------------------------------------------------------------
    with tab_inspect:
        d_col1, d_col2 = st.columns([1.25, 1])
        with d_col1:
            st.markdown(f"#### Deliverables Checklist — Review {selected_rev_num}")
            if repo_rev and repo_rev.deliverables:
                deliv_rows = [
                    {
                        "Deliverable": d.title,
                        "Required": "Yes" if d.required else "Optional",
                        "Submitted": format_bool_indicator(d.submitted, "Submitted", "No"),
                        "Artifact Path": d.artifact_path or "-",
                        "Verified in Repo": format_bool_indicator(
                            is_evidence_verified_in_repo(d.artifact_path, repo_paths_lower),
                            "Verified",
                            "Missing",
                        ),
                        "Notes": d.notes or "",
                    }
                    for d in repo_rev.deliverables
                ]
                st.dataframe(pd.DataFrame(deliv_rows), use_container_width=True, hide_index=True)
            elif rev_def:
                st.info(
                    f"`reviews/review-{selected_rev_num}.json` has not been submitted yet. "
                    "Expected deliverables for this stage:"
                )
                for req_d in rev_def.required_deliverables:
                    st.markdown(f"- {req_d}")

            if repo_rev and repo_rev.evidence_links:
                st.markdown("**Direct Evidence Links**")
                for label, link_val in repo_rev.evidence_links.items():
                    if not link_val:
                        continue
                    full_url = (
                        link_val
                        if link_val.startswith(("https://", "http://"))
                        else f"{ev.snapshot.html_url}/blob/{ev.snapshot.default_branch}/{link_val.lstrip('/')}"
                    )
                    st.markdown(f"- **{label.title()}:** [{link_val}]({full_url})")

        with d_col2:
            st.markdown(f"#### Action Items — Review {selected_rev_num}")
            if repo_rev and repo_rev.action_items:
                ai_df = pd.DataFrame(
                    [
                        {
                            "ID": ai.action_id,
                            "Action Item": ai.description,
                            "Assignee": ai.assigned_to,
                            "Due": ai.due_date or "-",
                            "Status": format_task_status(ai.status),
                            "Evidence": ai.resolution_evidence or "-",
                        }
                        for ai in repo_rev.action_items
                    ]
                )
                st.dataframe(ai_df, use_container_width=True, hide_index=True)
            else:
                st.info("No action items recorded in repository for this review.")

            if repo_rev and repo_rev.mentor_feedback:
                with st.container(border=True):
                    st.markdown("**Recorded Mentor Feedback**")
                    st.write(repo_rev.mentor_feedback)

    # ------------------------------------------------------------------
    # Tab 2: Edit Review Submission, Deliverables & Action Items (Owner Only)
    # ------------------------------------------------------------------
    with tab_edit_sub:
        _render_review_json_editor(
            selected_repo=selected_repo,
            selected_rev_num=selected_rev_num,
            ev=ev,
            repo_rev=repo_rev,
            rev_def=rev_def,
            user=user,
            github_client=github_client,
            local_store=local_store,
        )

    # ------------------------------------------------------------------
    # Tab 3: Record / Update Mentor Evaluation
    # ------------------------------------------------------------------
    with tab_evaluate:
        if not user.can_write_feedback(selected_repo):
            st.info(
                f"Signed in as `{user.username}` (`role = \"{user.role.value}\"`). "
                "Team members have read-only access to review records."
            )
        else:
            if saved_draft:
                st.success(
                    f"Loaded saved draft from local SQLite database (updated `{saved_draft['updated_at_utc']}` "
                    f"by `{saved_draft['mentor_username']}`)."
                )

            initial_status = (
                saved_draft["submission_status"]
                if saved_draft
                else (repo_rev.submission_status if repo_rev else "Not Submitted")
            )
            if initial_status not in VALID_SUBMISSION_STATUSES:
                initial_status = "Not Submitted"

            initial_feedback = (
                saved_draft["mentor_feedback"]
                if saved_draft
                else (repo_rev.mentor_feedback if repo_rev and repo_rev.mentor_feedback else "")
            )
            initial_strengths = "\n".join(
                saved_draft["strengths"]
                if saved_draft
                else (repo_rev.strengths if repo_rev else [])
            )
            initial_concerns = "\n".join(
                saved_draft["concerns"]
                if saved_draft
                else (repo_rev.concerns if repo_rev else [])
            )
            initial_improvements = "\n".join(
                saved_draft["improvement_areas"]
                if saved_draft
                else (repo_rev.improvement_areas if repo_rev else [])
            )

            with st.form(key=f"review_feedback_form_{selected_repo}_{selected_rev_num}"):
                sub_status_val = st.selectbox(
                    "Submission Status",
                    options=list(VALID_SUBMISSION_STATUSES),
                    index=list(VALID_SUBMISSION_STATUSES).index(initial_status),
                )
                feedback_val = st.text_area(
                    "Overall Mentor Feedback",
                    value=initial_feedback,
                    height=100,
                    placeholder="Enter evidence-based review feedback...",
                )
                sc1, sc2, sc3 = st.columns(3)
                strengths_val = sc1.text_area("Strengths (1 per line)", value=initial_strengths, height=95)
                concerns_val = sc2.text_area("Concerns (1 per line)", value=initial_concerns, height=95)
                improvements_val = sc3.text_area(
                    "Improvement Areas (1 per line)", value=initial_improvements, height=95
                )

                commit_to_gh = False
                if config.enable_github_writeback:
                    commit_to_gh = st.checkbox(
                        f"Also commit `reviews/review-{selected_rev_num}.json` directly to `{selected_repo}` on GitHub",
                        value=True if user.can_edit_repo_metadata(selected_repo) else False,
                    )
                else:
                    st.caption(
                        "Evaluations are saved to your local SQLite database (`enable_github_writeback = false`)."
                    )

                submitted_btn = st.form_submit_button("Save Review Evaluation")
                if submitted_btn:
                    strengths_list = [s.strip() for s in strengths_val.splitlines() if s.strip()]
                    concerns_list = [s.strip() for s in concerns_val.splitlines() if s.strip()]
                    improvements_list = [s.strip() for s in improvements_val.splitlines() if s.strip()]

                    existing_scores = (
                        saved_draft["criteria_scores"]
                        if saved_draft
                        else _default_scores_list(repo_rev)
                    )
                    existing_ais = (
                        saved_draft["action_items"]
                        if saved_draft
                        else _default_action_items_list(repo_rev)
                    )

                    saved_ok = local_store.save_feedback_draft(
                        repo_name=selected_repo,
                        review_number=selected_rev_num,
                        mentor_username=user.username,
                        submission_status=sub_status_val,
                        mentor_feedback=feedback_val.strip(),
                        strengths=strengths_list,
                        concerns=concerns_list,
                        improvement_areas=improvements_list,
                        criteria_scores=existing_scores,
                        action_items=existing_ais,
                        committed_to_github=commit_to_gh,
                    )
                    local_store.log_audit_event(
                        username=user.username,
                        role=user.role.value,
                        action="save_review_feedback",
                        target_repo=selected_repo,
                        details=f"Saved Review {selected_rev_num} evaluation (status={sub_status_val}).",
                    )

                    if saved_ok:
                        st.success(f"Saved Review {selected_rev_num} evaluation for `{selected_repo}`.")
                    if commit_to_gh and config.enable_github_writeback:
                        payload = _build_review_payload(
                            selected_rev_num=selected_rev_num,
                            repo_rev=repo_rev,
                            rev_def=rev_def,
                            submission_status=sub_status_val,
                            mentor_feedback=feedback_val.strip(),
                            strengths=strengths_list,
                            concerns=concerns_list,
                            improvement_areas=improvements_list,
                            criteria_scores=existing_scores,
                            action_items=existing_ais,
                        )
                        ok_gh, msg_gh = github_client.commit_review_file(
                            repo_name=selected_repo,
                            file_path=f"reviews/review-{selected_rev_num}.json",
                            json_payload=payload,
                            commit_message=f"chore(reviews): update Review {selected_rev_num} feedback by {user.username}",
                            branch=ev.snapshot.default_branch,
                        )
                        if ok_gh:
                            st.success(msg_gh)
                            st.rerun()
                        else:
                            st.error(msg_gh)

    # ------------------------------------------------------------------
    # Tab 4: Consecutive Review Comparison & Cohort Matrix
    # ------------------------------------------------------------------
    with tab_matrix:
        st.markdown(f"#### Consecutive Review Comparison for {ev.display_team_name}")
        comp_rows = []
        for r_num in review_numbers:
            r_obj = ev.reviews.get(r_num)
            if r_obj:
                open_ais = sum(1 for ai in r_obj.action_items if ai.status != "Completed")
                done_ais = sum(1 for ai in r_obj.action_items if ai.status == "Completed")
                awarded = sum(c.awarded_score for c in r_obj.criteria_scores if c.awarded_score is not None)
                max_pts = sum(c.max_score for c in r_obj.criteria_scores if c.awarded_score is not None)
                comp_rows.append(
                    {
                        "Review": f"Review {r_num}: {r_obj.review_name}",
                        "Scheduled Date": r_obj.scheduled_date or "-",
                        "Deadline": r_obj.submission_deadline or "-",
                        "Status": r_obj.submission_status,
                        "Deliverables Submitted": f"{sum(1 for d in r_obj.deliverables if d.submitted)}/{len(r_obj.deliverables)}",
                        "Score": f"{awarded:.1f} / {max_pts:.1f}" if max_pts > 0 else "Not Scored",
                        "Action Items (Resolved/Total)": f"{done_ais}/{open_ais + done_ais}",
                        "Mentor Feedback": "✓ Recorded" if r_obj.mentor_feedback else "None",
                    }
                )
            else:
                comp_rows.append(
                    {
                        "Review": f"Review {r_num}",
                        "Scheduled Date": "-",
                        "Deadline": "-",
                        "Status": "Not Reported",
                        "Deliverables Submitted": "-",
                        "Score": "Not Scored",
                        "Action Items (Resolved/Total)": "-",
                        "Mentor Feedback": "None",
                    }
                )
        st.dataframe(pd.DataFrame(comp_rows), use_container_width=True, hide_index=True)

        if len(authorized_repos) > 1:
            st.markdown("#### Cohort-Wide Review Progression Matrix (Reviews 1–4)")
            matrix_rows: List[Dict[str, Any]] = []
            for r in authorized_repos:
                ev_item = evaluations[r]
                row: Dict[str, Any] = {
                    "Repository": r,
                    "Team Name": ev_item.display_team_name,
                }
                for rev_def_item in config.reviews:
                    rev_rec = ev_item.reviews.get(rev_def_item.review_number)
                    draft = local_store.get_feedback_draft(r, rev_def_item.review_number)
                    if not ev_item.snapshot.accessible:
                        row[f"Review {rev_def_item.review_number}"] = "Unavailable"
                    elif rev_rec:
                        row[f"Review {rev_def_item.review_number}"] = rev_rec.submission_status
                    elif draft:
                        row[f"Review {rev_def_item.review_number}"] = f"Draft ({draft['submission_status']})"
                    else:
                        row[f"Review {rev_def_item.review_number}"] = "Not Reported"
                row["Open Action Items"] = (
                    len(ev_item.unresolved_action_items) if ev_item.snapshot.accessible else "-"
                )
                matrix_rows.append(row)
            st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True, hide_index=True)


def _default_deliverables_list(
    repo_rev: ReviewRecord | None,
    rev_def: ReviewDefinition | None,
) -> List[Dict[str, Any]]:
    if repo_rev and repo_rev.deliverables:
        return [
            {
                "title": d.title,
                "required": d.required,
                "submitted": d.submitted,
                "artifact_path": d.artifact_path,
                "notes": d.notes,
            }
            for d in repo_rev.deliverables
        ]
    if rev_def and rev_def.required_deliverables:
        return [
            {
                "title": req_title,
                "required": True,
                "submitted": False,
                "artifact_path": None,
                "notes": "",
            }
            for req_title in rev_def.required_deliverables
        ]
    return []


def _default_action_items_list(repo_rev: ReviewRecord | None) -> List[Dict[str, Any]]:
    if repo_rev and repo_rev.action_items:
        return [
            {
                "action_id": a.action_id,
                "description": a.description,
                "assigned_to": a.assigned_to,
                "due_date": a.due_date,
                "status": a.status,
                "resolution_evidence": a.resolution_evidence,
                "completed_date": a.completed_date,
            }
            for a in repo_rev.action_items
        ]
    return []


def _default_scores_list(repo_rev: ReviewRecord | None) -> List[Dict[str, Any]]:
    if repo_rev and repo_rev.criteria_scores:
        return [
            {
                "criterion": c.criterion,
                "max_score": c.max_score,
                "awarded_score": c.awarded_score,
                "comments": c.comments,
            }
            for c in repo_rev.criteria_scores
        ]
    return []


def _build_review_payload(
    selected_rev_num: int,
    repo_rev: ReviewRecord | None,
    rev_def: ReviewDefinition | None,
    submission_status: str | None = None,
    scheduled_date: str | None = None,
    submission_deadline: str | None = None,
    submitted_at: str | None = None,
    review_name: str | None = None,
    deliverables: List[Dict[str, Any]] | None = None,
    evidence_links: Dict[str, str] | None = None,
    mentor_feedback: str | None = None,
    strengths: List[str] | None = None,
    concerns: List[str] | None = None,
    improvement_areas: List[str] | None = None,
    criteria_scores: List[Dict[str, Any]] | None = None,
    action_items: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Assemble a complete `reviews/review-N.json` dictionary preserving existing fields."""
    return {
        "review_id": f"review-{selected_rev_num}",
        "review_number": selected_rev_num,
        "review_name": (
            review_name
            if review_name is not None
            else (
                repo_rev.review_name
                if repo_rev
                else (rev_def.title if rev_def else f"Review {selected_rev_num}")
            )
        ),
        "scheduled_date": (
            scheduled_date
            if scheduled_date is not None
            else (repo_rev.scheduled_date if repo_rev else None)
        ),
        "submission_deadline": (
            submission_deadline
            if submission_deadline is not None
            else (repo_rev.submission_deadline if repo_rev else None)
        ),
        "submitted_at": (
            submitted_at
            if submitted_at is not None
            else (repo_rev.submitted_at if repo_rev else None)
        ),
        "submission_status": (
            submission_status
            if submission_status is not None
            else (repo_rev.submission_status if repo_rev else "Not Submitted")
        ),
        "deliverables": (
            deliverables
            if deliverables is not None
            else _default_deliverables_list(repo_rev, rev_def)
        ),
        "evidence_links": (
            evidence_links
            if evidence_links is not None
            else (dict(repo_rev.evidence_links) if repo_rev else {})
        ),
        "mentor_feedback": (
            mentor_feedback
            if mentor_feedback is not None
            else (repo_rev.mentor_feedback if repo_rev else "")
        ),
        "criteria_scores": (
            criteria_scores
            if criteria_scores is not None
            else _default_scores_list(repo_rev)
        ),
        "strengths": (
            strengths
            if strengths is not None
            else (list(repo_rev.strengths) if repo_rev else [])
        ),
        "concerns": (
            concerns
            if concerns is not None
            else (list(repo_rev.concerns) if repo_rev else [])
        ),
        "improvement_areas": (
            improvement_areas
            if improvement_areas is not None
            else (list(repo_rev.improvement_areas) if repo_rev else [])
        ),
        "action_items": (
            action_items
            if action_items is not None
            else _default_action_items_list(repo_rev)
        ),
    }


def _render_review_json_editor(
    selected_repo: str,
    selected_rev_num: int,
    ev: TeamEvaluationSummary,
    repo_rev: ReviewRecord | None,
    rev_def: ReviewDefinition | None,
    user: AuthenticatedUser,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore,
) -> None:
    """Render owner-only interactive forms for `reviews/review-N.json`."""
    if not user.can_edit_repo_metadata(selected_repo):
        st.info(
            f"Signed in as `{user.username}` (`role = \"{user.role.value}\"`). "
            "You have **read-only** access. Only Team Leads (`role = \"owner\"` in Secrets) "
            f"can edit and commit `reviews/review-{selected_rev_num}.json`."
        )
        return

    if not github_client.auth.is_configured:
        st.warning("Configure a GitHub token (`[github].token`) in Secrets to commit changes to GitHub.")
        return

    st.caption(
        f"Team Lead Write Mode (`role = \"owner\"`): Update `reviews/review-{selected_rev_num}.json` "
        f"directly in `{selected_repo}` without editing raw JSON."
    )

    editor_section = st.radio(
        "Select Review Section to Edit",
        options=[
            "1. Submission Metadata & Evidence Links",
            "2. Deliverables Checklist",
            "3. Action Items",
        ],
        horizontal=True,
        key=f"rev_json_sec_{selected_repo}_{selected_rev_num}",
    )

    if editor_section.startswith("1."):
        ev_links = dict(repo_rev.evidence_links) if repo_rev and repo_rev.evidence_links else {}
        init_status = (
            repo_rev.submission_status
            if repo_rev and repo_rev.submission_status in VALID_SUBMISSION_STATUSES
            else "Not Submitted"
        )

        with st.form(f"rev_meta_form_{selected_repo}_{selected_rev_num}"):
            c1, c2 = st.columns([2, 1])
            r_name = c1.text_input(
                "Review Title",
                value=(
                    repo_rev.review_name
                    if repo_rev
                    else (rev_def.title if rev_def else f"Review {selected_rev_num}")
                ),
            )
            r_status = c2.selectbox(
                "Submission Status",
                options=list(VALID_SUBMISSION_STATUSES),
                index=list(VALID_SUBMISSION_STATUSES).index(init_status),
            )

            d1, d2, d3 = st.columns(3)
            r_sched = d1.text_input(
                "Scheduled Date (YYYY-MM-DD)",
                value=repo_rev.scheduled_date or "" if repo_rev else "",
            )
            r_dead = d2.text_input(
                "Submission Deadline (YYYY-MM-DD)",
                value=repo_rev.submission_deadline or "" if repo_rev else "",
            )
            r_sub_at = d3.text_input(
                "Submitted Date (YYYY-MM-DD)",
                value=(
                    repo_rev.submitted_at or datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    if repo_rev
                    else ""
                ),
            )

            st.markdown("**Direct Evidence Links (Repo Paths or URLs)**")
            e1, e2 = st.columns(2)
            ev_pres = e1.text_input(
                "Presentation Path / URL",
                value=ev_links.get("presentation", ""),
                placeholder="deliverables/review1_slides.pdf",
            )
            ev_rep = e2.text_input(
                "Report Path / URL",
                value=ev_links.get("report", ""),
                placeholder="documentation/architecture_spec.md",
            )
            e3, e4 = st.columns(2)
            ev_proto = e3.text_input(
                "Prototype Path / URL",
                value=ev_links.get("prototype", ""),
                placeholder="deliverables/prototype_v1/",
            )
            ev_res = e4.text_input(
                "Research / Dataset Path / URL",
                value=ev_links.get("research", ""),
                placeholder="research/literature_review.md",
            )

            if st.form_submit_button(f"Save Review {selected_rev_num} Metadata & Evidence Links"):
                new_links: Dict[str, str] = {}
                if ev_pres.strip():
                    new_links["presentation"] = ev_pres.strip()
                if ev_rep.strip():
                    new_links["report"] = ev_rep.strip()
                if ev_proto.strip():
                    new_links["prototype"] = ev_proto.strip()
                if ev_res.strip():
                    new_links["research"] = ev_res.strip()

                payload = _build_review_payload(
                    selected_rev_num=selected_rev_num,
                    repo_rev=repo_rev,
                    rev_def=rev_def,
                    review_name=r_name.strip(),
                    submission_status=r_status,
                    scheduled_date=r_sched.strip() or None,
                    submission_deadline=r_dead.strip() or None,
                    submitted_at=r_sub_at.strip() or None,
                    evidence_links=new_links,
                )
                ok, msg = github_client.commit_structured_json(
                    repo_name=selected_repo,
                    file_path=f"reviews/review-{selected_rev_num}.json",
                    json_payload=payload,
                    commit_message=f"chore(reviews): update Review {selected_rev_num} metadata and links by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                local_store.log_audit_event(user.username, user.role.value, "commit_review_json", selected_repo, msg)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    elif editor_section.startswith("2."):
        deliv_list = _default_deliverables_list(repo_rev, rev_def)
        titles = [d["title"] for d in deliv_list]
        pick_d = st.selectbox(
            "Select Deliverable to Edit (or '+ Add New Deliverable')",
            options=titles + ["+ Add New Deliverable"],
            key=f"pick_deliv_{selected_repo}_{selected_rev_num}",
        )
        sel_d = (
            None
            if pick_d == "+ Add New Deliverable"
            else next((d for d in deliv_list if d["title"] == pick_d), None)
        )

        with st.form(f"rev_deliv_form_{selected_repo}_{selected_rev_num}"):
            d_title = st.text_input("Deliverable Title", value=sel_d["title"] if sel_d else "")
            c1, c2, c3 = st.columns([1, 1, 2])
            d_req = c1.checkbox("Required Deliverable", value=bool(sel_d["required"]) if sel_d else True)
            d_sub = c2.checkbox("Submitted", value=bool(sel_d["submitted"]) if sel_d else False)
            d_path = c3.text_input(
                "Repository File Path or URL",
                value=sel_d.get("artifact_path") or "" if sel_d else "",
                placeholder="e.g., research/literature_survey.md",
            )
            d_notes = st.text_input("Notes / Comments", value=sel_d.get("notes") or "" if sel_d else "")

            if st.form_submit_button(f"Save Deliverable to `reviews/review-{selected_rev_num}.json`"):
                if not d_title.strip():
                    st.error("Deliverable Title is required.")
                else:
                    new_item = {
                        "title": d_title.strip(),
                        "required": d_req,
                        "submitted": d_sub,
                        "artifact_path": d_path.strip() or None,
                        "notes": d_notes.strip(),
                    }
                    updated_delivs = []
                    replaced = False
                    for item in deliv_list:
                        if item["title"] == (sel_d["title"] if sel_d else d_title.strip()):
                            updated_delivs.append(new_item)
                            replaced = True
                        else:
                            updated_delivs.append(item)
                    if not replaced:
                        updated_delivs.append(new_item)

                    payload = _build_review_payload(
                        selected_rev_num=selected_rev_num,
                        repo_rev=repo_rev,
                        rev_def=rev_def,
                        deliverables=updated_delivs,
                    )
                    ok, msg = github_client.commit_structured_json(
                        repo_name=selected_repo,
                        file_path=f"reviews/review-{selected_rev_num}.json",
                        json_payload=payload,
                        commit_message=f"chore(reviews): update deliverable '{d_title.strip()}' in Review {selected_rev_num} by {user.username}",
                        branch=ev.snapshot.default_branch,
                    )
                    local_store.log_audit_event(
                        user.username, user.role.value, "commit_review_deliverable", selected_repo, msg
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

    else:
        ai_list = _default_action_items_list(repo_rev)
        ai_ids = [a["action_id"] for a in ai_list]
        ai_mode = st.radio(
            "Action Item Operation",
            options=(
                ["Add / Update Action Item", "Delete Action Item"]
                if ai_ids
                else ["Add / Update Action Item"]
            ),
            horizontal=True,
            key=f"ai_op_{selected_repo}_{selected_rev_num}",
        )

        if ai_mode == "Delete Action Item" and ai_ids:
            del_ai = st.selectbox("Select Action Item to Delete", options=ai_ids)
            if st.button(f"Delete Action Item `{del_ai}`"):
                updated_ais = [a for a in ai_list if a["action_id"] != del_ai]
                payload = _build_review_payload(
                    selected_rev_num=selected_rev_num,
                    repo_rev=repo_rev,
                    rev_def=rev_def,
                    action_items=updated_ais,
                )
                ok, msg = github_client.commit_structured_json(
                    repo_name=selected_repo,
                    file_path=f"reviews/review-{selected_rev_num}.json",
                    json_payload=payload,
                    commit_message=f"chore(reviews): remove action item {del_ai} in Review {selected_rev_num} by {user.username}",
                    branch=ev.snapshot.default_branch,
                )
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
            return

        pick_ai = st.selectbox(
            "Select Action Item to Edit (or '+ Add New Action Item')",
            options=ai_ids + ["+ Add New Action Item"],
            format_func=lambda x: (
                x
                if x.startswith("+")
                else next(
                    (f"{a['action_id']}: {a['description']} ({a['status']})" for a in ai_list if a["action_id"] == x),
                    x,
                )
            ),
            key=f"pick_ai_{selected_repo}_{selected_rev_num}",
        )
        sel_ai = (
            None
            if pick_ai.startswith("+")
            else next((a for a in ai_list if a["action_id"] == pick_ai), None)
        )

        with st.form(f"rev_ai_form_{selected_repo}_{selected_rev_num}"):
            c1, c2, c3 = st.columns([1, 1.5, 1.2])
            a_id = c1.text_input(
                "Action ID",
                value=sel_ai["action_id"] if sel_ai else f"R{selected_rev_num}-A{len(ai_list) + 1}",
            )
            a_owner = c2.text_input("Assigned To", value=sel_ai["assigned_to"] if sel_ai else "")
            a_status = c3.selectbox(
                "Status",
                options=list(VALID_TASK_STATUSES),
                index=(
                    list(VALID_TASK_STATUSES).index(sel_ai["status"])
                    if sel_ai and sel_ai["status"] in VALID_TASK_STATUSES
                    else 0
                ),
            )
            a_desc = st.text_input("Action Item Description", value=sel_ai["description"] if sel_ai else "")
            c4, c5 = st.columns([1, 2])
            a_due = c4.text_input("Due Date (YYYY-MM-DD)", value=sel_ai.get("due_date") or "" if sel_ai else "")
            a_ev = c5.text_input(
                "Resolution Evidence (Path or Notes)",
                value=sel_ai.get("resolution_evidence") or "" if sel_ai else "",
                placeholder="e.g., documentation/updated_schema.md",
            )

            if st.form_submit_button(f"Save Action Item to `reviews/review-{selected_rev_num}.json`"):
                if not a_id.strip() or not a_desc.strip():
                    st.error("Action ID and Description are required.")
                else:
                    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    new_ai = {
                        "action_id": a_id.strip(),
                        "description": a_desc.strip(),
                        "assigned_to": a_owner.strip() or "Unassigned",
                        "due_date": a_due.strip() or None,
                        "status": a_status,
                        "resolution_evidence": a_ev.strip() or None,
                        "completed_date": (
                            today_str
                            if a_status == "Completed"
                            else (sel_ai.get("completed_date") if sel_ai else None)
                        ),
                    }
                    updated_ais = []
                    replaced = False
                    for item in ai_list:
                        if item["action_id"] == a_id.strip():
                            updated_ais.append(new_ai)
                            replaced = True
                        else:
                            updated_ais.append(item)
                    if not replaced:
                        updated_ais.append(new_ai)

                    payload = _build_review_payload(
                        selected_rev_num=selected_rev_num,
                        repo_rev=repo_rev,
                        rev_def=rev_def,
                        action_items=updated_ais,
                    )
                    ok, msg = github_client.commit_structured_json(
                        repo_name=selected_repo,
                        file_path=f"reviews/review-{selected_rev_num}.json",
                        json_payload=payload,
                        commit_message=f"chore(reviews): update action item {a_id.strip()} in Review {selected_rev_num} by {user.username}",
                        branch=ev.snapshot.default_branch,
                    )
                    local_store.log_audit_event(
                        user.username, user.role.value, "commit_review_action_item", selected_repo, msg
                    )
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
