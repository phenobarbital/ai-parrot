---
type: Wiki Entity
title: PersistenceMixin
id: class:parrot.bots.flows.core.storage.persistence.PersistenceMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pluggable persistence for crew/flow execution results.
---

# PersistenceMixin

Defined in [`parrot.bots.flows.core.storage.persistence`](../summaries/mod:parrot.bots.flows.core.storage.persistence.md).

```python
class PersistenceMixin
```

Pluggable persistence for crew/flow execution results.

The mixin exposes three public async methods:
    - ``_save_result``    — fire-and-forget write (same public contract as before).
    - ``aclose``          — wait for in-flight tasks, release the backend.
    - ``__aenter__`` / ``__aexit__`` — async context-manager protocol.

Attributes:
    (All owned by the host class — accessed via getattr.)

## Methods

- `async def aclose(self) -> None` — Wait for all in-flight persist tasks, then release the storage backend.
