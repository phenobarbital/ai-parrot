---
type: Wiki Summary
title: parrot_tools.ibkr.models
id: mod:parrot_tools.ibkr.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Pydantic data models for the IBKR Trading Toolkit.
relates_to:
- concept: class:parrot_tools.ibkr.models.AccountSummary
  rel: defines
- concept: class:parrot_tools.ibkr.models.BarData
  rel: defines
- concept: class:parrot_tools.ibkr.models.ContractSpec
  rel: defines
- concept: class:parrot_tools.ibkr.models.IBKRConfig
  rel: defines
- concept: class:parrot_tools.ibkr.models.OrderRequest
  rel: defines
- concept: class:parrot_tools.ibkr.models.OrderStatus
  rel: defines
- concept: class:parrot_tools.ibkr.models.Position
  rel: defines
- concept: class:parrot_tools.ibkr.models.Quote
  rel: defines
- concept: class:parrot_tools.ibkr.models.RiskConfig
  rel: defines
---

# `parrot_tools.ibkr.models`

Pydantic data models for the IBKR Trading Toolkit.

Defines configuration, market data, order, position, and account models
used throughout the IBKR toolkit. All monetary/price fields use Decimal
for precision. Field descriptions serve as LLM tool parameter descriptions.

## Classes

- **`IBKRConfig(BaseModel)`** — Configuration for IBKR connection.
- **`RiskConfig(BaseModel)`** — Risk management guardrails for agent-driven trading.
- **`ContractSpec(BaseModel)`** — Unified contract specification for IBKR instruments.
- **`Quote(BaseModel)`** — Real-time quote data for a contract.
- **`BarData(BaseModel)`** — Historical OHLCV bar.
- **`OrderRequest(BaseModel)`** — Order placement request with validation.
- **`OrderStatus(BaseModel)`** — Order status response from IBKR.
- **`Position(BaseModel)`** — Account position for a single instrument.
- **`AccountSummary(BaseModel)`** — Account summary information.
