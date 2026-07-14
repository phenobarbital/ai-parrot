---
type: Wiki Entity
title: AuditEntry
id: class:parrot.auth.audit.AuditEntry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single credential invocation record.
---

# AuditEntry

Defined in [`parrot.auth.audit`](../summaries/mod:parrot.auth.audit.md).

```python
class AuditEntry
```

Single credential invocation record.

.. deprecated::
    Use :class:`parrot.security.audit_ledger.AuditLedgerEntry` instead.
    This class will be removed in a future release.

Attributes:
    timestamp: ISO-8601 UTC timestamp of the invocation.
    user_id: Canonical user identity (``aad_object_id`` or channel id).
    channel: Integration channel (e.g. ``"msagentsdk"``).
    tool: Tool name that requested credentials (e.g. ``"o365"``).
    connection: OAuth connection name used (e.g. ``"graph_sso"``).
    key_fingerprint: SHA-256 hex of the first 8 bytes of the resolved
        token. Never the raw token itself.
    action: Either ``"resolve"`` (token fetched from token service) or
        ``"obo_exchange"`` (on-behalf-of exchange performed).
