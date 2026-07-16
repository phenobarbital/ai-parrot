---
type: Wiki Entity
title: MetadataTool
id: class:parrot_tools.metadata.MetadataTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Expose DataFrame metadata with comprehensive EDA capabilities.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# MetadataTool

Defined in [`parrot_tools.metadata`](../summaries/mod:parrot_tools.metadata.md).

```python
class MetadataTool(AbstractTool)
```

Expose DataFrame metadata with comprehensive EDA capabilities.

Provides:
- DataFrame schemas (columns, dtypes, shapes)
- EDA summaries (row counts, column types, missing values, memory usage)
- Sample rows for quick data inspection
- Detailed column statistics (optional)

## Methods

- `def update_metadata(self, metadata: Dict[str, Dict[str, Any]], alias_map: Optional[Dict[str, str]]=None, dataframes: Optional[Dict[str, pd.DataFrame]]=None) -> None` — Update the internal metadata dictionary, alias map, and dataframes.
