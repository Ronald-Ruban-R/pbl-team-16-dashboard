"""
Repository Explorer & Safe File Preview View (`src/views/repo_explorer.py`).

Provides:
- Interactive folder navigation and quick-jump file search across any custom or standard folder.
- Safe inline preview for Markdown, JSON, source code, CSV/TSV tables, images, and PDFs.
- Direct links to view or download files on GitHub.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.config import (
    PREVIEWABLE_IMAGE_EXTENSIONS,
    PREVIEWABLE_PDF_EXTENSIONS,
    PREVIEWABLE_TEXT_EXTENSIONS,
)
from src.github_client import GitHubCohortClient, RepoFileEntry
from src.security import AccessControlManager, AuthenticatedUser, sanitize_markdown_for_display


def render_repo_explorer_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    github_client: GitHubCohortClient,
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
) -> None:
    """Render the interactive Repository Explorer and File Viewer."""
    st.markdown("## Repository Explorer & File Preview")
    st.caption(
        "Browse repository folders, inspect source code and documentation inline, and verify submitted artifacts."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized team repositories available.")
        return

    top_c1, top_c2 = st.columns([1.4, 2])
    with top_c1:
        selected_repo = (
            authorized_repos[0]
            if len(authorized_repos) == 1
            else st.selectbox(
                "Select Repository",
                options=authorized_repos,
                format_func=lambda r: f"{r} — {evaluations[r].display_team_name}",
                key="explorer_repo_select",
            )
        )
    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]

    if not ev.snapshot.accessible:
        st.error(f"Repository `{selected_repo}` is unavailable: {ev.snapshot.error_message}")
        return

    all_files: List[RepoFileEntry] = [
        e for e in ev.snapshot.tree_entries if e.item_type == "file"
    ]
    all_dirs: List[str] = sorted(
        {""} | {e.path for e in ev.snapshot.tree_entries if e.item_type == "dir"}
    )

    with top_c2:
        search_query = st.text_input(
            "Filter files by name or path",
            value="",
            placeholder="e.g., research/, metadata.json, .py, .md",
            key=f"explorer_search_{selected_repo}",
        ).strip().lower()

    nav_col, preview_col = st.columns([1.15, 1.85])

    with nav_col:
        st.markdown("#### Directory & File Browser")
        selected_dir = st.selectbox(
            "Folder",
            options=all_dirs,
            format_func=lambda d: "/ (Repository Root)" if d == "" else f"/{d}",
            key=f"explorer_dir_{selected_repo}",
        )

        if search_query:
            matching_files = [f for f in all_files if search_query in f.path.lower()]
        else:
            if selected_dir == "":
                matching_files = [f for f in all_files if "/" not in f.path]
            else:
                prefix = selected_dir.rstrip("/") + "/"
                matching_files = [
                    f
                    for f in all_files
                    if f.path.startswith(prefix) and "/" not in f.path[len(prefix) :]
                ]
            if not matching_files:
                matching_files = [
                    f for f in all_files if selected_dir == "" or f.path.startswith(selected_dir.rstrip("/") + "/")
                ]

        if not matching_files:
            st.info("No matching files in this location.")
            selected_file_path = None
        else:
            file_paths = [f.path for f in matching_files]
            selected_file_path = st.selectbox(
                f"Select File to Preview ({len(file_paths)} available)",
                options=file_paths,
                key=f"explorer_file_{selected_repo}",
            )
            dir_rows = [
                {
                    "File": f.name,
                    "Path": f.path,
                    "Size (KB)": round(f.size / 1024.0, 1),
                }
                for f in matching_files[:50]
            ]
            st.dataframe(pd.DataFrame(dir_rows), use_container_width=True, hide_index=True)

    with preview_col:
        st.markdown("#### File Content Preview")
        if not selected_file_path:
            st.info("Select a file on the left to preview its contents.")
            return

        file_res = github_client.fetch_file_content(
            repo_name=selected_repo,
            file_path=selected_file_path,
            ref=ev.snapshot.default_branch,
        )

        h_col1, h_col2 = st.columns([2.2, 1])
        with h_col1:
            st.markdown(f"**`{selected_file_path}`** ({file_res.size:,} bytes)")
        with h_col2:
            if file_res.html_url:
                st.markdown(
                    f"<div style='text-align:right;'><a href='{file_res.html_url}' target='_blank'>"
                    f"Open on GitHub ↗</a></div>",
                    unsafe_allow_html=True,
                )

        if not file_res.exists:
            st.warning(file_res.error_message or "File could not be loaded.")
            return

        if file_res.too_large_for_preview:
            st.info(file_res.error_message)
            return

        ext = Path(selected_file_path).suffix.lower()

        if ext in PREVIEWABLE_IMAGE_EXTENSIONS and file_res.raw_bytes:
            st.image(file_res.raw_bytes, caption=selected_file_path, use_container_width=True)
        elif ext in PREVIEWABLE_PDF_EXTENSIONS and file_res.raw_bytes:
            st.download_button(
                label=f"Download {Path(selected_file_path).name}",
                data=file_res.raw_bytes,
                file_name=Path(selected_file_path).name,
                mime="application/pdf",
            )
            st.caption("PDF file ready for download or direct viewing on GitHub.")
        elif ext in (".csv", ".tsv") and file_res.text_content is not None:
            sep = "\t" if ext == ".tsv" else ","
            try:
                df_csv = pd.read_csv(io.StringIO(file_res.text_content), sep=sep)
                st.dataframe(df_csv.head(200), use_container_width=True, hide_index=True)
            except Exception:
                st.code(file_res.text_content[:15000], language="text")
        elif ext in (".md", ".markdown") and file_res.text_content is not None:
            view_mode = st.radio(
                "Markdown View",
                options=["Rendered Markdown", "Raw Source"],
                horizontal=True,
                label_visibility="collapsed",
                key=f"md_mode_{selected_repo}_{selected_file_path}",
            )
            if view_mode == "Rendered Markdown":
                with st.container(border=True):
                    st.markdown(sanitize_markdown_for_display(file_res.text_content))
            else:
                st.code(file_res.text_content, language="markdown")
        elif ext in PREVIEWABLE_TEXT_EXTENSIONS and file_res.text_content is not None:
            lang_map = {
                ".json": "json",
                ".py": "python",
                ".js": "javascript",
                ".ts": "typescript",
                ".html": "html",
                ".css": "css",
                ".sql": "sql",
                ".sh": "bash",
                ".yaml": "yaml",
                ".yml": "yaml",
                ".toml": "toml",
            }
            st.code(file_res.text_content, language=lang_map.get(ext, "text"))
        elif file_res.text_content is not None:
            st.code(file_res.text_content[:15000], language="text")
        else:
            st.info("Binary artifact. Use the 'Open on GitHub' link above to download or inspect.")
