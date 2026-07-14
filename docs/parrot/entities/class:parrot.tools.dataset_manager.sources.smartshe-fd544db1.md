---
type: Wiki Entity
title: SmartsheetSource
id: class:parrot.tools.dataset_manager.sources.smartsheet.SmartsheetSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Datasource backed by a Smartsheet sheet.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# SmartsheetSource

Defined in [`parrot.tools.dataset_manager.sources.smartsheet`](../summaries/mod:parrot.tools.dataset_manager.sources.smartsheet.md).

```python
class SmartsheetSource(DataSource)
```

Datasource backed by a Smartsheet sheet.

## Methods

- `def cache_key(self) -> str`
- `def describe(self) -> str`
- `async def prefetch_schema(self) -> Dict[str, str]`
- `async def fetch(self, **params) -> pd.DataFrame`
