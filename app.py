"""
Universal PBL Dashboard entry point (`app.py`).

Dynamically adapts to:
1. Single-Team Dashboard (e.g., `repositories = ["pbl-team-13"]` or `["pbl-team-16"]`)
2. Cohort-Wide Mentor Dashboard (e.g., `repositories = ["pbl-team-13", ... "pbl-team-18"]`)

Derives all titles, headers, and navigation options dynamically from the configured
repositories in `.streamlit/secrets.toml` with zero code modifications needed when deploying
multiple instances from the same repository.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import streamlit as st

from src.analytics import TeamEvaluationSummary, evaluate_team_repository
from src.config import DashboardConfig, to_plain_dict
from src.github_client import GitHubAuthProvider, GitHubCohortClient
from src.security import AccessControlManager, AuthenticatedUser
from src.storage import MentorLocalStore
from src.ui_theme import apply_clean_theme
from src.views.overview import render_overview_page
from src.views.repo_explorer import render_repo_explorer_page
from src.views.research_competitions import render_research_competitions_page
from src.views.reviews import render_reviews_page
from src.views.settings import render_settings_page
from src.views.tasks_progress import render_tasks_progress_page
from src.views.team_workspace import render_team_workspace_page
from src.views.timeline import render_timeline_page


def _get_navigation_pages(is_single_team: bool) -> List[str]:
    """Return appropriate navigation options based on whether this is a single team or cohort app."""
    if is_single_team:
        return [
            "Team Workspace & Profile",
            "Tasks, Progress & Live GitHub Sync",
            "Repository Explorer",
            "Reviews & Mentor Feedback",
            "Timeline & Milestones",
            "Research & Competitions",
            "Overview & Alerts",
            "Settings & Diagnostics",
        ]
    return [
        "Overview & Cohort Comparison",
        "Individual Team Workspace",
        "Repository Explorer",
        "Progress & Tasks",
        "Reviews & Feedback",
        "Timeline & Milestones",
        "Research & Competitions",
        "Settings & Diagnostics",
    ]


def _parse_toml_file(path: Path) -> Dict[str, Any]:
    """Parse a local TOML file using `tomllib` (Python 3.11+) or `toml` fallback."""
    try:
        import tomllib
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        try:
            import toml  # type: ignore
            return dict(toml.load(str(path)))
        except Exception:
            return {}
    except Exception:
        return {}


def _load_streamlit_secrets() -> Dict[str, Any]:
    """Load secrets reliably from `.streamlit/secrets.toml` or `st.secrets`."""
    app_dir = Path(__file__).resolve().parent
    candidate_paths: List[Path] = [
        app_dir / ".streamlit" / "secrets.toml",
        app_dir / ".streamlit" / "secrets.toml.txt",
        app_dir / ".streamlit" / "secrets.toml.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
    ]
    for p in candidate_paths:
        if p.is_file():
            loaded = _parse_toml_file(p)
            if loaded:
                return to_plain_dict(loaded)

    try:
        plain = to_plain_dict(st.secrets)
        if isinstance(plain, dict) and plain:
            return plain
    except Exception:
        pass

    return {}


def _get_or_init_services(secrets_map: Dict[str, Any]):
    needs_reinit = False
    if "access_manager" in st.session_state:
        cached_acm: AccessControlManager = st.session_state["access_manager"]
        if not cached_acm.is_auth_configured() and bool(secrets_map):
            needs_reinit = True

    if "dashboard_config" not in st.session_state or needs_reinit:
        st.session_state["dashboard_config"] = DashboardConfig.from_mapping(secrets_map)
    config: DashboardConfig = st.session_state["dashboard_config"]

    if "access_manager" not in st.session_state or needs_reinit:
        st.session_state["access_manager"] = AccessControlManager(
            secrets_map=secrets_map,
            configured_repos=config.team_repos,
        )
    access_manager: AccessControlManager = st.session_state["access_manager"]

    if "github_client" not in st.session_state or needs_reinit:
        auth_provider = GitHubAuthProvider.from_secrets(secrets_map=secrets_map, config=config)
        st.session_state["github_client"] = GitHubCohortClient(config=config, auth_provider=auth_provider)
    github_client: GitHubCohortClient = st.session_state["github_client"]

    if "local_store" not in st.session_state:
        st.session_state["local_store"] = MentorLocalStore(db_path=config.sqlite_db_path)
    local_store: MentorLocalStore = st.session_state["local_store"]

    return config, access_manager, github_client, local_store


def _render_login_screen(
    access_manager: AccessControlManager,
    local_store: MentorLocalStore,
    config: DashboardConfig,
    team_label: str,
) -> None:
    st.markdown(f"## PBL {team_label} Dashboard — Sign In")
    st.caption(
        f"Organization: `{config.github_org}` | Configured Repositories: `{', '.join(config.team_repos)}`"
    )

    if not access_manager.is_auth_configured():
        app_dir = Path(__file__).resolve().parent
        st.error(
            "**Dashboard Authentication Not Configured:** No valid user credentials found in "
            f"`{app_dir / '.streamlit' / 'secrets.toml'}` (or Streamlit Cloud Secrets)."
        )
        if st.button("Reload Secrets"):
            st.session_state.clear()
            st.rerun()
        return

    col_left, col_center, col_right = st.columns([1, 1.4, 1])
    with col_center:
        with st.form("universal_login_form", clear_on_submit=False):
            st.markdown(f"#### {team_label} Sign In")
            username = st.text_input("Username", placeholder="RONALDRUBAN")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In", use_container_width=True)

            if submitted:
                user = access_manager.authenticate(username, password)
                if user is not None:
                    st.session_state["authenticated_user"] = user
                    local_store.log_audit_event(
                        username=user.username,
                        role=user.role.value,
                        action="login_success",
                        details=f"Authenticated as {user.role.value}",
                    )
                    st.rerun()
                else:
                    local_store.log_audit_event(
                        username=username or "unknown",
                        role="unauthenticated",
                        action="login_failure",
                        details="Invalid username or password attempt.",
                    )
                    st.error("Invalid username or password.")


def _load_authorized_team_evaluations(
    user: AuthenticatedUser,
    config: DashboardConfig,
    github_client: GitHubCohortClient,
    local_store: MentorLocalStore,
) -> Dict[str, TeamEvaluationSummary]:
    evaluations: Dict[str, TeamEvaluationSummary] = {}
    authorized_repos = [r for r in config.team_repos if user.can_access_repo(r)]

    for repo_name in authorized_repos:
        snap = github_client.fetch_repository_snapshot(repo_name)
        custom_weights = local_store.get_setting(f"milestone_weights::{repo_name}", default=None)
        evaluations[repo_name] = evaluate_team_repository(
            snapshot=snap,
            config=config,
            custom_milestone_weights=custom_weights,
        )
    return evaluations


def main() -> None:
    secrets_map = _load_streamlit_secrets()
    config, access_manager, github_client, local_store = _get_or_init_services(secrets_map)

    is_single_team = len(config.team_repos) == 1
    team_label = config.team_repos[0].upper() if is_single_team else "Cohort-X"
    nav_pages = _get_navigation_pages(is_single_team)
    st.session_state["_nav_options"] = nav_pages

    st.set_page_config(
        page_title=f"PBL {team_label} Dashboard",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_clean_theme()

    user: AuthenticatedUser | None = st.session_state.get("authenticated_user")
    if user is None:
        _render_login_screen(access_manager, local_store, config, team_label)
        return

    with st.sidebar:
        st.markdown(f"### PBL {team_label}")
        st.caption(f"Repo: `{config.github_org}/{', '.join(config.team_repos)}`")
        access_badge = "Write Access (Owner)" if user.role.value == "owner" else "Read-Only"
        st.markdown(f"**{user.display_name}** (`{user.role.value}` — {access_badge})")

        if "active_page" not in st.session_state or st.session_state["active_page"] not in nav_pages:
            st.session_state["active_page"] = nav_pages[0]

        selected_page = st.radio(
            "Navigation",
            options=nav_pages,
            index=nav_pages.index(st.session_state["active_page"]),
            label_visibility="collapsed",
        )
        if selected_page != st.session_state["active_page"]:
            st.session_state["active_page"] = selected_page
            st.rerun()

        st.divider()
        if not github_client.auth.is_configured:
            st.warning("Configure GitHub token in `.streamlit/secrets.toml`.")
        else:
            rl = github_client.rate_limit
            st.caption(
                f"GitHub Auth: `{github_client.auth.auth_mode}`\n\n"
                f"API Quota: **{rl.remaining:,}/{rl.limit:,}**"
            )

        c_ref, c_out = st.columns(2)
        if c_ref.button("Sync Now", use_container_width=True):
            github_client.clear_cache()
            st.rerun()
        if c_out.button("Sign Out", use_container_width=True):
            local_store.log_audit_event(
                username=user.username,
                role=user.role.value,
                action="logout",
                details="User signed out.",
            )
            st.session_state.pop("authenticated_user", None)
            st.rerun()

    with st.spinner(f"Synchronizing `{', '.join(config.team_repos)}` from GitHub..."):
        evaluations = _load_authorized_team_evaluations(user, config, github_client, local_store)

    active_page = st.session_state["active_page"]
    if active_page in ("Team Workspace & Profile", "Team 16 Workspace & Profile", "Individual Team Workspace"):
        render_team_workspace_page(
            evaluations, user, access_manager, github_client=github_client, local_store=local_store
        )
    elif active_page in ("Tasks, Progress & Live GitHub Sync", "Progress & Tasks"):
        render_tasks_progress_page(
            evaluations, user, access_manager, local_store, github_client=github_client, config=config
        )
    elif active_page == "Repository Explorer":
        render_repo_explorer_page(evaluations, github_client, user, access_manager)
    elif active_page in ("Reviews & Mentor Feedback", "Reviews & Feedback"):
        render_reviews_page(evaluations, config, github_client, user, access_manager, local_store)
    elif active_page in ("Timeline & Milestones",):
        render_timeline_page(
            evaluations, user, access_manager, github_client=github_client, local_store=local_store
        )
    elif active_page in ("Research & Competitions",):
        render_research_competitions_page(evaluations, user, access_manager)
    elif active_page in ("Overview & Alerts", "Overview & Cohort Comparison"):
        render_overview_page(evaluations, config)
    elif active_page == "Settings & Diagnostics":
        render_settings_page(evaluations, config, github_client, user, local_store)


if __name__ == "__main__":
    main()
