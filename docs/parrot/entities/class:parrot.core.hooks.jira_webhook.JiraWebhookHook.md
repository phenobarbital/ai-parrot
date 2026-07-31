---
type: Wiki Entity
title: JiraWebhookHook
id: class:parrot.core.hooks.jira_webhook.JiraWebhookHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Receives Jira webhook POST requests via an aiohttp route.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# JiraWebhookHook

Defined in [`parrot.core.hooks.jira_webhook`](../summaries/mod:parrot.core.hooks.jira_webhook.md).

```python
class JiraWebhookHook(BaseHook)
```

Receives Jira webhook POST requests via an aiohttp route.

Validates HMAC signatures when a secret token is configured.
Parses issue events (created, updated, closed, deleted) and
emits HookEvents.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
- `def setup_routes(self, app: Any) -> None`
