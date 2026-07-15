---
type: Wiki Entity
title: ZaiCodeDispatcher
id: class:parrot.flows.dev_loop.dispatcher.ZaiCodeDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Local coding-agent loop bound to ``ZaiClient`` / GLM-5.2.
relates_to:
- concept: class:parrot.flows.dev_loop.dispatcher.LLMCodeDispatcher
  rel: extends
---

# ZaiCodeDispatcher

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class ZaiCodeDispatcher(LLMCodeDispatcher)
```

Local coding-agent loop bound to ``ZaiClient`` / GLM-5.2.

Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop,
Redis event streaming, cwd-safety guard, and output validation, while
overriding the completion-args and chat-completion hooks so requests
carry Z.ai-native ``thinking``/``reasoning_effort`` parameters instead
of the Nvidia-style ``extra_body.chat_template_kwargs`` block emitted
by the base class.

## Methods

- `async def dispatch(self, *, brief: BaseModel, profile: ZaiCodeDispatchProfile, output_model: Type[T], run_id: str, node_id: str, cwd: str) -> T`
