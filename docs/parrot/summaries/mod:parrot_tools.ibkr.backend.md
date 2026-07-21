---
type: Wiki Summary
title: parrot_tools.ibkr.backend
id: mod:parrot_tools.ibkr.backend
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract backend interface for IBKR connections.
relates_to:
- concept: class:parrot_tools.ibkr.backend.IBKRBackend
  rel: defines
- concept: mod:parrot_tools.ibkr.models
  rel: references
---

# `parrot_tools.ibkr.backend`

Abstract backend interface for IBKR connections.

Defines the contract that both TWSBackend and PortalBackend must implement.
The IBKRToolkit delegates all operations to whichever backend is configured.

## Classes

- **`IBKRBackend(ABC)`** — Abstract base class for IBKR connection backends.
