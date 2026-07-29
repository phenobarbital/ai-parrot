---
type: Wiki Entity
title: AirtableSource
id: class:parrot.tools.dataset_manager.sources.airtable.AirtableSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Datasource backed by an Airtable table.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# AirtableSource

Defined in [`parrot.tools.dataset_manager.sources.airtable`](../summaries/mod:parrot.tools.dataset_manager.sources.airtable.md).

```python
class AirtableSource(DataSource)
```

Datasource backed by an Airtable table.

## Methods

- `def cache_key(self) -> str`
- `def describe(self) -> str`
- `async def prefetch_schema(self) -> Dict[str, str]`
- `async def fetch(self, max_records: Optional[int]=None, **params) -> pd.DataFrame`
