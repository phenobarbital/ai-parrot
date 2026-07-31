---
type: Wiki Entity
title: MetricsCalculator
id: class:parrot_tools.whatif.MetricsCalculator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Calculates derived metrics on DataFrames
---

# MetricsCalculator

Defined in [`parrot_tools.whatif`](../summaries/mod:parrot_tools.whatif.md).

```python
class MetricsCalculator
```

Calculates derived metrics on DataFrames

## Methods

- `def register_metric(self, name: str, formula: str, description: str='')` — Register a derived metric
- `def calculate(self, df: pd.DataFrame, metric_name: str) -> pd.Series` — Calculate a derived metric
- `def add_to_dataframe(self, df: pd.DataFrame) -> pd.DataFrame` — Add all derived metrics to DataFrame
- `def get_base_value(self, df: pd.DataFrame, metric_name: str) -> float` — Get total value of a metric (derived or not)
