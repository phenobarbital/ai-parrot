---
type: Wiki Summary
title: parrot_tools.quant.models
id: mod:parrot_tools.quant.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic models for QuantToolkit input/output contracts.
relates_to:
- concept: class:parrot_tools.quant.models.AssetRiskInput
  rel: defines
- concept: class:parrot_tools.quant.models.CorrelationInput
  rel: defines
- concept: class:parrot_tools.quant.models.PiotroskiInput
  rel: defines
- concept: class:parrot_tools.quant.models.PortfolioRiskInput
  rel: defines
- concept: class:parrot_tools.quant.models.PortfolioRiskOutput
  rel: defines
- concept: class:parrot_tools.quant.models.RiskMetricsOutput
  rel: defines
- concept: class:parrot_tools.quant.models.StressScenario
  rel: defines
---

# `parrot_tools.quant.models`

Pydantic models for QuantToolkit input/output contracts.

These models define the data structures used across all quantitative
analysis functions: risk metrics, correlation, Piotroski F-Score,
volatility analytics, and stress testing.

## Classes

- **`PortfolioRiskInput(BaseModel)`** — Input for portfolio-level risk computation.
- **`AssetRiskInput(BaseModel)`** — Input for single-asset risk metrics.
- **`CorrelationInput(BaseModel)`** — Input for correlation analysis.
- **`StressScenario(BaseModel)`** — A single stress test scenario definition.
- **`PiotroskiInput(BaseModel)`** — Input for Piotroski F-Score calculation.
- **`RiskMetricsOutput(BaseModel)`** — Output from single-asset risk calculation.
- **`PortfolioRiskOutput(BaseModel)`** — Output from portfolio risk calculation.
