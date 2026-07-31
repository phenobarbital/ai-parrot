---
type: Wiki Entity
title: LocalToolExecutor
id: class:parrot.tools.executors.local.LocalToolExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Executor that runs the tool in the current Python process.
relates_to:
- concept: class:parrot.tools.executors.abstract.AbstractToolExecutor
  rel: extends
---

# LocalToolExecutor

Defined in [`parrot.tools.executors.local`](../summaries/mod:parrot.tools.executors.local.md).

```python
class LocalToolExecutor(AbstractToolExecutor)
```

Executor that runs the tool in the current Python process.

Used as the reference implementation: it imports the tool by path,
instantiates it from ``envelope.tool_init_kwargs``, and awaits its
``_execute(**envelope.arguments)``. Because it shares the runner
module with the worker entrypoint, this is what the
``K8sToolExecutor`` worker pod ends up doing inside its own
process — and what unit tests can exercise without ceremony.

## Methods

- `async def execute(self, envelope: ToolExecutionEnvelope) -> 'ToolResult'`
- `async def close(self) -> None`
