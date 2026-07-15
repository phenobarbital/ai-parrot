---
type: Wiki Entity
title: AbstractFormService
id: class:parrot_formdesigner.tools.services.abstract.AbstractFormService
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Strategy interface for sourcing a FormSchema from any origin.
---

# AbstractFormService

Defined in [`parrot_formdesigner.tools.services.abstract`](../summaries/mod:parrot_formdesigner.tools.services.abstract.md).

```python
class AbstractFormService(ABC)
```

Strategy interface for sourcing a FormSchema from any origin.

Subclasses implement two methods:

- ``fetch(*, formid, orgid, **kwargs)`` — retrieve raw data (DB row, REST
  payload, …). All parameters are keyword-only.
- ``to_form_schema(raw)``               — translate raw data into a FormSchema.

Splitting fetch from mapping keeps the schema-mapping logic testable
without I/O. The FormRegistry coupling stays in DatabaseFormTool — the
service must not call registry.register() itself.

## Methods

- `async def fetch(self, **params: Any) -> dict[str, Any]` — Fetch raw form data from the underlying source.
- `def to_form_schema(self, raw: dict[str, Any]) -> FormSchema` — Translate the raw payload into a canonical FormSchema.
