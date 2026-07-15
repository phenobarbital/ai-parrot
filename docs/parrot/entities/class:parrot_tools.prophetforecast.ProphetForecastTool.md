---
type: Wiki Entity
title: ProphetForecastTool
id: class:parrot_tools.prophetforecast.ProphetForecastTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Generate time series forecasts with Facebook Prophet and return plots.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ProphetForecastTool

Defined in [`parrot_tools.prophetforecast`](../summaries/mod:parrot_tools.prophetforecast.md).

```python
class ProphetForecastTool(AbstractTool)
```

Generate time series forecasts with Facebook Prophet and return plots.

## Methods

- `def update_context(self, dataframes: Dict[str, pd.DataFrame], alias_map: Optional[Dict[str, str]]=None) -> None` — Update internal references to available DataFrames and aliases.
