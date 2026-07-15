---
type: Wiki Entity
title: LLMCodeDispatchProfile
id: class:parrot.flows.dev_loop.models.LLMCodeDispatchProfile
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative profile consumed by ``LLMCodeDispatcher.dispatch()``.
---

# LLMCodeDispatchProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class LLMCodeDispatchProfile(BaseModel)
```

Declarative profile consumed by ``LLMCodeDispatcher.dispatch()``.

This profile targets OpenAI-compatible ``AbstractClient`` implementations
via ``LLMFactory``. The dispatcher supplies the coding-agent loop locally,
so the model only needs standard chat/tool-calling support.
