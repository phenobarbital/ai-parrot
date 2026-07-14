---
type: Wiki Entity
title: EdaUtils
id: class:parrot_tools.quickeda.EdaUtils
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Utility functions for EDA operations.
---

# EdaUtils

Defined in [`parrot_tools.quickeda`](../summaries/mod:parrot_tools.quickeda.md).

```python
class EdaUtils
```

Utility functions for EDA operations.

## Methods

- `def detect_outliers(df: pd.DataFrame, columns: List[str]=None, method: str='iqr') -> Dict[str, List]` — Detect outliers in numerical columns.
- `def suggest_data_types(df: pd.DataFrame) -> Dict[str, str]` — Suggest optimal data types for DataFrame columns.
- `def memory_usage_analysis(df: pd.DataFrame) -> Dict[str, Any]` — Analyze memory usage of DataFrame.
