---
type: Wiki Entity
title: DevLoopCodeDispatcher
id: class:parrot.flows.dev_loop.dispatcher.DevLoopCodeDispatcher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Shared dispatch contract consumed by dev-loop code-agent nodes.
---

# DevLoopCodeDispatcher

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class DevLoopCodeDispatcher(Protocol)
```

Shared dispatch contract consumed by dev-loop code-agent nodes.

## Methods

- `async def dispatch(self, *, brief: BaseModel, profile: BaseModel, output_model: Type[T], run_id: str, node_id: str, cwd: str) -> T` — Dispatch a code-agent run and return validated structured output.
