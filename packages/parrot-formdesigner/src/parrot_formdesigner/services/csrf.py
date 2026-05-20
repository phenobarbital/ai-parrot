"""CSRF token utilities for the remote events endpoint — FEAT-188.

Issues and validates per-session per-form CSRF tokens using an in-process
store with a soft TTL of 1 hour.

MVP limitations:
- In-process dictionary store — tokens are NOT shared across multiple worker
  processes (e.g., gunicorn with multiple workers).  For production deployments
  with multi-process servers, replace ``_STORE`` with a shared backend such as
  Redis.  This is intentional for the MVP; production hardening is a follow-up
  tracked in the spec §3 Module 6 notes.
"""

from __future__ import annotations

import secrets
import time
from typing import Final

_TTL_SECONDS: Final[int] = 3600
# In-process store: {(session_id, form_id): (token, expires_at)}
_STORE: dict[tuple[str, str], tuple[str, float]] = {}


def issue_form_csrf_token(session_id: str, form_id: str) -> str:
    """Issue a CSRF token for the given session / form pair.

    The token is stored in-process with a TTL of :data:`_TTL_SECONDS`.
    Any previously issued token for the same ``(session_id, form_id)`` is
    replaced.

    Args:
        session_id: Session identifier extracted from the navigator-auth
            session cookie.
        form_id: Form identifier from the URL path.

    Returns:
        A URL-safe 32-byte random token string.
    """
    token = secrets.token_urlsafe(32)
    _STORE[(session_id, form_id)] = (token, time.monotonic() + _TTL_SECONDS)
    return token


def validate_form_csrf_token(session_id: str, form_id: str, token: str) -> bool:
    """Validate a CSRF token against the in-process store.

    Performs a constant-time comparison to prevent timing attacks.  Expired
    entries are pruned on access.

    Args:
        session_id: Session identifier.
        form_id: Form identifier.
        token: Token string from the ``X-CSRF-Token`` / ``X-Form-CSRF-Token``
            request header.

    Returns:
        ``True`` if the token matches and has not expired; ``False`` otherwise.
    """
    entry = _STORE.get((session_id, form_id))
    if entry is None:
        return False
    stored_token, expires_at = entry
    if time.monotonic() > expires_at:
        _STORE.pop((session_id, form_id), None)
        return False
    return secrets.compare_digest(stored_token, token)


def _clear_csrf_store_for_tests() -> None:
    """Clear all CSRF tokens — for use in test teardown only."""
    _STORE.clear()
