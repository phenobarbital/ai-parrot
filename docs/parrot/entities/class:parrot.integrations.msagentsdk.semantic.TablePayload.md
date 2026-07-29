---
type: Wiki Entity
title: TablePayload
id: class:parrot.integrations.msagentsdk.semantic.TablePayload
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A tabular result payload.
---

# TablePayload

Defined in [`parrot.integrations.msagentsdk.semantic`](../summaries/mod:parrot.integrations.msagentsdk.semantic.md).

```python
class TablePayload(BaseModel)
```

A tabular result payload.

Attributes:
    result_type: Discriminator, always ``"table"``.
    columns: Column headers, in display order.
    rows: Row data; each row is a list of string cells aligned to
        ``columns``.
    total_rows: The total number of rows available upstream, used to
        render a "showing N of M" truncation note when ``rows`` has been
        capped by the renderer.
