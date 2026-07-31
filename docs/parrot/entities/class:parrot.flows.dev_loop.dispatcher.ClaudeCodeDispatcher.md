---
type: Wiki Entity
title: ClaudeCodeDispatcher
id: class:parrot.flows.dev_loop.dispatcher.ClaudeCodeDispatcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Thin orchestration class over :class:`ClaudeAgentClient`.
---

# ClaudeCodeDispatcher

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class ClaudeCodeDispatcher
```

Thin orchestration class over :class:`ClaudeAgentClient`.

A single dispatcher instance is meant to be shared by every node in a
flow: it owns the global concurrency cap and the Redis connection.

## Methods

- `async def dispatch(self, *, brief: BaseModel, profile: ClaudeCodeDispatchProfile, output_model: Type[T], run_id: str, node_id: str, cwd: str) -> T` — Dispatch a single Claude Code session and return its parsed output.
