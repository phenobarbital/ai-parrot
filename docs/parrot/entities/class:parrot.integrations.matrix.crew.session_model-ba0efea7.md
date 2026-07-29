---
type: Wiki Entity
title: SessionPhase
id: class:parrot.integrations.matrix.crew.session_models.SessionPhase
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase in the collaborative session lifecycle.
---

# SessionPhase

Defined in [`parrot.integrations.matrix.crew.session_models`](../summaries/mod:parrot.integrations.matrix.crew.session_models.md).

```python
class SessionPhase(str, Enum)
```

Phase in the collaborative session lifecycle.

Attributes:
    CREATED: Session created but not yet started.
    INVESTIGATING: All agents investigating the question in parallel.
    CROSS_POLLINATING: Agents refining answers using peers' findings.
    SYNTHESIZING: Dedicated summarizer agent producing the final answer.
    COMPLETED: Session finished successfully.
    FAILED: Session encountered an unrecoverable error.
