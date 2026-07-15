---
type: Wiki Entity
title: UsersIntegrationRow
id: class:parrot.auth.oauth2.models.UsersIntegrationRow
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Durable credential record stored in the ``users_integrations`` collection.
---

# UsersIntegrationRow

Defined in [`parrot.auth.oauth2.models`](../summaries/mod:parrot.auth.oauth2.models.md).

```python
class UsersIntegrationRow(BaseModel)
```

Durable credential record stored in the ``users_integrations`` collection.

The composite key is ``(user_id, provider)``.

Attributes:
    user_id: Navigator user identifier.
    provider: Provider identifier, e.g. ``"jira"``.
    channel: Origin channel — always ``"web"`` for this integration path.
    status: ``"active"`` while the credential is usable; ``"revoked"`` after
        explicit disconnect (soft-delete variant, not used in v1 — v1 does
        hard deletes).
    account_id: Provider-side account ID (e.g. Atlassian ``accountId``).
    display_name: Human-readable account name.
    email: Account email.
    scopes: Scopes granted during consent.
    cloud_id: Atlassian cloud ID (Jira-specific).
    site_url: Atlassian site URL.
    connected_at: When the credential was first stored.
    last_used_at: When the credential was last used (updated by the toolkit).
