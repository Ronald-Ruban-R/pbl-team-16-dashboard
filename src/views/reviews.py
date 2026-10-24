"""
Review Management & Action Item Tracking View.

Organized into three uncluttered tabs:
1. `📋 Deliverables & Action Items`: Inspect a team's review submission, evidence links, and action items.
2. `✍️ Record Mentor Feedback`: Clean evaluation form to save feedback locally in SQLite or commit to GitHub.
3. `📊 Cohort Review Matrix & History`: Cross-team Review 1–4 progression matrix and consecutive review comparison.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary, is_evidence_verified_in_repo
from src.config import DashboardConfig
from src.github_client import GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser
from src.storage import MentorLocalStore
from src.validators import (
    VALID_SUBMISSION_STATUSES,
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
    """Render the decluttered, tab-organized Review Management view."""
    st.markdown("## 📝 Review Management & Action-Item Tracker")
    st.caption(
        "Inspect Review 1–4 deliverables, verify evidence in the repository, track action items, "
        "and record structured mentor feedback."
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
            else st.selectbox("Select Team", options=authorized_repos, key="rev_team_select")
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

    tab_inspect, tab_evaluate, tab_matrix = st.tabs(
        [
            f"📋 Review {selected_rev_num} Deliverables & Action Items",
            f"✍️ Record Review {selected_rev_num} Feedback",
            "📊 Review History & Cohort Matrix",
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
                        "Submitted": "✅ Yes" if d.submitted else "❌ No",
                        "Artifact Path": d.artifact_path or "-",
                        "Verified in Repo": (
                            "✅ Found"
                            if is_evidence_verified_in_repo(d.artifact_path, repo_paths_lower)
                            else "❌ Missing"
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
                            "Status": ai.status,
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
    # Tab 2: Record / Update Mentor Evaluation
    # ------------------------------------------------------------------
    with tab_evaluate:
        if not user.can_write_feedback(selected_repo):
            st.info("You have read-only access to review records.")
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
                improvements_val = sc3.text_area("Improvement Areas (1 per line)", value=initial_improvements, height=95)

                commit_to_gh = False
                if config.enable_github_writeback:
                    commit_to_gh = st.checkbox(
                        f"Also commit `reviews/review-{selected_rev_num}.json` directly to `{selected_repo}` on GitHub",
                        value=False,
                    )
                else:
                    st.caption(
                        "Evaluations are saved to your local SQLite database (`enable_github_writeback = false`)."
                    )

                submitted_btn = st.form_submit_button("💾 Save Review Evaluation")
                if submitted_btn:
                    strengths_list = [s.strip() for s in strengths_val.splitlines() if s.strip()]
                    concerns_list = [s.strip() for s in concerns_val.splitlines() if s.strip()]
                    improvements_list = [s.strip() for s in improvements_val.splitlines() if s.strip()]

                    existing_scores = (
                        saved_draft["criteria_scores"]
                        if saved_draft
                        else (
                            [
                                {
                                    "criterion": c.criterion,
                                    "max_score": c.max_score,
                                    "awarded_score": c.awarded_score,
                                    "comments": c.comments,
                                }
                                for c in repo_rev.criteria_scores
                            ]
                            if repo_rev
                            else []
                        )
                    )
                    existing_ais = (
                        saved_draft["action_items"]
                        if saved_draft
                        else (
                            [
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
                            if repo_rev
                            else []
                        )
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
                        payload = {
                            "review_id": f"review-{selected_rev_num}",
                            "review_number": selected_rev_num,
                            "review_name": (
                                repo_rev.review_name
                                if repo_rev
                                else (rev_def.title if rev_def else f"Review {selected_rev_num}")
                            ),
                            "scheduled_date": repo_rev.scheduled_date if repo_rev else None,
                            "submission_deadline": repo_rev.submission_deadline if repo_rev else None,
                            "submitted_at": repo_rev.submitted_at if repo_rev else None,
                            "submission_status": sub_status_val,
                            "deliverables": [
                                {
                                    "title": d.title,
                                    "required": d.required,
                                    "submitted": d.submitted,
                                    "artifact_path": d.artifact_path,
                                    "notes": d.notes,
                                }
                                for d in (repo_rev.deliverables if repo_rev else [])
                            ],
                            "evidence_links": repo_rev.evidence_links if repo_rev else {},
                            "mentor_feedback": feedback_val.strip(),
                            "criteria_scores": existing_scores,
                            "strengths": strengths_list,
                            "concerns": concerns_list,
                            "improvement_areas": improvements_list,
                            "action_items": existing_ais,
                        }
                        ok_gh, msg_gh = github_client.commit_review_file(
                            repo_name=selected_repo,
                            file_path=f"reviews/review-{selected_rev_num}.json",
                            json_payload=payload,
                            commit_message=f"chore(reviews): update Review {selected_rev_num} feedback by {user.username}",
                            branch=ev.snapshot.default_branch,
                        )
                        if ok_gh:
                            st.success(msg_gh)
                        else:
                            st.error(msg_gh)

    # ------------------------------------------------------------------
    # Tab 3: Consecutive Review Comparison & Cohort Matrix
    # ------------------------------------------------------------------
    with tab_matrix:
        st.markdown(f"#### Consecutive Review Comparison for `{selected_repo}`")
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
                        "Mentor Feedback": "Recorded" if r_obj.mentor_feedback else "None",
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
                    "Team Name": ev_item.metadata.team_name if ev_item.metadata else r,
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
                row["Open Action Items"] = len(ev_item.unresolved_action_items) if ev_item.snapshot.accessible else "-"
                matrix_rows.append(row)
            st.dataframe(pd.DataFrame(matrix_rows), use_container_width=True, hide_index=True)
