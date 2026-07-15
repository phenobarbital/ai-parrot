---
type: Wiki Entity
title: MSTeamsOAuthNotifier
id: class:parrot.integrations.msteams.oauth_callback.MSTeamsOAuthNotifier
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Send a proactive message to a Teams user after a successful Jira OAuth callback.
---

# MSTeamsOAuthNotifier

Defined in [`parrot.integrations.msteams.oauth_callback`](../summaries/mod:parrot.integrations.msteams.oauth_callback.md).

```python
class MSTeamsOAuthNotifier
```

Send a proactive message to a Teams user after a successful Jira OAuth callback.

Uses ``adapter.continue_conversation`` from the Bot Framework to push a
confirmation into the existing 1:1 conversation.

Args:
    adapter: The Bot Framework adapter (from :class:`MSTeamsAgentWrapper`).
    app_id: The Microsoft App ID (``MSTeamsAgentConfig.client_id``).

## Methods

- `async def notify_connected(self, conversation_ref_dict: Dict[str, Any], display_name: str, site_url: str) -> None` — Send a proactive "connected" message to the Teams conversation.
- `async def notify_failure(self, conversation_ref_dict: Dict[str, Any], reason: str) -> None` — Send a proactive error message to the Teams conversation.
