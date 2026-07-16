---
type: Wiki Entity
title: SlackAgentWrapper
id: class:parrot.integrations.slack.wrapper.SlackAgentWrapper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wrap an AI-Parrot agent for Slack Events and slash commands.
---

# SlackAgentWrapper

Defined in [`parrot.integrations.slack.wrapper`](../summaries/mod:parrot.integrations.slack.wrapper.md).

```python
class SlackAgentWrapper
```

Wrap an AI-Parrot agent for Slack Events and slash commands.

Features:
- HMAC-SHA256 signature verification
- Event deduplication to prevent duplicate processing
- Async background processing (returns HTTP 200 immediately)
- Concurrency limiting via semaphore
- Retry header detection (ignores Slack retries)

## Methods

- `async def start(self) -> None` — Start the deduplication cleanup task.
- `async def stop(self) -> None` — Stop background tasks and cleanup.
