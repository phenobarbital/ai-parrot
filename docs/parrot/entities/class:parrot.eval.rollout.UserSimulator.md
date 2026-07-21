---
type: Wiki Entity
title: UserSimulator
id: class:parrot.eval.rollout.UserSimulator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract user-side simulator for conversational rollouts.
---

# UserSimulator

Defined in [`parrot.eval.rollout`](../summaries/mod:parrot.eval.rollout.md).

```python
class UserSimulator(ABC)
```

Abstract user-side simulator for conversational rollouts.

Generates the next user message given the current conversation history.
Returns ``None`` to signal that the task is complete or that the
simulator gives up.

## Methods

- `async def respond(self, conversation: list[TurnRecord], scenario: str) -> str | None` — Generate the next user utterance.
