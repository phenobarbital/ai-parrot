---
type: Wiki Entity
title: AbstractToolExecutor
id: class:parrot.tools.executors.abstract.AbstractToolExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pluggable transport that runs a tool somewhere other than here.
---

# AbstractToolExecutor

Defined in [`parrot.tools.executors.abstract`](../summaries/mod:parrot.tools.executors.abstract.md).

```python
class AbstractToolExecutor(ABC)
```

Pluggable transport that runs a tool somewhere other than here.

Concrete executors translate a :class:`ToolExecutionEnvelope` into
whatever protocol the remote runtime speaks (HTTP, gRPC, k8s API,
Redis Streams, etc.) and return a :class:`ToolResult` once the
remote side finishes — either by waiting synchronously up to
``envelope.timeout_seconds`` or by returning a ``pending``
ToolResult and arranging for the final result to arrive via webhook.

Concrete implementations:

* :class:`LocalToolExecutor` — in-process; reference / tests
* :class:`K8sToolExecutor` — ephemeral Pod via kubernetes-asyncio
* :class:`QworkerToolExecutor` — Qworker service (HTTP / Redis)

## Methods

- `async def execute(self, envelope: ToolExecutionEnvelope) -> 'ToolResult'` — Run the tool described by *envelope* and return its ToolResult.
- `async def close(self) -> None` — Release any pooled resources (HTTP sessions, k8s clients, etc.).
