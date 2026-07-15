---
type: Wiki Entity
title: CatalogValidationError
id: class:parrot.outputs.a2ui.catalog.base.CatalogValidationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when an envelope fails catalog allowlist / ``requires_actions`` checks.
relates_to:
- concept: class:parrot.outputs.a2ui.catalog.base.CatalogError
  rel: extends
---

# CatalogValidationError

Defined in [`parrot.outputs.a2ui.catalog.base`](../summaries/mod:parrot.outputs.a2ui.catalog.base.md).

```python
class CatalogValidationError(CatalogError)
```

Raised when an envelope fails catalog allowlist / ``requires_actions`` checks.

Attributes:
    unknown_components: Component names not present in the catalog.
    action_components: Action-bearing component names rejected for an
        LLM-produced envelope.
