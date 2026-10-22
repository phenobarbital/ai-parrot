"""Studio base helpers — slug/path validation and the resolved caller identity."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    from navigator_auth.conf import AUTH_SESSION_OBJECT
except ImportError:  # pragma: no cover — navigator-auth always installed in prod
    AUTH_SESSION_OBJECT = "userinfo"

# Superuser/admin group convention — mirrors
# navigator_auth.decorators.SUPERUSER_GROUP / `_check_superuser` (private
# helpers in that module; the check is small enough to replicate here
# rather than reach into navigator_auth internals).
SUPERUSER_GROUP = "superuser"

# Studio agent/asset slug convention — same regex as
# handlers/bots.py `_AGENT_SLUG_RE` (:85).
STUDIO_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


def is_valid_slug(value: str) -> bool:
    """Return ``True`` if ``value`` matches the Studio slug convention.

    Args:
        value: Candidate slug (agent name, skill name, draft name, ...).

    Returns:
        ``True`` when ``value`` matches ``^[a-z0-9_-]+$`` and is non-empty.
    """
    return bool(value) and bool(STUDIO_SLUG_RE.match(value))


def resolve_safe_path(base_dir: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``base_dir``, rejecting traversal escapes.

    Rejects absolute paths, ``..`` segments, and symlink escapes — any
    path that would resolve outside ``base_dir`` once both are fully
    resolved. Used by file/draft-management Studio endpoints (TASK-2513/
    TASK-2514) to keep on-disk writes sandboxed to their intended
    directory.

    Args:
        base_dir: The directory the resolved path MUST stay inside.
        relative: The caller-supplied relative path/filename.

    Returns:
        The resolved, safe ``Path``.

    Raises:
        ValueError: ``relative`` is empty, absolute, contains a ``..``
            segment, or resolves outside ``base_dir`` (including via a
            symlink escape).
    """
    if not relative:
        raise ValueError("Path must not be empty.")
    rel_path = Path(relative)
    if rel_path.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {relative!r}")
    if ".." in rel_path.parts:
        raise ValueError(f"Path traversal is not allowed: {relative!r}")

    base_resolved = Path(base_dir).resolve()
    candidate = (base_resolved / rel_path).resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        raise ValueError(f"Resolved path escapes the sandboxed directory: {relative!r}") from None
    return candidate


@dataclass(slots=True)
class StudioUser:
    """Resolved caller identity for a Studio request.

    Attributes:
        user_id: The session's authenticated user id (always a string).
        email: Best-effort email from session userinfo, if present.
        username: Best-effort username from session userinfo, if present.
        groups: Group memberships from session userinfo (empty list if none).
        is_superuser: Derived admin/superuser flag — bypasses ownership
            checks in :meth:`StudioBaseView._require_owner`.
        tenant: Resolved tenant (opted-in hosts only).
        may_author: Host authoring gate (opted-in hosts only).
        may_administer: Host tenant-admin gate (opted-in hosts only).
    """

    user_id: str
    email: str | None = None
    username: str | None = None
    groups: list[str] = field(default_factory=list)
    is_superuser: bool = False
    tenant: str | None = None
    may_author: bool = True
    may_administer: bool = False
