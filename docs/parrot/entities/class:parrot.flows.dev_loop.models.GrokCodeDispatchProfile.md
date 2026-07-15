---
type: Wiki Entity
title: GrokCodeDispatchProfile
id: class:parrot.flows.dev_loop.models.GrokCodeDispatchProfile
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative profile consumed by ``GrokCodeDispatcher.dispatch()``.
---

# GrokCodeDispatchProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class GrokCodeDispatchProfile(BaseModel)
```

Declarative profile consumed by ``GrokCodeDispatcher.dispatch()``.

This profile targets Grok models. The dispatcher supplies the coding-agent
loop locally, so the model only needs standard chat/tool-calling support.
