---
type: Wiki Entity
title: NetworkninjaFormService
id: class:parrot_formdesigner.tools.services.networkninja.NetworkninjaFormService
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: NetworkNinja PostgreSQL form-source service.
relates_to:
- concept: class:parrot_formdesigner.tools.services.abstract.AbstractFormService
  rel: extends
---

# NetworkninjaFormService

Defined in [`parrot_formdesigner.tools.services.networkninja`](../summaries/mod:parrot_formdesigner.tools.services.networkninja.md).

```python
class NetworkninjaFormService(AbstractFormService)
```

NetworkNinja PostgreSQL form-source service.

Owns the SQL query against ``networkninja.forms`` + ``networkninja.form_metadata``
and the question_blocks → FormSchema transformation pipeline.

DSN resolution order:
    1. constructor ``dsn=`` kwarg
    2. ``PARROT_NETWORKNINJA_DSN`` env var
    3. ``parrot.conf.default_dsn``

Example:
    svc = NetworkninjaFormService(dsn="postgres://user:pw@host/db")
    raw = await svc.fetch(formid=42, orgid=7)
    form = svc.to_form_schema(raw)

## Methods

- `async def fetch(self, *, formid: int, orgid: int, **_: Any) -> dict[str, Any]` — Run the parameterized SQL query and return the row dict.
- `def to_form_schema(self, raw: dict[str, Any]) -> FormSchema` — Transform the row dict into a FormSchema.
- `def import_with_report(self, raw: dict[str, Any]) -> tuple[FormSchema, ImportDiffReport]` — Transform a raw row into a FormSchema plus an ImportDiffReport.
