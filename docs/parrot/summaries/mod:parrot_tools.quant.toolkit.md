---
type: Wiki Summary
title: parrot_tools.quant.toolkit
id: mod:parrot_tools.quant.toolkit
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: QuantToolkit - Quantitative Risk Analysis Toolkit.
relates_to:
- concept: class:parrot_tools.quant.toolkit.QuantToolkit
  rel: defines
- concept: mod:parrot_tools.quant
  rel: references
- concept: mod:parrot_tools.quant.correlation
  rel: references
- concept: mod:parrot_tools.quant.models
  rel: references
- concept: mod:parrot_tools.quant.piotroski
  rel: references
- concept: mod:parrot_tools.quant.risk_metrics
  rel: references
- concept: mod:parrot_tools.quant.stress_testing
  rel: references
- concept: mod:parrot_tools.quant.volatility
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.quant.toolkit`

QuantToolkit - Quantitative Risk Analysis Toolkit.

Provides agent-accessible tools for portfolio risk management,
correlation analysis, fundamental scoring, volatility analytics,
and stress testing.

Designed for allocation to:
- risk_analyst: VaR, beta, drawdown, Sharpe, correlation, stress testing
- risk_research_crew: rolling metrics, regime detection
- equity_analyst: Piotroski F-Score, comparative risk metrics
- sentiment_analyst: volatility cone, IV/RV spread

Usage:
    toolkit = QuantToolkit()
    tools = await toolkit.get_tools()
    # Agent can now use: compute_risk_metrics, compute_portfolio_risk, etc.

## Classes

- **`QuantToolkit(AbstractToolkit)`** — Quantitative risk analysis, portfolio metrics, and fundamental scoring toolkit.
