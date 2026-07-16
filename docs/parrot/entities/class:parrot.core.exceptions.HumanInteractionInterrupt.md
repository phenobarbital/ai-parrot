---
type: Wiki Entity
title: HumanInteractionInterrupt
id: class:parrot.core.exceptions.HumanInteractionInterrupt
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when an agent tool requests human interaction to continue.
relates_to:
- concept: class:parrot.exceptions.ParrotError
  rel: extends
---

# HumanInteractionInterrupt

Defined in [`parrot.core.exceptions`](../summaries/mod:parrot.core.exceptions.md).

```python
class HumanInteractionInterrupt(ParrotError)
```

Raised when an agent tool requests human interaction to continue.

This interrupt is meant to be caught by the orchestrator so it can suspend
the current execution state and propagate the prompt out to the user via
a chat integration.
