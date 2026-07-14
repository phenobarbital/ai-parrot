---
type: Wiki Entity
title: ComponentContractError
id: class:parrot.outputs.a2ui.catalog.base.ComponentContractError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when a component class violates the registration contract.
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.base.CatalogError
  rel: extends
---

# ComponentContractError

Defined in [`parrot.outputs.a2ui.catalog.base`](../summaries/mod:parrot.outputs.a2ui.catalog.base.md).

```python
class ComponentContractError(CatalogError)
```

Raised when a component class violates the registration contract.

The canonical trigger is a missing/uncallable ``lower()`` — a component
cannot register without a lowering (spec G4, enforced not conventional).
