---
type: Wiki Summary
title: parrot.bots.flows.core.storage.backends.postgres
id: mod:parrot.bots.flows.core.storage.backends.postgres
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PostgresResultStorage — Postgres backend for crew/flow execution results
  (FEAT-147).
relates_to:
- concept: class:parrot.bots.flows.core.storage.backends.postgres.PostgresResultStorage
  rel: defines
- concept: mod:parrot.bots.flows.core.storage.backends.base
  rel: references
- concept: mod:parrot.conf
  rel: references
---

# `parrot.bots.flows.core.storage.backends.postgres`

PostgresResultStorage — Postgres backend for crew/flow execution results (FEAT-147).

One row per execution in a ``jsonb``-payload table; idempotent DDL on first write.

## Classes

- **`PostgresResultStorage(ResultStorage)`** — Persist crew/flow execution results to Postgres (one row per execution).
