---
type: Wiki Entity
title: LLMCodeDispatcher
id: class:parrot.flows.dev_loop.dispatcher.LLMCodeDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Local coding-agent loop for OpenAI-compatible LLM clients.
---

# LLMCodeDispatcher

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class LLMCodeDispatcher
```

Local coding-agent loop for OpenAI-compatible LLM clients.

CLI-backed dispatchers delegate filesystem and command execution to their
external runtime. This dispatcher keeps that runtime in-process: the model
receives a small OpenAI-style tool surface, every tool is cwd-confined, and
the final payload is validated against the requested Pydantic model.

## Methods

- `async def dispatch(self, *, brief: BaseModel, profile: LLMCodeDispatchProfile, output_model: Type[T], run_id: str, node_id: str, cwd: str) -> T`
