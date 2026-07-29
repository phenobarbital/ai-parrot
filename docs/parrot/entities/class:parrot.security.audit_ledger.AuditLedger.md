---
type: Wiki Entity
title: AuditLedger
id: class:parrot.security.audit_ledger.AuditLedger
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Append-only, KMS-signed credential-invocation ledger.
---

# AuditLedger

Defined in [`parrot.security.audit_ledger`](../summaries/mod:parrot.security.audit_ledger.md).

```python
class AuditLedger
```

Append-only, KMS-signed credential-invocation ledger.

Entries are stored in-memory by default.  An optional *storage* backend
can be supplied (a callable coroutine that accepts a serialised JSON string)
for durable persistence (DocumentDB, PostgreSQL, etc.).

Append-only semantics: only :meth:`append` and :meth:`verify` are exposed;
there is no ``update``, ``delete``, or ``get_all`` mutation surface.

Args:
    signer: A :class:`AbstractKMSSigner` implementation.  Defaults to
        :class:`LocalHMACSigner` (HMAC-SHA256 with a random in-process
        key — suitable for tests).
    storage: Optional async callable ``(json_str: str) -> None`` that
        persists each entry to a durable backend.  ``None`` (default)
        retains entries in memory only.

Example::

    ledger = AuditLedger()
    entry = await ledger.append(
        user_id="alice@example.com",
        channel="a2a:copilot",
        tool="jira_create_issue",
        provider="jira",
        credential_material=jira_token,
    )
    assert await ledger.verify(entry.entry_id)

## Methods

- `async def append(self, *, user_id: str, channel: str, tool: str, provider: str, credential_material: Any) -> AuditLedgerEntry` — Create, sign, and persist a new ledger entry.
- `async def verify(self, entry_id: str) -> bool` — Re-check the KMS signature on a previously appended entry.
- `def get_entry(self, entry_id: str) -> Optional[AuditLedgerEntry]` — Return the entry for *entry_id*, or ``None`` if not found.
- `def entry_count(self) -> int` — Return the number of entries in the in-memory store.
