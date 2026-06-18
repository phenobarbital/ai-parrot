"""Per-tenant FULL mode configuration resolver (FEAT-248 — Module 3).

Provides ``resolve_fullmode_config(tenant_id) -> FullModeConfig``, the single
public interface for resolving a fully-populated :class:`FullModeConfig` for a
given tenant.

Resolution order (first match wins):
1. (Future) Per-tenant DB overrides via ``TenantAvatarConfig`` —
   gated by Q-tenant-config-store (see §8 Open Questions in the spec).
2. Environment variables (``LIVEAVATAR_*``).
3. :class:`FullModeConfig` field defaults.

Interim implementation (env-only)
----------------------------------
The DB override layer is deferred until Q-tenant-config-store is resolved
(choice of program-DB column, NavConfig key, or feature-flag service).
All callers interact with the same ``resolve_fullmode_config`` interface —
only the backing resolution changes when the DB layer is added.

Environment variables
---------------------
``LIVEAVATAR_API_KEY`` (required)
    LiveAvatar API key.

``LIVEAVATAR_AVATAR_ID`` (required)
    Default avatar ID.

``LIVEAVATAR_VOICE_ID`` (optional)
    Default voice ID (``None`` → avatar default).

``LIVEAVATAR_LANGUAGE`` (optional, default ``"en"``)
    Default BCP-47 language tag.

``LIVEAVATAR_INTERACTIVITY_TYPE`` (optional, default ``"CONVERSATIONAL"``)
    Default interactivity type (``"CONVERSATIONAL"`` or ``"PUSH_TO_TALK"``).

``LIVEAVATAR_BASE_URL`` (optional, default ``https://api.liveavatar.com``)
    LiveAvatar API base URL.

``LIVEAVATAR_SANDBOX`` (optional, default ``"true"``)
    Sandbox mode flag.  Set to ``"false"`` for production.

``LIVEAVATAR_MAX_SESSION_DURATION`` (optional)
    Safety-net maximum session duration in seconds.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from parrot.integrations.liveavatar.models import FullModeConfig

_logger = logging.getLogger("Parrot.LiveAvatarTenantConfig")


def _parse_int_env(name: str) -> Optional[int]:
    """Parse an optional integer environment variable.

    Args:
        name: Environment variable name.

    Returns:
        Parsed integer or ``None`` if unset / not parseable.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        _logger.warning(
            "LiveAvatarTenantConfig: invalid %s=%r (expected integer); ignoring.", name, raw
        )
        return None


def resolve_fullmode_config(
    tenant_id: Optional[str] = None,
) -> FullModeConfig:
    """Resolve a :class:`FullModeConfig` from env defaults (+ future DB overrides).

    Resolution order:
    1. (Future) Per-tenant DB overrides via ``TenantAvatarConfig`` —
       TODO Q-tenant-config-store: overlay per-tenant DB values here once the
       storage layer (program DB column / NavConfig / feature-flag service) is
       agreed.
    2. Environment variables (``LIVEAVATAR_*``).
    3. :class:`FullModeConfig` field defaults.

    Args:
        tenant_id: Optional tenant identifier.  When provided, it will be used
            to look up per-tenant DB overrides in the future (see TODO above).
            Ignored by the current env-only implementation.

    Returns:
        A fully-populated :class:`FullModeConfig` ready for session creation.

    Raises:
        RuntimeError: If ``LIVEAVATAR_API_KEY`` or ``LIVEAVATAR_AVATAR_ID`` env
            vars are missing.
    """
    api_key = os.environ.get("LIVEAVATAR_API_KEY", "").strip()
    avatar_id = os.environ.get("LIVEAVATAR_AVATAR_ID", "").strip()

    if not api_key or not avatar_id:
        raise RuntimeError(
            "LIVEAVATAR_API_KEY and LIVEAVATAR_AVATAR_ID must be set to use "
            "LiveAvatar FULL mode.  Check your environment configuration."
        )

    voice_id: Optional[str] = os.environ.get("LIVEAVATAR_VOICE_ID", "").strip() or None
    language: str = os.environ.get("LIVEAVATAR_LANGUAGE", "en").strip() or "en"
    interactivity_type: str = (
        os.environ.get("LIVEAVATAR_INTERACTIVITY_TYPE", "CONVERSATIONAL").strip()
        or "CONVERSATIONAL"
    )
    base_url: str = (
        os.environ.get("LIVEAVATAR_BASE_URL", "https://api.liveavatar.com").strip()
        or "https://api.liveavatar.com"
    )
    is_sandbox: bool = (
        os.environ.get("LIVEAVATAR_SANDBOX", "true").strip().lower() != "false"
    )
    max_session_duration: Optional[int] = _parse_int_env("LIVEAVATAR_MAX_SESSION_DURATION")

    # TODO Q-tenant-config-store: if tenant_id is provided, look up a
    # TenantAvatarConfig record and overlay its non-None fields here.
    # Example (pseudocode, not yet implemented):
    #   if tenant_id:
    #       overrides = await TenantConfigStore.get(tenant_id)
    #       if overrides:
    #           if overrides.api_key: api_key = overrides.api_key
    #           if overrides.avatar_id: avatar_id = overrides.avatar_id
    #           if overrides.voice_id: voice_id = overrides.voice_id
    #           if overrides.language: language = overrides.language
    #           ...

    _logger.debug(
        "LiveAvatarTenantConfig: resolved config for tenant=%r (env-only)",
        tenant_id,
    )

    return FullModeConfig(
        api_key=api_key,
        avatar_id=avatar_id,
        voice_id=voice_id,
        language=language,
        interactivity_type=interactivity_type,
        base_url=base_url,
        is_sandbox=is_sandbox,
        max_session_duration=max_session_duration,
    )
