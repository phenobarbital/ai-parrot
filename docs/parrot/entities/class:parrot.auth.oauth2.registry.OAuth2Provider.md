---
type: Wiki Entity
title: OAuth2Provider
id: class:parrot.auth.oauth2.registry.OAuth2Provider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base class for an OAuth2-capable provider.
---

# OAuth2Provider

Defined in [`parrot.auth.oauth2.registry`](../summaries/mod:parrot.auth.oauth2.registry.md).

```python
class OAuth2Provider(ABC)
```

Abstract base class for an OAuth2-capable provider.

Concrete implementations (e.g. ``JiraOAuth2Provider``) declare their
provider metadata as class-level attributes and implement the two abstract
members.

Attributes:
    provider_id: Unique string key, e.g. ``"jira"``.
    display_name: Human-readable name shown in the UI, e.g. ``"Jira"``.
    icon: Icon identifier (Material Design Icons key) or URL.
    default_scopes: Scopes requested during the OAuth consent screen.
    pbac_action_namespace: PBAC action namespace for policy evaluation,
        e.g. ``"integration"``.

## Methods

- `def manager(self) -> Any` — Return the underlying OAuth manager (e.g. ``JiraOAuthManager``).
- `def toolkit_factory(self, credential_resolver: 'CredentialResolver') -> 'AbstractToolkit'` — Build a fresh toolkit instance bound to *credential_resolver*.
