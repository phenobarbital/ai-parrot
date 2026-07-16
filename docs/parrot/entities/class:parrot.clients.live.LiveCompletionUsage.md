---
type: Wiki Entity
title: LiveCompletionUsage
id: class:parrot.clients.live.LiveCompletionUsage
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Usage tracking for Gemini Live API responses.
---

# LiveCompletionUsage

Defined in [`parrot.clients.live`](../summaries/mod:parrot.clients.live.md).

```python
class LiveCompletionUsage
```

Usage tracking for Gemini Live API responses.

Compatible with CompletionUsage from parrot.models.basic

## Methods

- `def from_gemini_usage(cls, usage_metadata: Any) -> 'LiveCompletionUsage'` — Create from Gemini usage metadata when available.
