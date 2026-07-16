---
type: Wiki Entity
title: ConversationalRollout
id: class:parrot.eval.rollout.ConversationalRollout
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-turn rollout that loops ``bot.conversation()`` against a simulator.
relates_to:
- concept: class:parrot.eval.rollout.RolloutStrategy
  rel: extends
---

# ConversationalRollout

Defined in [`parrot.eval.rollout`](../summaries/mod:parrot.eval.rollout.md).

```python
class ConversationalRollout(RolloutStrategy)
```

Multi-turn rollout that loops ``bot.conversation()`` against a simulator.

The conversation continues until the simulator returns ``None`` or
``max_turns`` is reached.

Args:
    user_sim: ``UserSimulator`` that generates user-side turns.
    max_turns: Maximum number of agent turns before giving up.

## Methods

- `async def run(self, bot: 'AbstractBot', task: EvalTask, sandbox: Sandbox) -> Trajectory` — Drive a multi-turn conversation until completion or max_turns.
