"""Per-tenant opt-in gating for LiveAvatar LITE mode (FEAT-242 Phase A — Module 7).

Provides ``is_avatar_enabled(tenant_id, agent_name) -> bool``, the single
public interface all callers use to decide whether avatar mode may be
activated for a given tenant + agent combination.

**Default-deny**: if opt-in cannot be resolved, avatar mode is OFF.

Interim implementation — env/config-driven allowlist
-----------------------------------------------------
The permanent flag location (program DB table, NavConfig, or a dedicated
feature-flag service) is unresolved as of FEAT-242 Phase A (Q-tenant).

Interim source: two environment variables control the allowlist:

``LIVEAVATAR_ENABLED_TENANTS``
    Comma-separated list of tenant IDs that may use avatar mode, e.g.::

        LIVEAVATAR_ENABLED_TENANTS=acme,demo,internal-qa

    Set to ``*`` to opt-in ALL tenants (use only in development/staging).
    Absent or empty → no tenant is enabled (default-deny).

``LIVEAVATAR_ENABLED_AGENTS``
    Optional comma-separated list of agent names (slugs) that must also
    match.  If absent, any agent name is allowed for an enabled tenant.
    If set, BOTH ``tenant_id`` AND ``agent_name`` must appear in their
    respective lists.

Resolution order (first match wins):
1. Wildcard ``*`` in ``LIVEAVATAR_ENABLED_TENANTS`` → allow all tenants.
2. ``tenant_id`` appears in ``LIVEAVATAR_ENABLED_TENANTS`` AND (if
   ``LIVEAVATAR_ENABLED_AGENTS`` is set) ``agent_name`` appears there.
3. Otherwise → deny.

# TODO Q-tenant — Owner: Jesús.
#   Replace the env allowlist with the authoritative program flag location
#   once agreed.  Candidates:
#     a) A ``liveavatar_enabled`` column on the Navigator program/tenant table.
#     b) A NavConfig key per tenant (e.g. ``programs.<id>.avatar.enabled``).
#     c) An external feature-flag service (LaunchDarkly / GrowthBook).
#   The ``is_avatar_enabled`` interface is stable — only the backing store
#   changes.  No callers need updating.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

_logger = logging.getLogger("Parrot.AvatarOptIn")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def is_avatar_enabled(
    *,
    tenant_id: Optional[str],
    agent_name: Optional[str] = None,
) -> bool:
    """Return ``True`` iff avatar mode is enabled for the given tenant + agent.

    Default-deny: any unresolvable or unknown input returns ``False``.

    Args:
        tenant_id: Identifier for the tenant/program requesting avatar mode.
            ``None`` or empty string → deny (cannot resolve to any allowlist
            entry).
        agent_name: Optional agent slug to match against
            ``LIVEAVATAR_ENABLED_AGENTS``.  When the env var is not set, any
            agent name is accepted for an enabled tenant.

    Returns:
        ``True`` if the tenant (and optionally the agent) is opted-in.
        ``False`` in all other cases.

    # TODO Q-tenant — replace body with authoritative flag lookup once the
    #   program DB column / NavConfig key / feature-flag service is agreed.
    """
    if not tenant_id:
        _logger.debug("AvatarOptIn: tenant_id is empty — default-deny")
        return False

    enabled_tenants_raw = os.environ.get("LIVEAVATAR_ENABLED_TENANTS", "").strip()
    if not enabled_tenants_raw:
        _logger.debug(
            "AvatarOptIn: LIVEAVATAR_ENABLED_TENANTS not set — default-deny"
        )
        return False

    enabled_tenants = {t.strip() for t in enabled_tenants_raw.split(",") if t.strip()}

    # Wildcard: all tenants allowed
    if "*" not in enabled_tenants and tenant_id not in enabled_tenants:
        _logger.debug(
            "AvatarOptIn: tenant %r not in allowlist — deny", tenant_id
        )
        return False

    # Optionally gate on agent name as well
    enabled_agents_raw = os.environ.get("LIVEAVATAR_ENABLED_AGENTS", "").strip()
    if enabled_agents_raw and agent_name:
        enabled_agents = {
            a.strip() for a in enabled_agents_raw.split(",") if a.strip()
        }
        if agent_name not in enabled_agents:
            _logger.debug(
                "AvatarOptIn: agent %r not in agent allowlist — deny",
                agent_name,
            )
            return False

    _logger.debug(
        "AvatarOptIn: tenant %r / agent %r → allowed", tenant_id, agent_name
    )
    return True
