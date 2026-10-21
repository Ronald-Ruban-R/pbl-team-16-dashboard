"""
Utility script to push the dashboard's starter JSON templates (`templates/starter_repo/`)
into `pbl-team-13` through `pbl-team-18` using your configured GitHub token in `.streamlit/secrets.toml`.

Usage (run from inside `pbl_mentor_dashboard/`):
  1. Only add missing JSON files (never overwrites existing files at the same path):
     python scripts/sync_starter_templates.py

  2. Replace/overwrite existing JSON files at those paths with the clean starter templates:
     python scripts/sync_starter_templates.py --overwrite
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path
from urllib.parse import quote

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import _load_streamlit_secrets  # noqa: E402
from src.config import DashboardConfig  # noqa: E402
from src.github_client import GitHubAuthProvider, GitHubCohortClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync starter JSON templates to PBL-Cohort-X-Teams-13-18 repositories."
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing convention JSON files if they already exist at the target path.",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Optional single repository name (e.g. pbl-team-13). Defaults to all 6 configured repos.",
    )
    args = parser.parse_args()

    secrets_map = _load_streamlit_secrets()
    config = DashboardConfig.from_mapping(secrets_map)
    auth = GitHubAuthProvider.from_secrets(secrets_map=secrets_map, config=config)
    client = GitHubCohortClient(config=config, auth_provider=auth)

    if not auth.is_configured:
        print("ERROR: No GitHub token found in .streamlit/secrets.toml.")
        sys.exit(1)

    template_root = PROJECT_ROOT / "templates" / "starter_repo"
    template_files = sorted(p for p in template_root.rglob("*.json") if p.is_file())

    target_repos = [args.repo] if args.repo else config.team_repos

    for repo_name in target_repos:
        print(f"\n=== Processing {config.github_org}/{repo_name} ===")
        for file_path in template_files:
            rel_path = file_path.relative_to(template_root).as_posix()
            raw_text = file_path.read_text(encoding="utf-8")
            # Pre-fill the team_id placeholder with the actual repository name
            customized_text = raw_text.replace("<TEAM_ID_E.G._pbl-team-13>", repo_name)

            existing = client.fetch_file_content(repo_name, rel_path)
            if existing.exists and not args.overwrite:
                print(f"  [SKIP] {rel_path} already exists (use --overwrite to replace).")
                continue

            encoded = base64.b64encode(customized_text.encode("utf-8")).decode("ascii")
            body = {
                "message": f"chore(templates): initialize structured {rel_path} for mentor dashboard",
                "content": encoded,
            }
            if existing.exists and existing.sha:
                body["sha"] = existing.sha

            encoded_rel = "/".join(quote(seg) for seg in rel_path.split("/") if seg)
            endpoint = f"/repos/{quote(config.github_org)}/{quote(repo_name)}/contents/{encoded_rel}"
            status, _, _, err = client._request("PUT", endpoint, json_body=body)
            if status in (200, 201):
                action_str = "UPDATED" if existing.exists else "CREATED"
                print(f"  [{action_str}] {rel_path}")
            else:
                print(f"  [ERROR] Failed to write {rel_path} (HTTP {status}): {err}")


if __name__ == "__main__":
    main()
