"""Canonical identity mapper for cross-surface credential reuse.

Normalises per-surface raw identity data to a single canonical vault key
so credentials captured on A2A are honoured in MSAgentSDK chat (and any
other surface) without re-authentication.

Precedence: Entra OID (UUID) → email (lower-cased) → ``None`` (fail closed).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

__all__ = ["CanonicalIdentityMapper"]

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# ---------------------------------------------------------------------------
# Field priority lists
# ---------------------------------------------------------------------------

# Fields that carry an Entra Object ID (stable across surfaces), checked in
# order of precedence.  Only UUID-shaped values are accepted as OIDs.
_OID_FIELDS: tuple[str, ...] = (
    "oid",
    "aad_object_id",    # MSAgentSDK: activity.from_property.aad_object_id
    "aadObjectId",      # camelCase variant (raw activity JSON)
    "from_id",          # A2A: flattened metadata.from.id when UUID-shaped
)

# Fields that carry an email address, checked in order of precedence.
_EMAIL_FIELDS: tuple[str, ...] = (
    "email",
    "upn",              # User Principal Name (Entra — often email-shaped)
    "from_email",       # A2A: flattened metadata.from.email
    "from.email",       # A2A: nested metadata dict key
    "x-ms-user-email",  # A2A: metadata header field
    "x_ms_user_email",  # underscore variant
    "sender",           # A2A: metadata.sender (only when email-shaped)
)


# ---------------------------------------------------------------------------
# CanonicalIdentityMapper
# ---------------------------------------------------------------------------


class CanonicalIdentityMapper:
    """Maps raw per-surface identity data to a single canonical vault key.

    The canonical key is used as the *user_id* parameter when the broker looks
    up credentials in the vault.  Credentials stored under one surface are
    automatically reusable on any other surface that resolves to the same
    canonical key.

    Precedence (most stable → least stable):
    1. Entra OID (UUID string) — stable across surface changes and email renames.
    2. Email address (lower-cased) — stable across surfaces but not renames.
    3. ``None`` — anonymous / development identity; callers **must** fail closed.

    The mapper is stateless; call :meth:`to_canonical` directly or use the
    module-level singleton :data:`identity_mapper`.
    """

    @staticmethod
    def to_canonical(raw_identity: Dict[str, Any]) -> Optional[str]:
        """Map a raw identity dict to a canonical vault key.

        Accepts a flat or lightly-nested dict produced by any surface extractor
        (A2A server, MSAgentSDK agent, etc.).  Unknown keys are silently ignored.

        Args:
            raw_identity: Mapping produced by the surface layer.  Supported
                key layouts:

                * A2A (from ``A2AServer._extract_identity`` precedents):
                  ``{"from_id": "<uuid>", "from_email": "alice@corp.com",
                  "x-ms-user-email": "...", "sender": "..."}``
                * MSAgentSDK (from ``ParrotM365Agent._extract_user_id``
                  precedents): ``{"aad_object_id": "<uuid>", "email": "..."}``

        Returns:
            Canonical key string:
            - The Entra OID (lower-cased UUID) when found in any OID field.
            - The lower-cased email when no OID is present.
            - ``None`` when neither can be found — the caller must fail closed
              and refuse to resolve credentials.
        """
        # --- Phase 1: look for a stable Entra OID ---
        for field in _OID_FIELDS:
            val = _get(raw_identity, field)
            if val and isinstance(val, str):
                stripped = val.strip()
                if _UUID_PATTERN.match(stripped):
                    return stripped.lower()

        # --- Phase 2: look for an email address ---
        for field in _EMAIL_FIELDS:
            val = _get(raw_identity, field)
            if val and isinstance(val, str):
                stripped = val.strip()
                if _EMAIL_PATTERN.match(stripped):
                    return stripped.lower()

        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Default instance — import and call ``identity_mapper.to_canonical(...)``
#: or use ``CanonicalIdentityMapper.to_canonical(...)`` directly.
identity_mapper: CanonicalIdentityMapper = CanonicalIdentityMapper()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(d: Dict[str, Any], key: str) -> Any:
    """Retrieve a value from *d* by key, supporting dotted-key notation.

    Args:
        d: The source mapping.
        key: Flat key (e.g. ``"email"``) or dotted path (e.g. ``"from.email"``).

    Returns:
        The value if found, otherwise ``None``.
    """
    if key in d:
        return d[key]
    if "." in key:
        head, tail = key.split(".", 1)
        sub = d.get(head)
        if isinstance(sub, dict):
            return _get(sub, tail)
    return None
