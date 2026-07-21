---
type: Wiki Entity
title: AbstractKMSSigner
id: class:parrot.security.audit_ledger.AbstractKMSSigner
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Injectable signing/verification backend for :class:`AuditLedger`.
---

# AbstractKMSSigner

Defined in [`parrot.security.audit_ledger`](../summaries/mod:parrot.security.audit_ledger.md).

```python
class AbstractKMSSigner(ABC)
```

Injectable signing/verification backend for :class:`AuditLedger`.

Implementations must be async to allow non-blocking calls to managed KMS
services (AWS KMS, GCP Cloud KMS, Azure Key Vault, etc.).

## Methods

- `async def sign(self, data: bytes) -> str` — Return a hex-encoded signature over *data*.
- `async def verify(self, data: bytes, signature: str) -> bool` — Verify that *signature* was produced by ``sign(data)``.
