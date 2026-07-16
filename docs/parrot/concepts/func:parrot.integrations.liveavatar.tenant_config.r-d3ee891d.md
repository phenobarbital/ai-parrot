---
type: Concept
title: resolve_fullmode_config()
id: func:parrot.integrations.liveavatar.tenant_config.resolve_fullmode_config
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolve a :class:`FullModeConfig` from env defaults (+ future DB overrides).
---

# resolve_fullmode_config

```python
async def resolve_fullmode_config(tenant_id: Optional[str]=None) -> FullModeConfig
```

Resolve a :class:`FullModeConfig` from env defaults (+ future DB overrides).

Declared ``async`` so call sites do not need breaking changes when a real
DB ``await`` is added to the DB-override layer (TODO Q-tenant-config-store).

Resolution order:
1. (Future) Per-tenant DB overrides via a tenant config store —
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
