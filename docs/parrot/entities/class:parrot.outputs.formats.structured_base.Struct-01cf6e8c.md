---
type: Wiki Entity
title: StructuredOutputBase
id: class:parrot.outputs.formats.structured_base.StructuredOutputBase
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mixin providing the shared contract for all structured-output renderers.
---

# StructuredOutputBase

Defined in [`parrot.outputs.formats.structured_base`](../summaries/mod:parrot.outputs.formats.structured_base.md).

```python
class StructuredOutputBase
```

Mixin providing the shared contract for all structured-output renderers.

Concrete renderers (table, chart, map) inherit this alongside ``BaseChart``.
The mixin never touches ``@register_renderer`` wiring or the ``BaseChart``
abstract method — it only adds extraction and envelope helpers.

Methods:
    _extract_rows: Deterministic DataFrame extraction; never raises.
    _route_envelope: Shared envelope contract; never raises.
    _extract_json_code: JSON extraction from fenced or bare text.
