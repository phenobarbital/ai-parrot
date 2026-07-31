---
type: Wiki Entity
title: CodexCodeDispatcher
id: class:parrot.flows.dev_loop.dispatcher.CodexCodeDispatcher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Thin orchestration class over ``codex exec --json``.
---

# CodexCodeDispatcher

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class CodexCodeDispatcher
```

Thin orchestration class over ``codex exec --json``.

The class mirrors the public ``dispatch`` contract of
:class:`ClaudeCodeDispatcher` so Development can choose a coding-agent
backend without changing the dev-loop graph.

## Methods

- `async def dispatch(self, *, brief: BaseModel, profile: CodexCodeDispatchProfile, output_model: Type[T], run_id: str, node_id: str, cwd: str) -> T` — Dispatch a single Codex CLI session and return parsed output.
