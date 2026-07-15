---
type: Wiki Entity
title: OperationSpecInput
id: class:parrot.tools.working_memory.models.OperationSpecInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative operation specification — the DSL contract.
---

# OperationSpecInput

Defined in [`parrot.tools.working_memory.models`](../summaries/mod:parrot.tools.working_memory.models.md).

```python
class OperationSpecInput(BaseModel)
```

Declarative operation specification — the DSL contract.

The agent sends this as JSON; Pydantic validates it before execution.
No free-form code allowed.
