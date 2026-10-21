"""
Settings, GitHub Connection Diagnostics, Rate-Limit Monitor & Security Audit View.

Provides:
- Real-time verification of GitHub authentication mode (`github_app` vs `fine_grained_pat`),
  organization reachability (`PBL-Cohort-X-Teams-13-18`), and per-repository access diagnostics.
- GitHub API Rate-Limit monitor (`Limit`, `Remaining`, `Used`, `Reset Time UTC`).
- Cache management (clear global cache or single-repository cache).
- PBKDF2-HMAC-SHA256 password hash generator for configuring `.streamlit/secrets.toml`.
- Local SQLite Audit Log viewer.
"""

from __future__ import annotations

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
    """Render the Settings, Diagnostics & Security Audit view."""
    st.subheader("System Settings, GitHub Diagnostics & Security Audit")

    # ------------------------------------------------------------------
    # Section 1: Authenticated User Session & RBAC Profile
    # ------------------------------------------------------------------
    with st.container(border=True):
        st.markdown("#### Active User Session & Role-Based Access Scope")
        u1, u2, u3, u4 = st.columns(4)
        u1.metric("Username", user.username)
        u2.metric("Display Name", user.display_name)
        u3.metric("Role", user.role.value.upper())
        u4.metric("Authorized Repos", len([r for r in config.team_repos if user.can_access_repo(r)]))

    # ------------------------------------------------------------------
    # Section 2: GitHub API Connection & Rate-Limit Diagnostics
    # ------------------------------------------------------------------
    st.markdown("#### GitHub Organization & Repository Connection Diagnostics")
    rl = github_client.rate_limit
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Auth Mechanism", github_client.auth.auth_mode)
    r2.metric("API Rate Limit Remaining", f"{rl.remaining:,} / {rl.limit:,}")
    r3.metric("API Calls Used (Window)", f"{rl.used:,}")
    r4.metric(
        "Rate Limit Reset (UTC)",
        rl.reset_datetime_utc.strftime("%H:%M:%S UTC") if rl.reset_datetime_utc else "N/A",
    )

    diag_rows = []
    for repo_name, ev in evaluations.items():
        snap = ev.snapshot
        diag_rows.append(
            {
                "Organization": snap.org,
                "Repository": repo_name,
                "Accessible": "✅ Connected" if snap.accessible else "❌ Unreachable",
                "HTTP Status": snap.status_code,
                "Visibility": "Private" if snap.private else "Public",
                "Default Branch": snap.default_branch if snap.accessible else "-",
                "Discovered Files": sum(1 for e in snap.tree_entries if e.item_type == "file"),
                "Recent Commits Loaded": len(snap.recent_commits),
                "Snapshot Fetched (UTC)": snap.fetched_at_utc,
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
            "Refresh a Single Team Repository",
            options=[""] + list(evaluations.keys()),
            format_func=lambda x: "Select repository to refresh..." if x == "" else x,
        )
        if single_refresh and st.button(f"Refresh `{single_refresh}`"):
            github_client.clear_cache(single_refresh)
            st.rerun()

    # ------------------------------------------------------------------
    # Section 3: Password Hash Generator Utility (Owners Only)
    # ------------------------------------------------------------------
    if user.can_manage_settings():
        with st.expander("🔐 PBKDF2-HMAC-SHA256 Password Hash Utility (for `.streamlit/secrets.toml`)", expanded=False):
            st.caption(
                "Generate salted PBKDF2-HMAC-SHA256 hashes for organization owners, mentors, or future student accounts. "
                "Plaintext passwords are never stored or logged."
            )
            pw_input = st.text_input("Enter password to hash", type="password", key="pw_gen_input")
            if pw_input and st.button("Generate Hash", key="btn_pw_gen"):
                generated = hash_password_pbkdf2(pw_input)
                st.code(f'password_hash = "{generated}"', language="toml")

    # ------------------------------------------------------------------
    # Section 4: Local SQLite Storage & Audit Trail
    # ------------------------------------------------------------------
    st.markdown("#### Security & Mentor Action Audit Log (SQLite)")
    if not local_store.available:
        st.warning(f"Local SQLite database unavailable: {local_store.last_error}")
    else:
        logs = local_store.get_recent_audit_logs(limit=50)
        if logs:
            st.dataframe(pd.DataFrame(logs), use_container_width=True, hide_index=True)
        else:
            st.caption("No audit events recorded yet.")
