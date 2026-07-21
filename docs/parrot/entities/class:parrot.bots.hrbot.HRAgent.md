---
type: Wiki Entity
title: HRAgent
id: class:parrot.bots.hrbot.HRAgent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Represents an Human Resources agent in Navigator.
relates_to:
- concept: class:parrot.bots.chatbot.Chatbot
  rel: extends
---

# HRAgent

Defined in [`parrot.bots.hrbot`](../summaries/mod:parrot.bots.hrbot.md).

```python
class HRAgent(Chatbot)
```

Represents an Human Resources agent in Navigator.

Each agent has a name, a role, a goal, a backstory,
and an optional language model (llm).
