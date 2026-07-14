---
type: Wiki Entity
title: JiraOAuth2Provider
id: class:parrot.auth.oauth2.jira_provider.JiraOAuth2Provider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: OAuth2 provider for Atlassian Jira Cloud (3LO flow).
relates_to:
- concept: class:parrot.auth.oauth2.registry.OAuth2Provider
  rel: extends
---

# JiraOAuth2Provider

Defined in [`parrot.auth.oauth2.jira_provider`](../summaries/mod:parrot.auth.oauth2.jira_provider.md).

```python
class JiraOAuth2Provider(OAuth2Provider)
```

OAuth2 provider for Atlassian Jira Cloud (3LO flow).

This provider thin-wraps the existing :class:`~parrot.auth.jira_oauth.JiraOAuthManager`
and :class:`~parrot_tools.jiratoolkit.JiraToolkit`.

Register it at application startup once the ``JiraOAuthManager`` is
available::

    register_oauth2_provider(JiraOAuth2Provider(manager=jira_oauth_manager))

Attributes:
    provider_id: Always ``"jira"``.
    display_name: Always ``"Jira"``.
    icon: Material Design Icon key ``"mdi:jira"``.
    default_scopes: Standard Jira read/write + offline_access scopes.
    pbac_action_namespace: ``"integration"``.

## Methods

- `def manager(self) -> 'JiraOAuthManager'` — Return the underlying :class:`~parrot.auth.jira_oauth.JiraOAuthManager`.
- `def toolkit_factory(self, credential_resolver: 'CredentialResolver') -> '_JiraToolkit'` — Build a fresh :class:`~parrot_tools.jiratoolkit.JiraToolkit` bound to
