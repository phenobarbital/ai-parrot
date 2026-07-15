---
type: Wiki Entity
title: DispatchExecutionError
id: class:parrot.flows.dev_loop.dispatcher.DispatchExecutionError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when the Claude Code session fails before producing a result.
---

# DispatchExecutionError

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class DispatchExecutionError(Exception)
```

Raised when the Claude Code session fails before producing a result.

Wraps any exception raised by ``ClaudeAgentClient.ask_stream`` plus
misconfiguration errors caught before SDK invocation (e.g.
``cwd`` outside ``WORKTREE_BASE_PATH``).
