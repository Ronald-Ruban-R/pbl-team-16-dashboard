"""
Dynamic GitHub Repository Explorer View.

Features:
- Browses the actual directory and file structure of any authorized private repository.
- Supports nested directories and custom team folders without assuming a fixed folder tree.
- Interactive breadcrumb bar for rapid parent/child directory navigation.
- Safe in-app preview of Markdown (sanitized), source code, JSON, CSV/TSV tables, images, and PDFs.
- Safe file download and direct GitHub links (`blob`, `tree`, and commit history).
- Graceful handling of files > 1 MB, binary files, missing files, and API errors.
"""

from __future__ import annotations

import base64
import io
from typing import Dict, List

import pandas as pd
import streamlit as st

from src.analytics import TeamEvaluationSummary
from src.config import (
    MAX_PREVIEW_FILE_BYTES,
    PREVIEWABLE_IMAGE_EXTENSIONS,
    PREVIEWABLE_PDF_EXTENSIONS,
    PREVIEWABLE_TEXT_EXTENSIONS,
)
from src.github_client import GitHubCohortClient, RepoFileEntry
from src.security import (
    AccessControlManager,
    AuthenticatedUser,
    sanitize_markdown_for_display,
)


def _list_directory_from_tree(
    tree_entries: List[RepoFileEntry], current_dir: str
) -> List[RepoFileEntry]:
    """
    Derive the immediate children of `current_dir` from the repository's recursive tree,
    supporting arbitrary custom folder hierarchies without extra API round-trips.
    """
    clean_dir = current_dir.strip("/")
    prefix = f"{clean_dir}/" if clean_dir else ""
    children_map: Dict[str, RepoFileEntry] = {}

    for entry in tree_entries:
        if clean_dir and not entry.path.startswith(prefix):
            continue
        rel = entry.path[len(prefix):] if clean_dir else entry.path
        if not rel:
            continue
        if "/" not in rel:
            children_map[entry.path] = entry
        else:
            # Synthesize directory entry if only leaf blobs were present
            top_seg = rel.split("/", 1)[0]
            dir_path = f"{prefix}{top_seg}"
            if dir_path not in children_map:
                children_map[dir_path] = RepoFileEntry(
                    name=top_seg,
                    path=dir_path,
                    item_type="dir",
                    size=0,
                    html_url="",
                )

    result = list(children_map.values())
    result.sort(key=lambda e: (0 if e.item_type == "dir" else 1, e.name.lower()))
    return result


def render_repo_explorer_page(
    evaluations: Dict[str, TeamEvaluationSummary],
    github_client: GitHubCohortClient,
    user: AuthenticatedUser,
    access_manager: AccessControlManager,
) -> None:
    """Render the interactive GitHub Repository Explorer."""
    st.subheader("Repository Explorer")
    st.caption(
        "Browse live repository directories, custom folders, and files directly from GitHub. "
        "GitHub remains the single source of truth."
    )

    authorized_repos = [r for r in evaluations.keys() if user.can_access_repo(r)]
    if not authorized_repos:
        st.error("No authorized repositories available.")
        return

    default_repo = st.session_state.get("selected_repo")
    if default_repo not in authorized_repos:
        default_repo = authorized_repos[0]

    col_repo, col_search, col_gh = st.columns([2, 2, 1])
    with col_repo:
        selected_repo = st.selectbox(
            "Repository",
            options=authorized_repos,
            index=authorized_repos.index(default_repo),
            key="explorer_repo_select",
        )
        if selected_repo != st.session_state.get("selected_repo"):
            st.session_state["selected_repo"] = selected_repo
            st.session_state["explorer_path"] = ""
            st.session_state["explorer_selected_file"] = None

    access_manager.authorize_repo_access(user, selected_repo)
    ev = evaluations[selected_repo]
    snap = ev.snapshot

    with col_gh:
        st.write("")
        st.link_button("Open Repo on GitHub ↗", snap.html_url, use_container_width=True)

    if not snap.accessible:
        st.error(f"Cannot browse `{selected_repo}`: {snap.error_message}")
        return

    with col_search:
        global_filter = st.text_input(
            "Jump to any file in repository",
            value="",
            placeholder="Type filename or path (e.g. progress.json, research/)...",
        ).strip().lower()

    current_path: str = st.session_state.get("explorer_path", "").strip("/")

    # ------------------------------------------------------------------
    # Breadcrumb Navigation Bar
    # ------------------------------------------------------------------
    segments = [seg for seg in current_path.split("/") if seg]
    bc_cols = st.columns(min(8, len(segments) + 2))
    if bc_cols[0].button(f"🏠 {selected_repo}", key="bc_root", use_container_width=True):
        st.session_state["explorer_path"] = ""
        st.session_state["explorer_selected_file"] = None
        st.rerun()

    accum = []
    for idx, seg in enumerate(segments):
        accum.append(seg)
        target_path = "/".join(accum)
        col_idx = min(idx + 1, len(bc_cols) - 1)
        if bc_cols[col_idx].button(f"📁 {seg}", key=f"bc_{target_path}", use_container_width=True):
            st.session_state["explorer_path"] = target_path
            st.session_state["explorer_selected_file"] = None
            st.rerun()

    # Retrieve directory entries (from recursive tree or fallback to live Contents API)
    if snap.tree_entries and not snap.tree_truncated:
        dir_entries = _list_directory_from_tree(snap.tree_entries, current_path)
        dir_error = None
    else:
        dir_entries, dir_error = github_client.fetch_directory_contents(
            selected_repo, folder_path=current_path, ref=snap.default_branch
        )

    if dir_error:
        st.error(f"Error loading directory `{current_path or '/'}`: {dir_error}")
        return

    left_pane, right_pane = st.columns([1.15, 1.85])

    # ------------------------------------------------------------------
    # Left Pane: Folder & File Navigator
    # ------------------------------------------------------------------
    with left_pane:
        st.markdown(f"#### Directory: `/{current_path}`")
        if current_path:
            parent_path = "/".join(segments[:-1])
            if st.button("⬅️ Up to parent folder", key="btn_up_dir"):
                st.session_state["explorer_path"] = parent_path
                st.session_state["explorer_selected_file"] = None
                st.rerun()

        if global_filter:
            matched_files = [
                e for e in snap.tree_entries
                if e.item_type == "file" and global_filter in e.path.lower()
            ]
            st.caption(f"Global search matches ({len(matched_files)}):")
            for entry in matched_files[:40]:
                if st.button(f"📄 {entry.path} ({entry.size:,} B)", key=f"gsearch_{entry.path}", use_container_width=True):
                    st.session_state["explorer_selected_file"] = entry.path
                    st.rerun()
        else:
            dirs = [e for e in dir_entries if e.item_type == "dir"]
            files = [e for e in dir_entries if e.item_type == "file"]

            if not dirs and not files:
                st.info("This directory is empty.")

            for d in dirs:
                if st.button(f"📁 {d.name}/", key=f"dir_{d.path}", use_container_width=True):
                    st.session_state["explorer_path"] = d.path
                    st.session_state["explorer_selected_file"] = None
                    st.rerun()

            for f in files:
                if st.button(
                    f"📄 {f.name} ({f.size:,} B)",
                    key=f"file_{f.path}",
                    use_container_width=True,
                ):
                    st.session_state["explorer_selected_file"] = f.path
                    st.rerun()

        if dir_entries:
            with st.expander("View Directory Metadata Table", expanded=False):
                meta_df = pd.DataFrame(
                    [
                        {
                            "Type": "Folder" if e.item_type == "dir" else (e.extension or "File"),
                            "Name": e.name,
                            "Path": e.path,
                            "Size (B)": e.size if e.item_type == "file" else None,
                            "SHA": e.sha[:8] if e.sha else "",
                        }
                        for e in dir_entries
                    ]
                )
                st.dataframe(meta_df, use_container_width=True, hide_index=True)

    # ------------------------------------------------------------------
    # Right Pane: Safe File Content Previewer
    # ------------------------------------------------------------------
    with right_pane:
        selected_file_path = st.session_state.get("explorer_selected_file")
        if not selected_file_path:
            st.info("Select any file on the left to inspect its metadata, preview its contents, or open it on GitHub.")
            return

        st.markdown(f"#### File Preview: `{selected_file_path}`")
        file_res = github_client.fetch_file_content(
            selected_repo,
            selected_file_path,
            ref=snap.default_branch,
            max_bytes=MAX_PREVIEW_FILE_BYTES,
        )

        m1, m2, m3, m4 = st.columns([1.2, 1.2, 1.2, 1.4])
        m1.caption(f"**Size:** {file_res.size:,} bytes")
        m2.caption(f"**SHA:** `{file_res.sha[:10] if file_res.sha else 'N/A'}`")
        ext = ("." + selected_file_path.rsplit(".", 1)[-1].lower()) if "." in selected_file_path else ""
        m3.caption(f"**Format:** `{ext or 'plain'}`")
        m4.link_button("Open File on GitHub ↗", file_res.html_url, use_container_width=True)

        if not file_res.exists:
            st.error(file_res.error_message or "File could not be retrieved.")
            return

        if file_res.too_large_for_preview:
            st.warning(
                file_res.error_message
                or "This file exceeds the 1 MB in-app preview threshold. Use the GitHub link above to view or download it."
            )
            return

        if file_res.raw_bytes is not None:
            st.download_button(
                label=f"⬇️ Download `{selected_file_path.rsplit('/', 1)[-1]}` ({file_res.size:,} bytes)",
                data=file_res.raw_bytes,
                file_name=selected_file_path.rsplit("/", 1)[-1],
                mime="application/octet-stream",
                key=f"dl_{selected_repo}_{selected_file_path}",
            )

        # Render according to file extension and content safety rules
        if ext in PREVIEWABLE_IMAGE_EXTENSIONS and file_res.raw_bytes:
            st.image(file_res.raw_bytes, caption=selected_file_path, use_container_width=True)
            return

        if ext in PREVIEWABLE_PDF_EXTENSIONS and file_res.raw_bytes:
            b64_pdf = base64.b64encode(file_res.raw_bytes).decode("ascii")
            pdf_html = (
                f'<iframe src="data:application/pdf;base64,{b64_pdf}" '
                f'width="100%" height="620" type="application/pdf" style="border: 1px solid #ccc; border-radius: 6px;"></iframe>'
            )
            st.markdown(pdf_html, unsafe_allow_html=True)
            return

        if file_res.is_binary or file_res.text_content is None:
            st.info(
                "Binary or non-text file format cannot be rendered as text inline. "
                "Use the Download button or Open on GitHub link above."
            )
            return

        if ext in (".md", ".markdown"):
            view_mode = st.radio(
                "Markdown View Mode",
                options=["Rendered Markdown (Sanitized)", "Raw Source"],
                horizontal=True,
                key=f"md_mode_{selected_file_path}",
            )
            if view_mode == "Rendered Markdown (Sanitized)":
                st.markdown(sanitize_markdown_for_display(file_res.text_content))
            else:
                st.code(file_res.text_content, language="markdown")
        elif ext in (".csv", ".tsv"):
            sep = "\t" if ext == ".tsv" else ","
            try:
                df_csv = pd.read_csv(io.StringIO(file_res.text_content), sep=sep)
                st.dataframe(df_csv.head(200), use_container_width=True)
                if len(df_csv) > 200:
                    st.caption(f"Showing first 200 of {len(df_csv):,} rows.")
            except Exception:
                st.code(file_res.text_content, language="text")
        elif ext == ".json":
            st.code(file_res.text_content, language="json")
        elif ext in PREVIEWABLE_TEXT_EXTENSIONS:
            lang_map = {
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
        else:
            st.code(file_res.text_content[:20000], language="text")
