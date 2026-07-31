---
type: Wiki Entity
title: GitHubWebhookConfig
id: class:parrot.core.hooks.models.GitHubWebhookConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for GitHub webhook receiver.
---

# GitHubWebhookConfig

Defined in [`parrot.core.hooks.models`](../summaries/mod:parrot.core.hooks.models.md).

```python
class GitHubWebhookConfig(BaseModel)
```

Configuration for GitHub webhook receiver.

Used by :class:`parrot.core.hooks.github_webhook.GitHubWebhookHook` to
register an aiohttp route that accepts ``pull_request`` deliveries from
GitHub. ``secret_token`` enables HMAC-SHA256 signature verification on
the ``X-Hub-Signature-256`` header.
