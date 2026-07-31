---
type: Wiki Summary
title: parrot.integrations.liveavatar.optin
id: mod:parrot.integrations.liveavatar.optin
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-tenant opt-in gating for LiveAvatar LITE mode (FEAT-242 Phase A — Module
  7).
relates_to:
- concept: func:parrot.integrations.liveavatar.optin.is_avatar_enabled
  rel: defines
- concept: func:parrot.integrations.liveavatar.optin.is_fullmode_enabled
  rel: defines
---

# `parrot.integrations.liveavatar.optin`

Per-tenant opt-in gating for LiveAvatar LITE mode (FEAT-242 Phase A — Module 7).

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

## Functions

- `def is_avatar_enabled(*, tenant_id: Optional[str], agent_name: Optional[str]=None) -> bool` — Return ``True`` iff avatar mode is enabled for the given tenant + agent.
- `def is_fullmode_enabled(*, tenant_id: Optional[str], agent_name: Optional[str]=None) -> bool` — Return ``True`` iff FULL mode avatar is enabled for the given tenant + agent.
