---
type: Wiki Entity
title: GeminiCodeReviewProfile
id: class:parrot.flows.dev_loop.models.GeminiCodeReviewProfile
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Review profile for the Gemini code review dispatcher (FEAT-270).
relates_to:
- concept: class:parrot.flows.dev_loop.models.GeminiCodeDispatchProfile
  rel: extends
---

# GeminiCodeReviewProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class GeminiCodeReviewProfile(GeminiCodeDispatchProfile)
```

Review profile for the Gemini code review dispatcher (FEAT-270).

Inherits ``GeminiCodeDispatchProfile`` so it carries the fields that
``GeminiCodeDispatcher._build_command()`` accesses. Overrides defaults
for the write-enabled review use case.
