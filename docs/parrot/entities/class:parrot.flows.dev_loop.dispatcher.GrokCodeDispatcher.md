---
type: Wiki Entity
title: GrokCodeDispatcher
id: class:parrot.flows.dev_loop.dispatcher.GrokCodeDispatcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Local coding-agent loop tailored for Grok client and Grok Build model.
relates_to:
- concept: class:parrot.flows.dev_loop.dispatcher.LLMCodeDispatcher
  rel: extends
---

# GrokCodeDispatcher

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class GrokCodeDispatcher(LLMCodeDispatcher)
```

Local coding-agent loop tailored for Grok client and Grok Build model.

Extends LLMCodeDispatcher to leverage the local OpenAI-compatible tool loop
while binding to the custom `GrokClient` via LLMFactory and xAI SDK.

## Methods

- `async def dispatch(self, *, brief: BaseModel, profile: GrokCodeDispatchProfile, output_model: Type[T], run_id: str, node_id: str, cwd: str) -> T`
