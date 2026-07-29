---
type: Wiki Entity
title: MSTeamsHook
id: class:parrot.core.hooks.messaging.MSTeamsHook
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Receives MS Teams Activity POSTs via Bot Framework webhook.
---

# MSTeamsHook

Defined in [`parrot.core.hooks.messaging`](../summaries/mod:parrot.core.hooks.messaging.md).

```python
class MSTeamsHook(_MessagingHookBase)
```

Receives MS Teams Activity POSTs via Bot Framework webhook.

Parses the incoming Activity JSON, extracts the message text,
applies filters, and emits a HookEvent.  For full bidirectional
Teams integration, use ``MSTeamsAgentWrapper`` instead.

## Methods

- `def setup_routes(self, app: Any) -> None`
