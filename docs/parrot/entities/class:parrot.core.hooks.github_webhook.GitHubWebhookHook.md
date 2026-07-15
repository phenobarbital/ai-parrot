---
type: Wiki Entity
title: GitHubWebhookHook
id: class:parrot.core.hooks.github_webhook.GitHubWebhookHook
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Receives GitHub webhook POST requests via an aiohttp route.
relates_to:
- concept: class:parrot.core.hooks.base.BaseHook
  rel: extends
---

# GitHubWebhookHook

Defined in [`parrot.core.hooks.github_webhook`](../summaries/mod:parrot.core.hooks.github_webhook.md).

```python
class GitHubWebhookHook(BaseHook)
```

Receives GitHub webhook POST requests via an aiohttp route.

Validates HMAC-SHA256 signatures when a secret token is configured.
Parses ``pull_request`` events (opened, reopened, synchronize) and
emits :class:`HookEvent` instances tagged ``github.pr_<action>``.

Other event types (issues, push, …) and other ``pull_request`` actions
(closed, edited, labeled, …) are ignored with a 200 response so GitHub
does not back off the webhook delivery.

## Methods

- `async def start(self) -> None`
- `async def stop(self) -> None`
- `def setup_routes(self, app: Any) -> None`
