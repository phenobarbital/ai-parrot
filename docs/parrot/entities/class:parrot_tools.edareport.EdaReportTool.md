---
type: Wiki Entity
title: EdaReportTool
id: class:parrot_tools.edareport.EdaReportTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for generating comprehensive EDA reports using ydata_profiling.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# EdaReportTool

Defined in [`parrot_tools.edareport`](../summaries/mod:parrot_tools.edareport.md).

```python
class EdaReportTool(AbstractTool)
```

Tool for generating comprehensive EDA reports using ydata_profiling.

This tool creates detailed profiling reports with statistics, visualizations,
correlations, missing value analysis, and data quality insights.

## Methods

- `def apply_preset(self, preset_name: str, **kwargs) -> Dict[str, Any]` — Apply a configuration preset.
