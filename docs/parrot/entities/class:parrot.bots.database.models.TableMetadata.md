---
type: Wiki Entity
title: TableMetadata
id: class:parrot.bots.database.models.TableMetadata
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Enhanced table metadata for large-scale operations.
---

# TableMetadata

Defined in [`parrot.bots.database.models`](../summaries/mod:parrot.bots.database.models.md).

```python
class TableMetadata
```

Enhanced table metadata for large-scale operations.

## Methods

- `def satisfies(self, required: Completeness) -> bool` — Return True if this entry meets or exceeds *required* completeness.
- `def to_yaml_context(self) -> str` — Convert to YAML context optimized for LLM consumption.
- `def to_dict(self) -> Dict[str, Any]` — Serialize ``TableMetadata`` to a plain dictionary.
