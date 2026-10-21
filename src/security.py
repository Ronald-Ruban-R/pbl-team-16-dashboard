"""
Security, authentication, role-based access control (RBAC), and content sanitization.

Design principles:
1. Never expose GitHub credentials, tokens, or secrets in UI components, URLs, or logs.
2. Enforce server-side authorization checks before any repository or team data is accessed.
3. Support the two Organization Owners (`owner` / `mentor` roles) with full access to all
   six repositories (`pbl-team-13`..`pbl-team-18`), while supporting future `student` role
   accounts strictly scoped to their single assigned repository.
4. Provide constant-time password verification (PBKDF2-HMAC-SHA256) and safe Markdown/HTML
   sanitization so untrusted repository files cannot execute XSS in the browser.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from src.config import to_plain_dict


class UserRole(str, Enum):
    """Supported application roles."""

    OWNER = "owner"      # Organization owner / Lead Mentor (full access to all 6 repos + settings)
    MENTOR = "mentor"    # Co-mentor / evaluator (access to configured repos, read + review feedback)
    STUDENT = "student"  # Future student view (strictly restricted to their single team repo)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Represents a verified dashboard user session."""

    username: str
    display_name: str
    role: UserRole
    allowed_repos: Tuple[str, ...] = field(default_factory=tuple)
    email: Optional[str] = None
    csrf_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    def can_access_repo(self, repo_name: str) -> bool:
        """
        Server-side authorization check for whether this user can access `repo_name`.

        - Organization owners can access all configured cohort repositories.
        - Mentors can access all repositories listed in `allowed_repos` (or `*`).
        - Students can ONLY access the exact repository explicitly assigned to them,
          preventing URL parameter or selector tampering.
        """
        normalized = (repo_name or "").strip().lower()
        if not normalized:
            return False
        if self.role == UserRole.OWNER:
            if "*" in self.allowed_repos:
                return True
            return normalized in {r.lower() for r in self.allowed_repos}
        if self.role == UserRole.MENTOR:
            if "*" in self.allowed_repos:
                return True
            return normalized in {r.lower() for r in self.allowed_repos}
        if self.role == UserRole.STUDENT:
            # Students are never permitted wildcard access
            explicit_allowed = {r.lower() for r in self.allowed_repos if r != "*"}
            return normalized in explicit_allowed
        return False

    def can_write_feedback(self, repo_name: str) -> bool:
        """Only Owners and Mentors authorized for the repository can record review feedback."""
        if self.role not in (UserRole.OWNER, UserRole.MENTOR):
            return False
        return self.can_access_repo(repo_name)

    def can_manage_settings(self) -> bool:
        """Only Organization Owners can modify cohort-wide settings or trigger GitHub writeback."""
        return self.role == UserRole.OWNER


class AuthorizationError(PermissionError):
    """Raised when a user attempts to access a repository or action outside their scope."""


def hash_password_pbkdf2(password: str, salt: Optional[str] = None, iterations: int = 260_000) -> str:
    """
    Create a PBKDF2-HMAC-SHA256 password hash string formatted as:
    `pbkdf2_sha256$<iterations>$<salt>$<hex_digest>`
    """
    if not password:
        raise ValueError("Password cannot be empty.")
    salt_val = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_val.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt_val}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Verify a password against a `pbkdf2_sha256$...` hash or a `sha256$<hex>` hash
    using constant-time comparison (`hmac.compare_digest`).
    """
    if not password or not stored_hash:
        return False

    cleaned_hash = stored_hash.strip()
    try:
        if cleaned_hash.startswith("pbkdf2_sha256$"):
            parts = cleaned_hash.split("$")
            if len(parts) != 4:
                return False
            _, iter_str, salt, _ = parts
            iterations = int(iter_str)
            candidate = hash_password_pbkdf2(password, salt=salt, iterations=iterations)
            return hmac.compare_digest(candidate, cleaned_hash)

        if cleaned_hash.startswith("sha256$"):
            _, expected_hex = cleaned_hash.split("$", 1)
            actual_hex = hashlib.sha256(password.encode("utf-8")).hexdigest()
            return hmac.compare_digest(actual_hex.lower(), expected_hex.strip().lower())

        return False
    except (ValueError, TypeError):
        return False


class AccessControlManager:
    """
    Manages user authentication and role-based repository authorization.

    Loads user definitions from `.streamlit/secrets.toml` (`[auth.users]`) or
    environment variables (`PBL_OWNER_1_USERNAME`, `PBL_OWNER_1_PASSWORD_HASH`, etc.).
    Correctly handles Streamlit's nested `AttrDict` (`collections.abc.Mapping`) objects.
    """

    def __init__(self, secrets_map: Optional[Mapping] = None, configured_repos: Optional[List[str]] = None):
        plain = to_plain_dict(secrets_map) if secrets_map is not None else {}
        self.secrets_map: Dict = plain if isinstance(plain, dict) else {}
        self.configured_repos = tuple(configured_repos or [])
        self._users: Dict[str, Dict] = self._load_users()

    def _load_users(self) -> Dict[str, Dict]:
        users: Dict[str, Dict] = {}
        auth_section = self.secrets_map.get("auth", {})
        if not isinstance(auth_section, Mapping):
            auth_section = {}

        users_cfg = auth_section.get("users", {})
        if not isinstance(users_cfg, Mapping):
            users_cfg = {}

        for uname, udata in users_cfg.items():
            if not isinstance(udata, Mapping):
                continue
            role_str = str(udata.get("role", "mentor")).lower()
            try:
                role = UserRole(role_str)
            except ValueError:
                role = UserRole.STUDENT

            allowed = udata.get("allowed_repos", list(self.configured_repos) if role != UserRole.STUDENT else [])
            if isinstance(allowed, str):
                allowed_tuple = tuple(r.strip() for r in allowed.split(",") if r.strip())
            else:
                allowed_tuple = tuple(str(r).strip() for r in allowed if str(r).strip())

            pw_hash = str(udata.get("password_hash", "")).strip()
            # Ignore unedited template placeholders so we can give a clear diagnostic if unedited
            if pw_hash.startswith("<") and pw_hash.endswith(">"):
                pw_hash = ""

            users[str(uname).strip().lower()] = {
                "username": str(uname).strip(),
                "display_name": str(udata.get("display_name", str(uname).strip())),
                "password_hash": pw_hash,
                "role": role,
                "allowed_repos": allowed_tuple,
                "email": udata.get("email"),
            }

        # Support environment variable configuration for the two Organization Owners
        for idx in (1, 2):
            env_user = os.environ.get(f"PBL_OWNER_{idx}_USERNAME")
            env_hash = os.environ.get(f"PBL_OWNER_{idx}_PASSWORD_HASH")
            env_name = os.environ.get(f"PBL_OWNER_{idx}_DISPLAY_NAME", f"Organization Owner {idx}")
            if env_user and env_hash:
                users[env_user.strip().lower()] = {
                    "username": env_user.strip(),
                    "display_name": env_name,
                    "password_hash": env_hash.strip(),
                    "role": UserRole.OWNER,
                    "allowed_repos": self.configured_repos or ("*",),
                    "email": os.environ.get(f"PBL_OWNER_{idx}_EMAIL"),
                }

        return users

    def is_auth_configured(self) -> bool:
        """Return True if at least one user account with a valid password hash is configured."""
        return any(bool(u.get("password_hash")) for u in self._users.values())

    def authenticate(self, username: str, password: str) -> Optional[AuthenticatedUser]:
        """Verify username and password and return an `AuthenticatedUser` on success."""
        if not username or not password:
            return None
        lookup = username.strip().lower()
        record = self._users.get(lookup)
        if not record:
            for urec in self._users.values():
                if urec.get("display_name", "").strip().lower() == lookup:
                    record = urec
                    break
        if not record:
            verify_password(
                password,
                "pbkdf2_sha256$260000$00000000000000000000000000000000$0000000000000000000000000000000000000000000000000000000000000000",
            )
            return None

        if not verify_password(password, record.get("password_hash", "")):
            return None

        return AuthenticatedUser(
            username=record["username"],
            display_name=record["display_name"],
            role=record["role"],
            allowed_repos=record["allowed_repos"],
            email=record.get("email"),
        )

    def authorize_repo_access(self, user: Optional[AuthenticatedUser], repo_name: str) -> None:
        """
        Enforce server-side repository access control.
        Raises `AuthorizationError` if `user` is unauthenticated or not permitted for `repo_name`.
        """
        if user is None:
            raise AuthorizationError("Authentication required to access repository data.")
        if repo_name.lower() not in {r.lower() for r in self.configured_repos} and "*" not in user.allowed_repos:
            raise AuthorizationError(f"Repository '{repo_name}' is not in the configured cohort registry.")
        if not user.can_access_repo(repo_name):
            raise AuthorizationError(
                f"Access denied: User '{user.username}' ({user.role.value}) is not authorized for repository '{repo_name}'."
            )

    def filter_authorized_repos(self, user: Optional[AuthenticatedUser], repos: List[str]) -> List[str]:
        """Return only the subset of `repos` that `user` is authorized to view."""
        if user is None:
            return []
        return [r for r in repos if user.can_access_repo(r)]


# ---------------------------------------------------------------------------
# Content Sanitization & Redaction Utilities
# ---------------------------------------------------------------------------

_SCRIPT_TAG_RE = re.compile(r"<\s*(script|iframe|object|embed|form|style|meta|link|base)\b[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_SELF_CLOSING_DANGEROUS_RE = re.compile(r"<\s*(script|iframe|object|embed|meta|link|base|input|button)\b[^>]*/?\s*>", re.IGNORECASE)
_EVENT_HANDLER_RE = re.compile(r"\bon[a-z]+\s*=\s*(['\"].*?['\"]|[^\s>]+)", re.IGNORECASE | re.DOTALL)
_JS_URI_RE = re.compile(r"(javascript|vbscript|data)\s*:", re.IGNORECASE)
_TOKEN_REDACT_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|ghs_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9_\-\.]+)"
)


def sanitize_markdown_for_display(markdown_text: str) -> str:
    """
    Sanitize repository Markdown content before rendering in Streamlit.
    Strips raw HTML script/iframe/object tags, inline `on*` event handlers,
    and `javascript:` / `data:` URIs while keeping standard Markdown intact.
    """
    if not markdown_text:
        return ""
    cleaned = _SCRIPT_TAG_RE.sub("[removed unsafe HTML block]", markdown_text)
    cleaned = _SELF_CLOSING_DANGEROUS_RE.sub("[removed unsafe HTML tag]", cleaned)
    cleaned = _EVENT_HANDLER_RE.sub("", cleaned)
    cleaned = _JS_URI_RE.sub("blocked-scheme:", cleaned)
    return cleaned


def is_safe_external_url(url: Optional[str]) -> bool:
    """Validate that a URL uses strictly `https://` or `http://` or is a relative repository path."""
    if not url or not isinstance(url, str):
        return False
    stripped = url.strip()
    if not stripped:
        return False
    if _JS_URI_RE.search(stripped):
        return False
    parsed = urlparse(stripped)
    if parsed.scheme in ("https", "http"):
        return bool(parsed.netloc)
    if parsed.scheme == "" and not stripped.startswith("//"):
        return ".." not in stripped.split("/")
    return False


def redact_secrets(text: str) -> str:
    """Redact any accidental GitHub tokens or Bearer credentials from error messages or logs."""
    if not text:
        return ""
    return _TOKEN_REDACT_RE.sub("[REDACTED_CREDENTIAL]", str(text))


def escape_html_text(text: str) -> str:
    """Escape untrusted plain text for safe display."""
    return html.escape(str(text or ""), quote=True)
