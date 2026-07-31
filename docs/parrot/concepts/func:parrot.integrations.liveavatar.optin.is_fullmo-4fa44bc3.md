---
type: Concept
title: is_fullmode_enabled()
id: func:parrot.integrations.liveavatar.optin.is_fullmode_enabled
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return ``True`` iff FULL mode avatar is enabled for the given tenant + agent.
---

# is_fullmode_enabled

```python
def is_fullmode_enabled(*, tenant_id: Optional[str], agent_name: Optional[str]=None) -> bool
```

Return ``True`` iff FULL mode avatar is enabled for the given tenant + agent.

FULL mode opt-in is a superset of the base avatar opt-in:
1. ``is_avatar_enabled()`` must return ``True`` (base gate).
2. ``LIVEAVATAR_FULLMODE_ENABLED_TENANTS`` must allow the tenant.

Default-deny: if the base gate fails, or if
``LIVEAVATAR_FULLMODE_ENABLED_TENANTS`` is absent/empty, FULL mode is OFF.

Args:
    tenant_id: Identifier for the tenant/program requesting FULL mode.
        ``None`` or empty string → deny.
    agent_name: Optional agent slug forwarded to the base gate.

Returns:
    ``True`` if both the base avatar gate and the FULL mode gate allow
    the tenant.  ``False`` in all other cases.

Environment variables:
    ``LIVEAVATAR_FULLMODE_ENABLED_TENANTS``
        Comma-separated tenant allowlist (or ``"*"`` for all tenants).
        Absent or empty → default-deny for FULL mode.

# TODO Q-tenant — replace body with authoritative flag lookup once the
#   storage layer is agreed (same as is_avatar_enabled).
