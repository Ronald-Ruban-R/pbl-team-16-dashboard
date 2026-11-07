"""
Security, Authentication, Role-Based Access Control (RBAC), and Sanitization Module.

Enforces:
- Salted PBKDF2-HMAC-SHA256 password verification (`hashlib.pbkdf2_hmac` + `hmac.compare_digest`).
- Strict separation between `owner` (Team Lead / Organization Owner — full JSON write access),
  `mentor` (Mentor feedback access), and `student` (Team Member — strictly read-only access).
- Secret redaction so tokens/PEM keys never leak into error messages or logs.
- Safe Markdown sanitization to strip unsafe `<script>`, `<iframe>`, `javascript:` links.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.config import to_plain_dict


class UserRole(str, Enum):
    """Supported dashboard user roles."""

    OWNER = "owner"
    MENTOR = "mentor"
    STUDENT = "student"


PBKDF2_ITERATIONS: int = 260_000


def hash_password_pbkdf2(password: str, salt: Optional[str] = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Create a salted PBKDF2-HMAC-SHA256 password hash string."""
    if not password:
        raise ValueError("Password cannot be empty.")
    salt_hex = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_hex.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt_hex}${dk.hex()}"


def verify_password_pbkdf2(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored `pbkdf2_sha256$iterations$salt$hex` hash in constant time."""
    if not password or not stored_hash:
        return False
    parts = stored_hash.strip().split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
        salt_hex = parts[2]
        expected_hex = parts[3]
    except ValueError:
        return False

    candidate_dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_hex.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(candidate_dk, expected_hex)


_SECRET_PATTERNS = [
    re.compile(r"(gh[pousr]_[A-Za-z0-9_]{8,})"),
    re.compile(r"(github_pat_[A-Za-z0-9_]{12,})"),
    re.compile(r"(Bearer\s+[A-Za-z0-9\-._~+/]+=*)", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(pbkdf2_sha256\$\d+\$[A-Za-z0-9]+\$[A-Za-z0-9]+)"),
]


def redact_secrets(text: Optional[str]) -> str:
    """Mask any GitHub PATs, Bearer tokens, private keys, or password hashes from strings."""
    if not text:
        return ""
    cleaned = str(text)
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED_SECRET]", cleaned)
    return cleaned


_UNSAFE_HTML_TAG_RE = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|form|input|button|style|link|meta)\b[^>]*>",
    re.IGNORECASE,
)
_JS_LINK_RE = re.compile(r"javascript\s*:", re.IGNORECASE)


def sanitize_markdown_for_display(md_text: Optional[str]) -> str:
    """Sanitize repository Markdown content prior to rendering."""
    if not md_text:
        return ""
    cleaned = _UNSAFE_HTML_TAG_RE.sub("", md_text)
    cleaned = _JS_LINK_RE.sub("blocked-js:", cleaned)
    return cleaned


@dataclass(frozen=True)
class AuthenticatedUser:
    """Authenticated user context with RBAC helpers."""

    username: str
    display_name: str
    role: UserRole
    allowed_repos: Tuple[str, ...] = field(default_factory=tuple)

    def can_access_repo(self, repo_name: str) -> bool:
        """Return True if this user is permitted to view `repo_name`."""
        target = (repo_name or "").strip().lower()
        if not target:
            return False
        if self.role == UserRole.OWNER and ("*" in self.allowed_repos or not self.allowed_repos):
            return True
        normalized = {r.strip().lower() for r in self.allowed_repos}
        return "*" in normalized or target in normalized

    def can_edit_repo_metadata(self, repo_name: str) -> bool:
        """
        Return True ONLY if the user has `role = "owner"` (Team Lead / Organization Owner)
        and is authorized for `repo_name`. Users with `role = "student"` are strictly read-only.
        """
        return self.role == UserRole.OWNER and self.can_access_repo(repo_name)

    def can_write_feedback(self, repo_name: str) -> bool:
        """Return True if the user is an `owner` or `mentor` authorized for `repo_name`."""
        return self.role in (UserRole.OWNER, UserRole.MENTOR) and self.can_access_repo(repo_name)

    def can_manage_settings(self) -> bool:
        """Return True if the user can access password hashing and SQLite reset utilities."""
        return self.role in (UserRole.OWNER, UserRole.MENTOR)


class AccessControlManager:
    """Loads user credentials from Streamlit secrets and enforces per-repository authorization."""

    def __init__(self, secrets_map: Optional[Mapping] = None, configured_repos: Optional[Iterable[str]] = None):
        self._configured_repos: Tuple[str, ...] = tuple(configured_repos or ())
        self._users: Dict[str, Dict[str, Any]] = {}
        self._load_users(secrets_map)

    def _load_users(self, secrets_map: Optional[Mapping]) -> None:
        plain = to_plain_dict(secrets_map) if secrets_map is not None else {}
        if not isinstance(plain, dict):
            return
        auth_sec = plain.get("auth", {})
        if not isinstance(auth_sec, Mapping):
            return
        users_sec = auth_sec.get("users", {})
        if not isinstance(users_sec, Mapping):
            return

        for raw_username, uinfo in users_sec.items():
            if not isinstance(uinfo, Mapping):
                continue
            uname = str(raw_username).strip()
            if not uname:
                continue
            pw_hash = str(uinfo.get("password_hash") or "").strip()
            if not pw_hash:
                continue
            role_raw = str(uinfo.get("role") or "student").strip().lower()
            try:
                role = UserRole(role_raw)
            except ValueError:
                role = UserRole.STUDENT

            allowed_raw = uinfo.get("allowed_repos", ["*"])
            if isinstance(allowed_raw, str):
                allowed = tuple(r.strip() for r in allowed_raw.split(",") if r.strip())
            elif isinstance(allowed_raw, (list, tuple)):
                allowed = tuple(str(r).strip() for r in allowed_raw if str(r).strip())
            else:
                allowed = ("*",)

            self._users[uname.lower()] = {
                "username": uname,
                "display_name": str(uinfo.get("display_name") or uname),
                "role": role,
                "password_hash": pw_hash,
                "allowed_repos": allowed,
            }

    def is_auth_configured(self) -> bool:
        """Return True if at least one valid user account is configured in secrets."""
        return len(self._users) > 0

    def authenticate(self, username: str, password: str) -> Optional[AuthenticatedUser]:
        """Verify username and password in constant time and return `AuthenticatedUser` on match."""
        key = (username or "").strip().lower()
        record = self._users.get(key)
        if not record:
            return None
        if not verify_password_pbkdf2(password, record["password_hash"]):
            return None

        raw_allowed = record["allowed_repos"]
        if "*" in raw_allowed and self._configured_repos:
            effective_allowed = tuple(self._configured_repos)
        else:
            effective_allowed = tuple(raw_allowed)

        return AuthenticatedUser(
            username=record["username"],
            display_name=record["display_name"],
            role=record["role"],
            allowed_repos=effective_allowed,
        )

    def authorize_repo_access(self, user: AuthenticatedUser, repo_name: str) -> None:
        """Raise PermissionError if `user` is not authorized to access `repo_name`."""
        if not user.can_access_repo(repo_name):
            raise PermissionError(
                f"User '{user.username}' ({user.role.value}) is not authorized to access '{repo_name}'."
            )
