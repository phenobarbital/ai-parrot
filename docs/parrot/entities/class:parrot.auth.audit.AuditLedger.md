---
type: Wiki Entity
title: AuditLedger
id: class:parrot.auth.audit.AuditLedger
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DEPRECATED log-based audit ledger.
---

# AuditLedger

Defined in [`parrot.auth.audit`](../summaries/mod:parrot.auth.audit.md).

```python
class AuditLedger
```

DEPRECATED log-based audit ledger.

.. deprecated::
    Use :class:`parrot.security.audit_ledger.AuditLedger` instead.
    This class will be removed in a future release.

Records per-invocation credential usage for compliance.
Initially log-based (structured JSON lines).

Attributes:
    logger: Logger instance used for structured JSON output.

## Methods

- `def record(self, entry: AuditEntry) -> None` — Record a credential invocation entry.
- `async def flush(self) -> None` — Flush any buffered entries to the backing store (no-op).
- `def entries(self) -> list[AuditEntry]` — Return a copy of all recorded entries (primarily for testing).
