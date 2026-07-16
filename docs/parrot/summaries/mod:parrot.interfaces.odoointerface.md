---
type: Wiki Summary
title: parrot.interfaces.odoointerface
id: mod:parrot.interfaces.odoointerface
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Odoo ERP interface via JSON-RPC 2.0.
relates_to:
- concept: class:parrot.interfaces.odoointerface.JsonRpcRequest
  rel: defines
- concept: class:parrot.interfaces.odoointerface.JsonRpcResponse
  rel: defines
- concept: class:parrot.interfaces.odoointerface.OdooAuthenticationError
  rel: defines
- concept: class:parrot.interfaces.odoointerface.OdooConfig
  rel: defines
- concept: class:parrot.interfaces.odoointerface.OdooConnectionError
  rel: defines
- concept: class:parrot.interfaces.odoointerface.OdooError
  rel: defines
- concept: class:parrot.interfaces.odoointerface.OdooInterface
  rel: defines
- concept: class:parrot.interfaces.odoointerface.OdooRPCError
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot.interfaces.odoointerface`

Odoo ERP interface via JSON-RPC 2.0.

Provides an async-first interface to Odoo v16+ for reading and writing
business data (partners, invoices, products, inventory, etc.) through
the standard JSON-RPC 2.0 endpoint.

## Classes

- **`OdooError(Exception)`** — Base exception for Odoo JSON-RPC errors.
- **`OdooAuthenticationError(OdooError)`** — Raised when authentication fails (invalid credentials or False uid).
- **`OdooRPCError(OdooError)`** — Raised when Odoo returns a JSON-RPC error response.
- **`OdooConnectionError(OdooError)`** — Raised on network or connection failures.
- **`OdooConfig(BaseModel)`** — Configuration for Odoo JSON-RPC connection.
- **`JsonRpcRequest(BaseModel)`** — JSON-RPC 2.0 request payload.
- **`JsonRpcResponse(BaseModel)`** — JSON-RPC 2.0 response payload.
- **`OdooInterface`** — Async interface for Odoo ERP via JSON-RPC 2.0.
