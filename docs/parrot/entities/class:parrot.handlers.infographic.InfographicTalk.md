---
type: Wiki Entity
title: InfographicTalk
id: class:parrot.handlers.infographic.InfographicTalk
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dedicated HTTP handler for bot.get_infographic() plus template/theme
relates_to:
- concept: class:parrot.handlers.agent.AgentTalk
  rel: extends
---

# InfographicTalk

Defined in [`parrot.handlers.infographic`](../summaries/mod:parrot.handlers.infographic.md).

```python
class InfographicTalk(AgentTalk)
```

Dedicated HTTP handler for bot.get_infographic() plus template/theme
discovery and registration endpoints.

Inherits from AgentTalk to reuse authentication decorators, PBAC guards
(``_check_pbac_agent_access``), agent lookup (``_get_agent``), and session
management (``_get_user_session``).

Content negotiation:
    Priority order — ``?format=`` query param > ``Accept`` header >
    default ``text/html``.

## Methods

- `def post_init(self, *args, **kwargs) -> None` — Initialise logger for this handler.
- `async def post(self) -> web.Response` — Dispatch POST requests.
- `async def get(self) -> web.Response` — Dispatch GET requests.
