---
type: Wiki Entity
title: ProvisioningRecord
id: class:parrot.bots.factory.contracts.ProvisioningRecord
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Side-effect produced by a builder while drafting the definition.
---

# ProvisioningRecord

Defined in [`parrot.bots.factory.contracts`](../summaries/mod:parrot.bots.factory.contracts.md).

```python
class ProvisioningRecord(BaseModel)
```

Side-effect produced by a builder while drafting the definition.

Builders may provision a vector store, register an OpenAPI toolkit, etc.
These records let the orchestrator report what was done and, if the user
cancels at pre-finalize, surface the items that may need cleanup.
