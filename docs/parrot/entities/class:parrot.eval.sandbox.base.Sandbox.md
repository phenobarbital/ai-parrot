---
type: Wiki Entity
title: Sandbox
id: class:parrot.eval.sandbox.base.Sandbox
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract execution environment for agent evaluation.
---

# Sandbox

Defined in [`parrot.eval.sandbox.base`](../summaries/mod:parrot.eval.sandbox.base.md).

```python
class Sandbox(ABC)
```

Abstract execution environment for agent evaluation.

Sandboxes are used as async context managers so the runner can bracket
the lifecycle cleanly:

    async with sandbox:
        await sandbox.reset(seed_state)
        bot = await agent_factory(sandbox)
        trajectory = await rollout.run(bot, task, sandbox)
        state = await sandbox.snapshot()

Subclasses provide concrete isolation strategies (in-memory, Docker, …).

## Methods

- `async def reset(self, seed_state: dict[str, Any] | None) -> None` — Reset the sandbox to a known state.
- `async def health_check(self) -> bool` — Check whether the sandbox is operational.
- `async def snapshot(self) -> dict[str, Any]` — Capture a deterministic snapshot of the current world state.
- `async def exec(self, cmd: list[str]) -> ExecResult` — Execute a shell command inside the sandbox.
