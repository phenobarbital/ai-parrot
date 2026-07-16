---
type: Wiki Summary
title: parrot.bots.database.retries
id: mod:parrot.bots.database.retries
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Query retry handling — generalized for multiple database types.
relates_to:
- concept: class:parrot.bots.database.retries.DSLRetryHandler
  rel: defines
- concept: class:parrot.bots.database.retries.FluxRetryHandler
  rel: defines
- concept: class:parrot.bots.database.retries.QueryRetryConfig
  rel: defines
- concept: class:parrot.bots.database.retries.RetryContext
  rel: defines
- concept: class:parrot.bots.database.retries.RetryHandler
  rel: defines
- concept: class:parrot.bots.database.retries.SQLRetryHandler
  rel: defines
---

# `parrot.bots.database.retries`

Query retry handling — generalized for multiple database types.

Provides ``RetryHandler`` base class and ``SQLRetryHandler`` for SQL-specific
error patterns.  Stubs for Flux and DSL handlers are included for future use.

## Classes

- **`RetryContext(BaseModel)`** — Payload returned by SQLToolkit.execute_query on a retryable error.
- **`QueryRetryConfig`** — Configuration for query retry mechanism.
- **`RetryHandler`** — Base retry handler for any database toolkit.
- **`SQLRetryHandler(RetryHandler)`** — SQL-specific retry handler with error learning.
- **`FluxRetryHandler(RetryHandler)`** — InfluxDB Flux-specific retry handler (stub for future use).
- **`DSLRetryHandler(RetryHandler)`** — Elasticsearch DSL-specific retry handler (stub for future use).
