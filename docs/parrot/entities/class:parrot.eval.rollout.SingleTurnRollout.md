---
type: Wiki Entity
title: SingleTurnRollout
id: class:parrot.eval.rollout.SingleTurnRollout
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'One-shot rollout: a single ``bot.ask()`` call.'
relates_to:
- concept: class:parrot.eval.rollout.RolloutStrategy
  rel: extends
---

# SingleTurnRollout

Defined in [`parrot.eval.rollout`](../summaries/mod:parrot.eval.rollout.md).

```python
class SingleTurnRollout(RolloutStrategy)
```

One-shot rollout: a single ``bot.ask()`` call.

Suitable for single-shot toolkit agents (e.g. "Do CRUD task X").
Records one ``TurnRecord`` (role=``"agent"``) with the bot's response.

## Methods

- `async def run(self, bot: 'AbstractBot', task: EvalTask, sandbox: Sandbox) -> Trajectory` — Execute a single ``bot.ask()`` call and return the trajectory.
