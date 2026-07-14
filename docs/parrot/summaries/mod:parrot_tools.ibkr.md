---
type: Wiki Summary
title: parrot_tools.ibkr
id: mod:parrot_tools.ibkr
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: IBKR Trading Toolkit for AI-Parrot agents.
relates_to:
- concept: class:parrot_tools.ibkr.IBKRToolkit
  rel: defines
- concept: mod:parrot_tools
  rel: references
---

# `parrot_tools.ibkr`

IBKR Trading Toolkit for AI-Parrot agents.

Provides a unified toolkit for market data, order management, account info,
and portfolio operations through Interactive Brokers. Supports both TWS API
and Client Portal REST API backends with built-in risk management.

Usage:
    from parrot_tools.ibkr import IBKRToolkit, IBKRConfig, RiskConfig

    toolkit = IBKRToolkit(
        config=IBKRConfig(backend="tws", port=7497),
        risk_config=RiskConfig(max_order_qty=100),
    )

    async with toolkit:
        tools = toolkit.get_tools()

## Classes

- **`IBKRToolkit(AbstractToolkit)`** — Interactive Brokers trading toolkit for market data, orders, and portfolio management.
