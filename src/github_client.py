"""
Secure GitHub REST API and GitHub App client for the PBL Cohort-X Mentor Dashboard.

Features:
- Supports both GitHub App Installation Authentication (RS256 JWT -> short-lived installation token)
  and Fine-Grained Personal Access Token (PAT) authentication.
- Enforces timeouts, exponential backoff retry logic on transient errors (502/503/504),
  and transparent pagination.
- Tracks GitHub API rate-limit headers (`X-RateLimit-Remaining`, `X-RateLimit-Reset`).
- Isolates per-repository failures so one inaccessible or misconfigured repository never
  breaks the remaining five repositories.
- Redacts tokens from all exception messages and logs.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from src.config import (
    CONVENTION_FILES,
    DashboardConfig,
    MAX_PREVIEW_FILE_BYTES,
)
from src.security import redact_secrets


@dataclass
class RateLimitStatus:
    """Snapshot of the GitHub API rate limit."""

    limit: int = 5000
    remaining: int = 5000
    reset_epoch: int = 0
    used: int = 0
    resource: str = "core"

    @property
    def reset_datetime_utc(self) -> Optional[datetime]:
        if self.reset_epoch <= 0:
            return None
        return datetime.fromtimestamp(self.reset_epoch, tz=timezone.utc)

    @property
    def is_exhausted(self) -> bool:
        return self.remaining <= 0 and self.reset_epoch > int(time.time())

    @property
    def is_low(self) -> bool:
        return 0 < self.remaining < 100


@dataclass
class RepoFileEntry:
    """Metadata for a single file or directory in a GitHub repository."""

    name: str
    path: str
    item_type: str  # "file" or "dir"
    size: int = 0
    sha: str = ""
    html_url: str = ""
    download_url: Optional[str] = None

    @property
    def extension(self) -> str:
        if "." not in self.name or self.item_type == "dir":
            return ""
        return "." + self.name.rsplit(".", 1)[-1].lower()


@dataclass
class CommitRecord:
    """Summary of a single GitHub repository commit."""

    sha: str
    short_sha: str
    message: str
    author_name: str
    author_login: str
    committed_date: str
    html_url: str


@dataclass
class FileContentResult:
    """Result of fetching a single file's content from GitHub."""

    repo_name: str
    path: str
    exists: bool
    size: int = 0
    sha: str = ""
    encoding: str = "utf-8"
    text_content: Optional[str] = None
    raw_bytes: Optional[bytes] = None
    html_url: str = ""
    last_modified: Optional[str] = None
    too_large_for_preview: bool = False
    is_binary: bool = False
    error_message: Optional[str] = None


@dataclass
class RepositorySnapshot:
    """
    Isolated snapshot of a single team repository's metadata, convention files,
    full directory tree, and recent commits.
    """

    org: str
    repo_name: str
    accessible: bool
    status_code: int = 200
    error_message: Optional[str] = None
    description: Optional[str] = None
    private: bool = True
    default_branch: str = "main"
    html_url: str = ""
    pushed_at: Optional[str] = None
    updated_at: Optional[str] = None
    size_kb: int = 0
    open_issues_count: int = 0
    tree_entries: List[RepoFileEntry] = field(default_factory=list)
    tree_truncated: bool = False
    recent_commits: List[CommitRecord] = field(default_factory=list)
    convention_raw_files: Dict[str, FileContentResult] = field(default_factory=dict)
    fetched_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


class GitHubAuthProvider:
    """
    Provides least-privilege Authorization headers for GitHub API requests.
    Supports:
    1. GitHub App Installation authentication (`app_id`, `installation_id`, `private_key_pem`)
       using RS256 JWT generation via `cryptography` and automatic installation token caching.
    2. Fine-Grained Personal Access Token (`token` / `PBL_GITHUB_TOKEN`).
    """

    def __init__(
        self,
        token: Optional[str] = None,
        app_id: Optional[str] = None,
        installation_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        api_base_url: str = "https://api.github.com",
        timeout_seconds: int = 15,
    ):
        self._pat_token = (token or "").strip() or None
        self._app_id = (str(app_id).strip() if app_id else None)
        self._installation_id = (str(installation_id).strip() if installation_id else None)
        self._private_key_pem = (private_key_pem or "").strip() or None
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout = timeout_seconds

        self._cached_installation_token: Optional[str] = None
        self._installation_token_expiry_epoch: int = 0

    @classmethod
    def from_secrets(cls, secrets_map: Optional[Dict] = None, config: Optional[DashboardConfig] = None) -> "GitHubAuthProvider":
        """Construct a GitHubAuthProvider from Streamlit secrets or environment variables."""
        import os

        from src.config import to_plain_dict
        plain = to_plain_dict(secrets_map) if secrets_map is not None else {}
        secrets_map = plain if isinstance(plain, dict) else {}
        gh_sec = secrets_map.get("github", {}) if isinstance(secrets_map.get("github"), dict) else {}
        cfg = config or DashboardConfig.from_mapping(secrets_map)

        token = gh_sec.get("token") or os.environ.get("PBL_GITHUB_TOKEN")
        app_id = gh_sec.get("app_id") or os.environ.get("PBL_GITHUB_APP_ID")
        installation_id = gh_sec.get("installation_id") or os.environ.get("PBL_GITHUB_INSTALLATION_ID")
        private_key_pem = gh_sec.get("private_key_pem") or os.environ.get("PBL_GITHUB_PRIVATE_KEY_PEM")

        return cls(
            token=token,
            app_id=app_id,
            installation_id=installation_id,
            private_key_pem=private_key_pem,
            api_base_url=cfg.github_api_base_url,
            timeout_seconds=cfg.api_timeout_seconds,
        )

    @property
    def auth_mode(self) -> str:
        if self._app_id and self._installation_id and self._private_key_pem:
            return "github_app"
        if self._pat_token:
            return "fine_grained_pat"
        return "unconfigured"

    @property
    def is_configured(self) -> bool:
        return self.auth_mode != "unconfigured"

    def _generate_app_jwt(self) -> str:
        """Create a short-lived RS256 JWT (9 minutes) signed with the GitHub App's RSA private key."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iat": now - 60,
            "exp": now + (9 * 60),
            "iss": self._app_id,
        }

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

        signing_input = (
            f"{_b64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}."
            f"{_b64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
        )

        pem_bytes = self._private_key_pem.replace("\\n", "\n").encode("utf-8")
        private_key = serialization.load_pem_private_key(pem_bytes, password=None)
        signature = private_key.sign(
            signing_input.encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return f"{signing_input}.{_b64url(signature)}"

    def get_access_token(self, session: Optional[requests.Session] = None) -> str:
        """Return a valid bearer token (either cached GitHub App installation token or fine-grained PAT)."""
        if self.auth_mode == "fine_grained_pat":
            return self._pat_token  # type: ignore[return-value]

        if self.auth_mode == "github_app":
            now = int(time.time())
            if self._cached_installation_token and now < (self._installation_token_expiry_epoch - 120):
                return self._cached_installation_token

            jwt_token = self._generate_app_jwt()
            http = session or requests.Session()
            url = f"{self._api_base_url}/app/installations/{self._installation_id}/access_tokens"
            resp = http.post(
                url,
                headers={
                    "Authorization": f"Bearer {jwt_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=self._timeout,
            )
            if resp.status_code != 201:
                raise RuntimeError(
                    f"GitHub App installation token exchange failed (HTTP {resp.status_code}): "
                    f"{redact_secrets(resp.text[:300])}"
                )
            body = resp.json()
            self._cached_installation_token = body["token"]
            self._installation_token_expiry_epoch = now + 3300
            return self._cached_installation_token

        raise RuntimeError(
            "GitHub credentials are not configured. Provide a Fine-Grained PAT or GitHub App credentials "
            "in `.streamlit/secrets.toml` or environment variables."
        )


class GitHubCohortClient:
    """
    Resilient GitHub API client for `PBL-Cohort-X-Teams-13-18`.

    Guarantees:
    - Never throws an unhandled exception when an individual repository is missing,
      private/unauthorized, empty, or contains malformed files.
    - Tracks rate limits and prevents repeated hammering when rate-limited.
    - Supports in-memory TTL caching with manual cache clearing.
    """

    def __init__(
        self,
        config: DashboardConfig,
        auth_provider: GitHubAuthProvider,
        session: Optional[requests.Session] = None,
    ):
        self.config = config
        self.auth = auth_provider
        self.session = session or requests.Session()
        self.rate_limit = RateLimitStatus()
        self._cache: Dict[str, Tuple[float, Any]] = {}

    def clear_cache(self, repo_name: Optional[str] = None) -> None:
        """Clear cached responses globally or for a single repository."""
        if repo_name is None:
            self._cache.clear()
        else:
            prefix = f"{repo_name.lower()}::"
            keys_to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_delete:
                self._cache.pop(k, None)

    def _get_cached(self, key: str) -> Optional[Any]:
        if self.config.cache_ttl_seconds <= 0:
            return None
        entry = self._cache.get(key)
        if not entry:
            return None
        expires_at, val = entry
        if time.time() > expires_at:
            self._cache.pop(key, None)
            return None
        return val

    def _set_cached(self, key: str, value: Any) -> None:
        if self.config.cache_ttl_seconds > 0:
            self._cache[key] = (time.time() + self.config.cache_ttl_seconds, value)

    def _update_rate_limit(self, headers: Dict[str, Any]) -> None:
        try:
            if "X-RateLimit-Limit" in headers:
                self.rate_limit.limit = int(headers["X-RateLimit-Limit"])
            if "X-RateLimit-Remaining" in headers:
                self.rate_limit.remaining = int(headers["X-RateLimit-Remaining"])
            if "X-RateLimit-Reset" in headers:
                self.rate_limit.reset_epoch = int(headers["X-RateLimit-Reset"])
            if "X-RateLimit-Used" in headers:
                self.rate_limit.used = int(headers["X-RateLimit-Used"])
            if "X-RateLimit-Resource" in headers:
                self.rate_limit.resource = str(headers["X-RateLimit-Resource"])
        except (ValueError, TypeError):
            pass

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        accept: str = "application/vnd.github+json",
    ) -> Tuple[int, Any, Dict[str, Any], Optional[str]]:
        """
        Execute an authenticated GitHub API request with retries for transient 5xx errors
        and explicit rate-limit handling.
        Returns `(status_code, parsed_json_or_bytes, headers, error_message)`.
        """
        if not self.auth.is_configured:
            return (
                401,
                None,
                {},
                "GitHub authentication is not configured. Configure `.streamlit/secrets.toml` or environment variables.",
            )

        if self.rate_limit.is_exhausted:
            reset_str = (
                self.rate_limit.reset_datetime_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
                if self.rate_limit.reset_datetime_utc
                else "shortly"
            )
            return (
                429,
                None,
                {},
                f"GitHub API rate limit exhausted (0 remaining). Resets at {reset_str}.",
            )

        try:
            token = self.auth.get_access_token(session=self.session)
        except Exception as exc:
            return 401, None, {}, redact_secrets(str(exc))

        url = (
            endpoint
            if endpoint.startswith("http")
            else f"{self.config.github_api_base_url}/{endpoint.lstrip('/')}"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PBL-Cohort-X-Mentor-Dashboard/1.0",
        }

        last_error = None
        for attempt in range(max(1, self.config.max_retries)):
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=self.config.api_timeout_seconds,
                )
                self._update_rate_limit(dict(resp.headers))

                if resp.status_code in (502, 503, 504) and attempt < self.config.max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue

                if resp.status_code == 403 and "rate limit" in resp.text.lower():
                    return (
                        429,
                        None,
                        dict(resp.headers),
                        "GitHub API rate limit exceeded. Wait for reset or use cached data.",
                    )

                if resp.status_code == 401:
                    return (
                        401,
                        None,
                        dict(resp.headers),
                        "GitHub authentication failed (HTTP 401): Invalid or expired access token.",
                    )

                if resp.status_code == 403:
                    return (
                        403,
                        None,
                        dict(resp.headers),
                        "Insufficient GitHub permissions (HTTP 403): Verify repository read permissions for this token/App.",
                    )

                if resp.status_code == 404:
                    return (
                        404,
                        None,
                        dict(resp.headers),
                        "Resource or private repository not found (HTTP 404).",
                    )

                if 200 <= resp.status_code < 300:
                    if accept == "application/vnd.github.raw+json":
                        return resp.status_code, resp.content, dict(resp.headers), None
                    try:
                        return resp.status_code, resp.json(), dict(resp.headers), None
                    except ValueError:
                        return resp.status_code, resp.text, dict(resp.headers), None

                return (
                    resp.status_code,
                    None,
                    dict(resp.headers),
                    f"GitHub API returned HTTP {resp.status_code}: {redact_secrets(resp.text[:250])}",
                )
            except requests.RequestException as exc:
                last_error = redact_secrets(str(exc))
                if attempt < self.config.max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue

        return 503, None, {}, f"Network error communicating with GitHub API: {last_error}"

    def verify_organization_connection(self) -> Dict[str, Any]:
        """Verify authenticated access to the organization and return diagnostic summary."""
        status, data, _, err = self._request("GET", f"/orgs/{quote(self.config.github_org)}")
        if status == 200 and isinstance(data, dict):
            return {
                "connected": True,
                "status_code": 200,
                "org_login": data.get("login", self.config.github_org),
                "org_name": data.get("name") or data.get("login", self.config.github_org),
                "html_url": data.get("html_url", f"https://github.com/{self.config.github_org}"),
                "error": None,
                "rate_limit": self.rate_limit,
            }
        return {
            "connected": False,
            "status_code": status,
            "org_login": self.config.github_org,
            "org_name": self.config.github_org,
            "html_url": f"https://github.com/{self.config.github_org}",
            "error": err,
            "rate_limit": self.rate_limit,
        }

    def fetch_directory_contents(self, repo_name: str, folder_path: str = "", ref: Optional[str] = None) -> Tuple[List[RepoFileEntry], Optional[str]]:
        """
        Retrieve directory contents for `folder_path` inside `repo_name`.
        Supports dynamic nested folders and custom folder names.
        """
        clean_path = folder_path.strip("/")
        cache_key = f"{repo_name.lower()}::dir::{clean_path}::{ref or 'default'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached, None

        encoded_path = "/".join(quote(seg) for seg in clean_path.split("/") if seg)
        endpoint = f"/repos/{quote(self.config.github_org)}/{quote(repo_name)}/contents/{encoded_path}".rstrip("/")
        params = {"ref": ref} if ref else None
        status, data, _, err = self._request("GET", endpoint, params=params)
        if status != 200:
            return [], err

        raw_items = data if isinstance(data, list) else [data]
        entries: List[RepoFileEntry] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            entries.append(
                RepoFileEntry(
                    name=str(item.get("name", "")),
                    path=str(item.get("path", "")),
                    item_type="dir" if item.get("type") == "dir" else "file",
                    size=int(item.get("size") or 0),
                    sha=str(item.get("sha") or ""),
                    html_url=str(item.get("html_url") or ""),
                    download_url=item.get("download_url"),
                )
            )

        # Sort directories first, then alphabetically by name
        entries.sort(key=lambda e: (0 if e.item_type == "dir" else 1, e.name.lower()))
        self._set_cached(cache_key, entries)
        return entries, None

    def fetch_file_content(
        self,
        repo_name: str,
        file_path: str,
        ref: Optional[str] = None,
        max_bytes: int = MAX_PREVIEW_FILE_BYTES,
    ) -> FileContentResult:
        """
        Fetch and decode a single file's content from GitHub with size checks,
        binary detection, and error isolation.
        """
        clean_path = file_path.strip("/")
        cache_key = f"{repo_name.lower()}::file::{clean_path}::{ref or 'default'}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        encoded_path = "/".join(quote(seg) for seg in clean_path.split("/") if seg)
        endpoint = f"/repos/{quote(self.config.github_org)}/{quote(repo_name)}/contents/{encoded_path}"
        params = {"ref": ref} if ref else None
        status, data, headers, err = self._request("GET", endpoint, params=params)

        default_html_url = f"https://github.com/{self.config.github_org}/{repo_name}/blob/main/{clean_path}"

        if status == 404:
            res = FileContentResult(
                repo_name=repo_name,
                path=clean_path,
                exists=False,
                html_url=default_html_url,
                error_message="File not found in repository.",
            )
            self._set_cached(cache_key, res)
            return res

        if status != 200 or not isinstance(data, dict):
            return FileContentResult(
                repo_name=repo_name,
                path=clean_path,
                exists=False,
                html_url=default_html_url,
                error_message=err or f"Unexpected response fetching '{clean_path}'.",
            )

        size = int(data.get("size") or 0)
        sha = str(data.get("sha") or "")
        html_url = str(data.get("html_url") or default_html_url)
        last_mod = headers.get("Last-Modified")

        if size > max_bytes:
            res = FileContentResult(
                repo_name=repo_name,
                path=clean_path,
                exists=True,
                size=size,
                sha=sha,
                html_url=html_url,
                last_modified=last_mod,
                too_large_for_preview=True,
                error_message=f"File size ({size:,} bytes) exceeds in-app preview limit ({max_bytes:,} bytes). Open directly on GitHub.",
            )
            self._set_cached(cache_key, res)
            return res

        encoding = str(data.get("encoding") or "")
        raw_content = data.get("content") or ""

        if encoding == "base64" and raw_content:
            try:
                raw_bytes = base64.b64decode(raw_content)
            except Exception as exc:
                return FileContentResult(
                    repo_name=repo_name,
                    path=clean_path,
                    exists=True,
                    size=size,
                    sha=sha,
                    html_url=html_url,
                    error_message=f"Failed to decode base64 file content: {exc}",
                )
        elif size == 0:
            raw_bytes = b""
        else:
            # If GitHub omitted base64 content (e.g. file near 1MB), try raw accept header
            raw_status, raw_body, _, raw_err = self._request(
                "GET",
                endpoint,
                params=params,
                accept="application/vnd.github.raw+json",
            )
            if raw_status == 200 and isinstance(raw_body, bytes):
                raw_bytes = raw_body
            else:
                return FileContentResult(
                    repo_name=repo_name,
                    path=clean_path,
                    exists=True,
                    size=size,
                    sha=sha,
                    html_url=html_url,
                    too_large_for_preview=True,
                    error_message=raw_err or "File content could not be retrieved inline; use the direct GitHub link.",
                )

        # Detect binary vs UTF-8 text
        is_binary = b"\x00" in raw_bytes[:8192]
        text_content: Optional[str] = None
        if not is_binary:
            try:
                text_content = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text_content = raw_bytes.decode("latin-1")
                except UnicodeDecodeError:
                    is_binary = True

        res = FileContentResult(
            repo_name=repo_name,
            path=clean_path,
            exists=True,
            size=size,
            sha=sha,
            raw_bytes=raw_bytes,
            text_content=text_content,
            html_url=html_url,
            last_modified=last_mod,
            is_binary=is_binary,
        )
        self._set_cached(cache_key, res)
        return res

    def fetch_recent_commits(self, repo_name: str, branch: Optional[str] = None, max_commits: int = 15) -> Tuple[List[CommitRecord], Optional[str]]:
        """Fetch recent commits with pagination support."""
        cache_key = f"{repo_name.lower()}::commits::{branch or 'default'}::{max_commits}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached, None

        endpoint = f"/repos/{quote(self.config.github_org)}/{quote(repo_name)}/commits"
        per_page = min(100, max(1, max_commits))
        params: Dict[str, Any] = {"per_page": per_page, "page": 1}
        if branch:
            params["sha"] = branch

        commits: List[CommitRecord] = []
        while len(commits) < max_commits:
            status, data, _, err = self._request("GET", endpoint, params=params)
            if status == 409:
                # 409 Conflict from GitHub means the repository is empty (0 commits)
                break
            if status != 200 or not isinstance(data, list):
                return commits, err
            if not data:
                break

            for item in data:
                if not isinstance(item, dict):
                    continue
                sha = str(item.get("sha") or "")
                commit_obj = item.get("commit") or {}
                author_obj = commit_obj.get("author") or {}
                gh_author = item.get("author") or {}
                msg = str(commit_obj.get("message") or "").splitlines()[0].strip()
                commits.append(
                    CommitRecord(
                        sha=sha,
                        short_sha=sha[:7],
                        message=msg,
                        author_name=str(author_obj.get("name") or gh_author.get("login") or "Unknown"),
                        author_login=str(gh_author.get("login") or ""),
                        committed_date=str(author_obj.get("date") or ""),
                        html_url=str(
                            item.get("html_url")
                            or f"https://github.com/{self.config.github_org}/{repo_name}/commit/{sha}"
                        ),
                    )
                )
                if len(commits) >= max_commits:
                    break

            if len(data) < per_page:
                break
            params["page"] += 1

        self._set_cached(cache_key, commits)
        return commits, None

    def fetch_repository_snapshot(self, repo_name: str, force_refresh: bool = False) -> RepositorySnapshot:
        """
        Retrieve a complete, fault-isolated snapshot of `repo_name`:
        1. Basic repository metadata (default branch, privacy, last push).
        2. Recursive Git tree (`GET /repos/{org}/{repo}/git/trees/{branch}?recursive=1`)
           so all custom folders, nested files, and convention files are discovered in 1 API call.
        3. Recent commits.
        4. Convention metadata files (`project/*.json`, `team/*.json`, `tasks/*.json`, `reviews/*.json`, `README.md`)
           only for files that actually exist in the repository tree (avoiding unnecessary 404 requests!).
        """
        if force_refresh:
            self.clear_cache(repo_name)

        cache_key = f"{repo_name.lower()}::snapshot"
        cached = self._get_cached(cache_key)
        if cached is not None and not force_refresh:
            return cached

        repo_endpoint = f"/repos/{quote(self.config.github_org)}/{quote(repo_name)}"
        status, repo_data, _, err = self._request("GET", repo_endpoint)
        default_repo_url = f"https://github.com/{self.config.github_org}/{repo_name}"

        if status != 200 or not isinstance(repo_data, dict):
            snap = RepositorySnapshot(
                org=self.config.github_org,
                repo_name=repo_name,
                accessible=False,
                status_code=status,
                error_message=err or f"Unable to access repository '{repo_name}' (HTTP {status}).",
                html_url=default_repo_url,
            )
            return snap

        default_branch = str(repo_data.get("default_branch") or "main")
        html_url = str(repo_data.get("html_url") or default_repo_url)

        # Fetch recursive git tree to discover all folders/files in a single API call
        tree_entries: List[RepoFileEntry] = []
        tree_truncated = False
        existing_paths: Dict[str, RepoFileEntry] = {}

        tree_endpoint = f"/repos/{quote(self.config.github_org)}/{quote(repo_name)}/git/trees/{quote(default_branch)}"
        t_status, t_data, _, _ = self._request("GET", tree_endpoint, params={"recursive": "1"})
        if t_status == 200 and isinstance(t_data, dict):
            tree_truncated = bool(t_data.get("truncated", False))
            for node in t_data.get("tree", []):
                if not isinstance(node, dict):
                    continue
                path_str = str(node.get("path") or "")
                if not path_str:
                    continue
                node_type = "dir" if node.get("type") == "tree" else "file"
                name = path_str.rsplit("/", 1)[-1]
                blob_kind = "tree" if node_type == "dir" else "blob"
                entry = RepoFileEntry(
                    name=name,
                    path=path_str,
                    item_type=node_type,
                    size=int(node.get("size") or 0),
                    sha=str(node.get("sha") or ""),
                    html_url=f"{html_url}/{blob_kind}/{default_branch}/{path_str}",
                )
                tree_entries.append(entry)
                existing_paths[path_str.lower()] = entry

        # Fetch recent commits
        recent_commits, _ = self.fetch_recent_commits(repo_name, branch=default_branch, max_commits=15)

        # Fetch convention files that exist in the tree (plus any additional review-*.json files in reviews/)
        convention_results: Dict[str, FileContentResult] = {}
        for key, rel_path in CONVENTION_FILES.items():
            if existing_paths and rel_path.lower() not in existing_paths:
                # We know from the recursive tree that the file does not exist; record missing without wasting an API call
                convention_results[rel_path] = FileContentResult(
                    repo_name=repo_name,
                    path=rel_path,
                    exists=False,
                    html_url=f"{html_url}/blob/{default_branch}/{rel_path}",
                    error_message="File not present in repository.",
                )
            else:
                convention_results[rel_path] = self.fetch_file_content(repo_name, rel_path, ref=default_branch)

        # Also dynamically discover any extra review files matching `reviews/review-*.json`
        for entry in tree_entries:
            if (
                entry.item_type == "file"
                and entry.path.lower().startswith("reviews/")
                and entry.path.lower().endswith(".json")
                and entry.path not in convention_results
            ):
                convention_results[entry.path] = self.fetch_file_content(repo_name, entry.path, ref=default_branch)

        snap = RepositorySnapshot(
            org=self.config.github_org,
            repo_name=repo_name,
            accessible=True,
            status_code=200,
            description=repo_data.get("description"),
            private=bool(repo_data.get("private", True)),
            default_branch=default_branch,
            html_url=html_url,
            pushed_at=repo_data.get("pushed_at"),
            updated_at=repo_data.get("updated_at"),
            size_kb=int(repo_data.get("size") or 0),
            open_issues_count=int(repo_data.get("open_issues_count") or 0),
            tree_entries=tree_entries,
            tree_truncated=tree_truncated,
            recent_commits=recent_commits,
            convention_raw_files=convention_results,
        )
        self._set_cached(cache_key, snap)
        return snap

    def commit_review_file(
        self,
        repo_name: str,
        file_path: str,
        json_payload: Dict[str, Any],
        commit_message: str,
        branch: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Explicitly write a validated review JSON record back to GitHub ONLY when
        `config.enable_github_writeback` is True and invoked by an authorized mentor/owner.
        Never overwrites student files silently.
        """
        if not self.config.enable_github_writeback:
            return (
                False,
                "GitHub write-back is disabled in configuration (`enable_github_writeback = false`). "
                "Feedback has been saved to the local mentor database instead.",
            )

        clean_path = file_path.strip("/")
        if not clean_path.startswith("reviews/") or not clean_path.endswith(".json"):
            return (
                False,
                "Write-back is strictly restricted to `reviews/*.json` files to prevent overwriting student project files.",
            )

        existing = self.fetch_file_content(repo_name, clean_path, ref=branch)
        encoded_content = base64.b64encode(
            json.dumps(json_payload, indent=2, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")

        body: Dict[str, Any] = {
            "message": commit_message,
            "content": encoded_content,
        }
        if branch:
            body["branch"] = branch
        if existing.exists and existing.sha:
            body["sha"] = existing.sha

        encoded_path = "/".join(quote(seg) for seg in clean_path.split("/") if seg)
        endpoint = f"/repos/{quote(self.config.github_org)}/{quote(repo_name)}/contents/{encoded_path}"
        status, _, _, err = self._request("PUT", endpoint, json_body=body)
        if status in (200, 201):
            self.clear_cache(repo_name)
            return True, f"Successfully committed `{clean_path}` to `{repo_name}`."
        return False, err or f"Failed to commit `{clean_path}` (HTTP {status})."

    def commit_structured_json(
        self,
        repo_name: str,
        file_path: str,
        json_payload: Dict[str, Any],
        commit_message: str,
        branch: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Explicitly commit a validated structured metadata JSON file (`project/*.json`,
        `team/*.json`, `tasks/tasks.json`, or `reviews/*.json`) to GitHub so both the
        Team 16 Dashboard and the Mentor Dashboard receive updates simultaneously.
        """
        if not self.config.enable_github_writeback:
            return (
                False,
                "GitHub write-back is disabled (`enable_github_writeback = false`). Set it to `true` in `.streamlit/secrets.toml`.",
            )

        clean_path = file_path.strip("/")
        allowed_prefixes = ("project/", "team/", "tasks/", "reviews/")
        if not clean_path.startswith(allowed_prefixes) or not clean_path.endswith(".json"):
            return (
                False,
                "Write-back is restricted to structured JSON files inside `project/`, `team/`, `tasks/`, and `reviews/`.",
            )

        existing = self.fetch_file_content(repo_name, clean_path, ref=branch)
        encoded_content = base64.b64encode(
            json.dumps(json_payload, indent=2, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")

        body: Dict[str, Any] = {
            "message": commit_message,
            "content": encoded_content,
        }
        if branch:
            body["branch"] = branch
        if existing.exists and existing.sha:
            body["sha"] = existing.sha

        encoded_path = "/".join(quote(seg) for seg in clean_path.split("/") if seg)
        endpoint = f"/repos/{quote(self.config.github_org)}/{quote(repo_name)}/contents/{encoded_path}"
        status, _, _, err = self._request("PUT", endpoint, json_body=body)
        if status in (200, 201):
            self.clear_cache(repo_name)
            return True, f"Successfully committed `{clean_path}` to `{repo_name}` on GitHub."
        return False, err or f"Failed to commit `{clean_path}` (HTTP {status})."
