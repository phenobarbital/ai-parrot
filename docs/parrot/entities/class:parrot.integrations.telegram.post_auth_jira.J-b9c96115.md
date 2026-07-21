---
type: Wiki Entity
title: JiraPostAuthProvider
id: class:parrot.integrations.telegram.post_auth_jira.JiraPostAuthProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Secondary auth provider for Atlassian Jira (OAuth2 3LO).
---

# JiraPostAuthProvider

Defined in [`parrot.integrations.telegram.post_auth_jira`](../summaries/mod:parrot.integrations.telegram.post_auth_jira.md).

```python
class JiraPostAuthProvider
```

Secondary auth provider for Atlassian Jira (OAuth2 3LO).

Args:
    oauth_manager: Pre-configured :class:`JiraOAuthManager` (typically
        obtained from ``app["jira_oauth_manager"]``).
    identity_service: :class:`IdentityMappingService` for writing
        ``auth.user_identities`` rows.
    vault_sync: :class:`VaultTokenSync` for encrypted token persistence.

## Methods

- `async def build_auth_url(self, session: 'TelegramUserSession', config: 'TelegramAgentConfig', callback_base_url: str) -> str` — Return a Jira authorization URL with BasicAuth state embedded.
- `async def handle_result(self, data: Dict[str, Any], session: 'TelegramUserSession', primary_auth_data: Dict[str, Any]) -> bool` — Exchange the Jira code and persist tokens + identities.
