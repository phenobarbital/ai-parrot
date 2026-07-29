---
type: Wiki Entity
title: SeasonalDetectionTool
id: class:parrot_tools.seasonaldetection.SeasonalDetectionTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for detecting stationarity and seasonality in time series data.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# SeasonalDetectionTool

Defined in [`parrot_tools.seasonaldetection`](../summaries/mod:parrot_tools.seasonaldetection.md).

```python
class SeasonalDetectionTool(AbstractTool)
```

Tool for detecting stationarity and seasonality in time series data.

This tool performs comprehensive stationarity analysis using:
- Augmented Dickey-Fuller (ADF) test
- Kwiatkowski-Phillips-Schmidt-Shin (KPSS) test
- Visual inspection through plots
- Optional seasonal decomposition
- Trend removal and re-testing

The tool helps determine if a time series is stationary (suitable for many
time series models) or non-stationary (requiring differencing or detrending).
