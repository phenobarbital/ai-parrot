---
type: Concept
title: is_avatar_enabled()
id: func:parrot.integrations.liveavatar.optin.is_avatar_enabled
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return ``True`` iff avatar mode is enabled for the given tenant + agent.
---

# is_avatar_enabled

```python
def is_avatar_enabled(*, tenant_id: Optional[str], agent_name: Optional[str]=None) -> bool
```

Return ``True`` iff avatar mode is enabled for the given tenant + agent.

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
