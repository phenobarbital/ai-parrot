---
type: Wiki Summary
title: parrot_tools.ibkr.tws_backend
id: mod:parrot_tools.ibkr.tws_backend
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: TWS API backend for IBKR using ib_async.
relates_to:
- concept: class:parrot_tools.ibkr.tws_backend.TWSBackend
  rel: defines
- concept: mod:parrot_tools.ibkr.backend
  rel: references
- concept: mod:parrot_tools.ibkr.models
  rel: references
---

# `parrot_tools.ibkr.tws_backend`

TWS API backend for IBKR using ib_async.

Implements all IBKRBackend methods using the ib_async library (async-first
fork of ib_insync). Connects to TWS or IB Gateway for real-time market data,
order management, account info, and more.

## Classes

- **`TWSBackend(IBKRBackend)`** — TWS API backend using ib_async.
