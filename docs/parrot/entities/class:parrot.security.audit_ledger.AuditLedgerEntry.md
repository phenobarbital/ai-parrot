---
type: Wiki Entity
title: AuditLedgerEntry
id: class:parrot.security.audit_ledger.AuditLedgerEntry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Append-only, KMS-signed record of a credentialed tool invocation.
---

# AuditLedgerEntry

Defined in [`parrot.security.audit_ledger`](../summaries/mod:parrot.security.audit_ledger.md).

```python
class AuditLedgerEntry(BaseModel)
```

Append-only, KMS-signed record of a credentialed tool invocation.

Attributes:
    entry_id: Unique ledger record identifier (UUIDv4).
    user_id: Canonical per-user identity (email), consistent with
        ``TeamsHumanChannel`` and ``A2AServer._extract_identity``.
    channel: Invocation channel, e.g. ``"a2a:copilot"``.
    tool: Name of the tool that was invoked.
    provider: Credential provider, e.g. ``"jira"``, ``"o365"``,
        ``"work-iq"``, ``"fireflies"``, or ``"stub"``.
    key_fingerprint: SHA-256 hex digest of the credential material.
        **Never** the raw credential.
    signature: KMS signature over the canonical entry bytes (see
        :meth:`canonical_bytes`).
    created_at: UTC timestamp recorded at entry creation.

## Methods

- `def canonical_bytes(self) -> bytes` — Return the canonical byte representation used for signing/verification.
