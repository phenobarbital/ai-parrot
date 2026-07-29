---
type: Wiki Entity
title: FactoryResult
id: class:parrot.bots.factory.contracts.FactoryResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Terminal output of an orchestrator run.
---

# FactoryResult

Defined in [`parrot.bots.factory.contracts`](../summaries/mod:parrot.bots.factory.contracts.md).

```python
class FactoryResult(BaseModel)
```

Terminal output of an orchestrator run.

``definition`` and ``yaml_path`` are populated only when ``status`` is
``SUCCESS``. ``cancelled_at`` records which HITL checkpoint the user
bailed at, so the handler/CLI can show a meaningful message.
