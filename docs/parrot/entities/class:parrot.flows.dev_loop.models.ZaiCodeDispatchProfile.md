---
type: Wiki Entity
title: ZaiCodeDispatchProfile
id: class:parrot.flows.dev_loop.models.ZaiCodeDispatchProfile
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.
relates_to:
- concept: class:parrot.flows.dev_loop.models.LLMCodeDispatchProfile
  rel: extends
---

# ZaiCodeDispatchProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class ZaiCodeDispatchProfile(LLMCodeDispatchProfile)
```

Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.

Subclasses ``LLMCodeDispatchProfile`` so it flows through the inherited
dispatch loop unchanged; Z.ai-native fields (``enable_thinking``,
``reasoning_effort``) are consumed by
``ZaiCodeDispatcher._completion_args`` instead of the Nvidia-style
``extra_body.chat_template_kwargs`` block used by the base class.
