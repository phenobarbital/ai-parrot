---
type: Wiki Summary
title: parrot.autonomous.ledger
id: mod:parrot.autonomous.ledger
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Typed Event Ledger for the autonomous harness.
relates_to:
- concept: class:parrot.autonomous.ledger.AgentLedgerState
  rel: defines
- concept: class:parrot.autonomous.ledger.EventLedger
  rel: defines
- concept: class:parrot.autonomous.ledger.InMemoryLedgerBackend
  rel: defines
- concept: class:parrot.autonomous.ledger.IncompleteExecution
  rel: defines
- concept: class:parrot.autonomous.ledger.LedgerConfig
  rel: defines
- concept: class:parrot.autonomous.ledger.LedgerEvent
  rel: defines
- concept: class:parrot.autonomous.ledger.LedgerRecorder
  rel: defines
- concept: class:parrot.autonomous.ledger.PostgresLedgerBackend
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: references
---

# `parrot.autonomous.ledger`

Typed Event Ledger for the autonomous harness.

FEAT-212 — Typed Event Ledger & Crash Resume.

Provides:
- ``LedgerEvent``: Pydantic wrapper for a persisted lifecycle event.
- ``LedgerConfig``: Configuration for the recorder and backend.
- ``AgentLedgerState``: Read projection for /health and /status.
- ``IncompleteExecution``: Read projection for crash-resume detection.
- ``LEDGER_DDL``: Idempotent DDL for the ``harness_ledger`` Postgres table.
- ``EventLedger`` (ABC): Abstract interface for the ledger store.
- ``PostgresLedgerBackend``: Postgres append-only implementation.
- ``InMemoryLedgerBackend``: In-memory backend for testing (no DB required).
- ``LedgerRecorder``: Subscribes to the global lifecycle registry and
  persists all events (except filtered ones) via batched async writes.

Usage::

    # Wire up at app startup:
    db = app["database"]
    backend = PostgresLedgerBackend(db)
    await backend.ensure_schema()
    recorder = LedgerRecorder(backend)
    recorder.start()
    # At orchestrator start (opt-in):
    await orchestrator.resume(backend)

## Classes

- **`LedgerEvent(BaseModel)`** — Pydantic wrapper for a single persisted lifecycle event.
- **`LedgerConfig(BaseModel)`** — Configuration for the ledger recorder and backend.
- **`AgentLedgerState(BaseModel)`** — Read projection of an agent's recent ledger activity.
- **`IncompleteExecution(BaseModel)`** — An execution that was opened (Before*) but never closed (After*/Failed*).
- **`EventLedger(ABC)`** — Abstract interface for the persistent event ledger.
- **`PostgresLedgerBackend(EventLedger)`** — Postgres append-only implementation of ``EventLedger``.
- **`InMemoryLedgerBackend(EventLedger)`** — In-memory ``EventLedger`` implementation for use in tests and CI.
- **`LedgerRecorder`** — Subscribe to the global lifecycle registry and persist all events.
