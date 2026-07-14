---
type: Wiki Entity
title: TableMetadata
id: class:parrot_tools.multidb.TableMetadata
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Optimized table metadata structure designed for both caching efficiency
---

# TableMetadata

Defined in [`parrot_tools.multidb`](../summaries/mod:parrot_tools.multidb.md).

```python
class TableMetadata
```

Optimized table metadata structure designed for both caching efficiency
and LLM comprehension. This format balances completeness with conciseness.

## Methods

- `def to_llm_context(self, format_type: MetadataFormat=MetadataFormat.YAML_OPTIMIZED) -> str` — Convert table metadata to LLM-friendly format.
