---
type: Wiki Entity
title: FilterDefinition
id: class:parrot.tools.dataset_manager.filtering.contracts.FilterDefinition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A declarative common-field filter definition stored on a DatasetManager.
---

# FilterDefinition

Defined in [`parrot.tools.dataset_manager.filtering.contracts`](../summaries/mod:parrot.tools.dataset_manager.filtering.contracts.md).

```python
class FilterDefinition(BaseModel)
```

A declarative common-field filter definition stored on a DatasetManager.

Instances are validated at ``define_filters()`` time, before any I/O.
The ``model_validator`` enforces op⇄kind compatibility.

Attributes:
    name: Stable filter identifier used in requests and the schema.
    columns: Column(s) targeted; spatial filters may carry [lat, lng]
        or a single geometry column.
    kind: Semantic kind of the filter (categorical, numeric, temporal,
        text, or spatial).
    ops: Allowed filter operators for this definition (at least one).
    required: When True, ``apply_filters`` raises ``ValueError`` if a
        target dataset lacks the column(s). When False (default),
        missing-column datasets are silently skipped.
    values_source: Optional explicit source for distinct values.
    label: Human-readable label for frontend display.
    description: Longer description for documentation or LLM context.
