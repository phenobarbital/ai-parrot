---
type: Wiki Summary
title: parrot_tools.ibkr.portal_backend
id: mod:parrot_tools.ibkr.portal_backend
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: IBKR Client Portal REST API backend.
relates_to:
- concept: class:parrot_tools.ibkr.portal_backend.PortalBackend
  rel: defines
- concept: mod:parrot_tools.ibkr.backend
  rel: references
- concept: mod:parrot_tools.ibkr.models
  rel: references
---

# `parrot_tools.ibkr.portal_backend`

IBKR Client Portal REST API backend.

Implements IBKRBackend using aiohttp to communicate with the IBKR Client
Portal Gateway. Handles authentication, session keepalive, and automatic
re-authentication on 401 responses.

All monetary fields are converted from JSON floats to Decimal for precision.

## Classes

- **`PortalBackend(IBKRBackend)`** — IBKR Client Portal REST API backend.
