---
type: Wiki Entity
title: LLMUserSimulator
id: class:parrot.eval.rollout.LLMUserSimulator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: User simulator backed by an LLM (``AbstractClient.ask()``).
relates_to:
- concept: class:parrot.eval.rollout.UserSimulator
  rel: extends
---

# LLMUserSimulator

Defined in [`parrot.eval.rollout`](../summaries/mod:parrot.eval.rollout.md).

```python
class LLMUserSimulator(UserSimulator)
```

User simulator backed by an LLM (``AbstractClient.ask()``).

Sends the scenario + conversation history to the model and asks it to
generate the next user turn.  Uses ``temperature=0`` for reproducibility
(spec D6).

A ``None`` return from the model (or any response that looks like an
end-of-task signal) stops the conversational rollout.

Args:
    client: ``AbstractClient`` instance to use for turn generation.
        Must NOT be the same model-under-test.
    system_prompt: Optional system prompt.  Defaults to a sensible
        user-simulation instruction.

## Methods

- `async def respond(self, conversation: list[TurnRecord], scenario: str) -> str | None` — Generate the next user utterance via the client.
