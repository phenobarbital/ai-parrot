---
type: Wiki Summary
title: parrot.integrations.liveavatar.tenant_config
id: mod:parrot.integrations.liveavatar.tenant_config
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-tenant FULL mode configuration resolver (FEAT-248 — Module 3).
relates_to:
- concept: func:parrot.integrations.liveavatar.tenant_config.resolve_fullmode_config
  rel: defines
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
---

# `parrot.integrations.liveavatar.tenant_config`

Per-tenant FULL mode configuration resolver (FEAT-248 — Module 3).

Provides ``resolve_fullmode_config(tenant_id) -> FullModeConfig``, the single
public interface for resolving a fully-populated :class:`FullModeConfig` for a
given tenant.

Resolution order (first match wins):
1. (Future) Per-tenant DB overrides via a tenant config store —
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

## Functions

- `async def resolve_fullmode_config(tenant_id: Optional[str]=None) -> FullModeConfig` — Resolve a :class:`FullModeConfig` from env defaults (+ future DB overrides).
