---
type: Wiki Entity
title: IntegrationDescriptor
id: class:parrot.auth.oauth2.models.IntegrationDescriptor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Describes one OAuth2-capable integration for the menu listing.
---

# IntegrationDescriptor

Defined in [`parrot.auth.oauth2.models`](../summaries/mod:parrot.auth.oauth2.models.md).

```python
class IntegrationDescriptor(BaseModel)
```

Describes one OAuth2-capable integration for the menu listing.

Attributes:
    provider: Provider identifier, e.g. ``"jira"``.
    display_name: Human-readable name, e.g. ``"Jira"``.
    icon: Icon identifier (Material Design Icons key) or URL.
    default_scopes: Scopes requested during the OAuth consent screen.
    connected: Whether the current user has a ``users_integrations`` row.
    enabled_on_agent: Whether the user has a ``user_agent_toolkits`` row
        for the current ``(user, agent)`` pair.
    account_id: Provider-side account identifier (available when connected).
    display_account_name: Human-readable account name.
    email: Account email (if the provider exposes it).
    connected_at: Timestamp when the credential was first stored.
