---
type: Wiki Entity
title: RolloutStrategy
id: class:parrot.eval.rollout.RolloutStrategy
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract strategy for driving an agent through a task.
---

# RolloutStrategy

Defined in [`parrot.eval.rollout`](../summaries/mod:parrot.eval.rollout.md).

```python
class RolloutStrategy(ABC)
```

Abstract strategy for driving an agent through a task.

A rollout strategy calls ``bot.ask()`` or ``bot.conversation()`` and
records the resulting ``Trajectory``.

## Methods

- `async def run(self, bot: 'AbstractBot', task: EvalTask, sandbox: Sandbox) -> Trajectory` — Drive *bot* through *task* in *sandbox* and return the trajectory.
