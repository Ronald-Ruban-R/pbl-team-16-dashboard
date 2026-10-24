"""
Settings, GitHub Connection Diagnostics, Rate-Limit Monitor & Security Audit View.

Organized into three clean tabs:
1. `🔌 GitHub Connection & Cache`: Per-repo connectivity table, API rate-limit status, and manual cache refresh.
2. `🔐 Security & Password Hasher`: Active user session info and PBKDF2-HMAC-SHA256 hash generator.
3. `📜 SQLite Audit & Database Management`: Security audit trail and 1-click local SQLite reset options.
"""

from __future__ import annotations

import sqlite3
from typing import Dict

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.config import DashboardConfig
from src.github_client import GitHubCohortClient
from src.security import AuthenticatedUser, hash_password_pbkdf2
from src.storage import MentorLocalStore


def render_settings_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    config: DashboardConfig,
    github_client: GitHubCohortClient,
    user: AuthenticatedUser,
    local_store: MentorLocalStore,
) -> None:
    """Render the decluttered, tab-organized Settings & Diagnostics view."""
    st.markdown("## ⚙️ Settings, GitHub Diagnostics & Security")

    rl = github_client.rate_limit
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Signed-In User", f"{user.username} ({user.role.value})")
    r2.metric("GitHub Auth Mode", github_client.auth.auth_mode)
    r3.metric("API Quota Remaining", f"{rl.remaining:,} / {rl.limit:,}")
    r4.metric(
        "Quota Resets (UTC)",
        rl.reset_datetime_utc.strftime("%H:%M:%S UTC") if rl.reset_datetime_utc else "N/A",
    )

    tab_gh, tab_sec, tab_db = st.tabs(
        [
            "🔌 GitHub Connection & Cache",
            "🔐 Security & Password Hasher",
            "📜 SQLite Audit Log & Reset",
        ]
    )

    # ------------------------------------------------------------------
    # Tab 1: GitHub Connection Diagnostics & Cache Refresh
    # ------------------------------------------------------------------
    with tab_gh:
        diag_rows = []
        for repo_name, ev in evaluations.items():
            snap = ev.snapshot
            diag_rows.append(
                {
                    "Organization": snap.org,
                    "Repository": repo_name,
                    "Status": "✅ Connected" if snap.accessible else "❌ Unreachable",
                    "HTTP": snap.status_code,
                    "Visibility": "Private" if snap.private else "Public",
                    "Default Branch": snap.default_branch if snap.accessible else "-",
                    "Files Indexed": sum(1 for e in snap.tree_entries if e.item_type == "file"),
                    "Recent Commits": len(snap.recent_commits),
                    "Fetched At (UTC)": snap.fetched_at_utc,
                    "Diagnostic Message": snap.error_message or "OK",
                }
            )
        st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True)

        c_btn1, c_btn2 = st.columns(2)
        if c_btn1.button("🔄 Clear API Cache & Refresh All Repositories", use_container_width=True):
            github_client.clear_cache()
            local_store.log_audit_event(
                username=user.username,
                role=user.role.value,
                action="manual_cache_refresh_all",
                details="Cleared all cached GitHub repository snapshots.",
            )
            st.success("Cache cleared. Reloading fresh repository data from GitHub...")
            st.rerun()

        with c_btn2:
            single_refresh = st.selectbox(
                "Refresh a Single Repository",
                options=[""] + list(evaluations.keys()),
                format_func=lambda x: "Select a repository to refresh..." if x == "" else x,
                label_visibility="collapsed",
            )
            if single_refresh and st.button(f"Refresh `{single_refresh}`", use_container_width=True):
                github_client.clear_cache(single_refresh)
                st.rerun()

    # ------------------------------------------------------------------
    # Tab 2: Security Session & Password Hash Generator
    # ------------------------------------------------------------------
    with tab_sec:
        st.markdown("#### Active User Session")
        st.write(
            f"- **Username:** `{user.username}`\n"
            f"- **Display Name:** {user.display_name}\n"
            f"- **Role:** `{user.role.value}`\n"
            f"- **Authorized Repositories:** {', '.join(f'`{r}`' for r in config.team_repos if user.can_access_repo(r))}"
        )

        if user.can_manage_settings():
            st.divider()
            st.markdown("#### 🔐 PBKDF2-HMAC-SHA256 Password Hash Generator")
            st.caption(
                "Generate a salted PBKDF2-HMAC-SHA256 hash for any new mentor or student account "
                "to paste into `.streamlit/secrets.toml` (or Streamlit Cloud Secrets)."
            )
            pw_col1, pw_col2 = st.columns([2, 1])
            pw_input = pw_col1.text_input("Enter password to hash", type="password", key="pw_gen_input")
            with pw_col2:
                st.write("")
                gen_clicked = st.button("Generate Hash", key="btn_pw_gen", use_container_width=True)
            if pw_input and gen_clicked:
                generated = hash_password_pbkdf2(pw_input)
                st.code(f'password_hash = "{generated}"', language="toml")

    # ------------------------------------------------------------------
    # Tab 3: Local SQLite Audit Log & One-Click Reset
    # ------------------------------------------------------------------
    with tab_db:
        if not local_store.available:
            st.warning(f"Local SQLite database unavailable: {local_store.last_error}")
        else:
            if user.can_manage_settings():
                with st.expander("🗑️ Reset / Clear Local SQLite Database Tables", expanded=False):
                    st.caption(
                        "Clearing local SQLite tables only resets local drafts or audit logs—it never deletes "
                        "any files in your GitHub repositories."
                    )
                    r_col1, r_col2, r_col3 = st.columns(3)
                    if r_col1.button("Clear Audit Log", use_container_width=True):
                        with sqlite3.connect(local_store.db_path) as conn:
                            conn.execute("DELETE FROM audit_log")
                            conn.commit()
                        st.success("Cleared `audit_log` table.")
                        st.rerun()
                    if r_col2.button("Clear Saved Review Drafts", use_container_width=True):
                        with sqlite3.connect(local_store.db_path) as conn:
                            conn.execute("DELETE FROM mentor_feedback_drafts")
                            conn.commit()
                        st.success("Cleared `mentor_feedback_drafts` table.")
                        st.rerun()
                    if r_col3.button("Clear Custom Settings", use_container_width=True):
                        with sqlite3.connect(local_store.db_path) as conn:
                            conn.execute("DELETE FROM mentor_settings")
                            conn.commit()
                        st.success("Cleared `mentor_settings` table.")
                        st.rerun()

            st.markdown("#### Recent Security & Action Audit Log")
            logs = local_store.get_recent_audit_logs(limit=50)
            if logs:
                st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
            else:
                st.info("No audit events recorded yet.")
