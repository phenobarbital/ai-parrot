---
type: Wiki Summary
title: parrot.security.audit_ledger
id: mod:parrot.security.audit_ledger
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Append-only, KMS-signed credential-invocation ledger (FEAT-260 / TASK-1642).
relates_to:
- concept: class:parrot.security.audit_ledger.AbstractKMSSigner
  rel: defines
- concept: class:parrot.security.audit_ledger.AuditLedger
  rel: defines
- concept: class:parrot.security.audit_ledger.AuditLedgerEntry
  rel: defines
- concept: class:parrot.security.audit_ledger.AzureKeyVaultSigner
  rel: defines
- concept: class:parrot.security.audit_ledger.LocalHMACSigner
  rel: defines
- concept: func:parrot.security.audit_ledger.derive_key_fingerprint
  rel: defines
---

# `parrot.security.audit_ledger`

Append-only, KMS-signed credential-invocation ledger (FEAT-260 / TASK-1642).

Every credentialed tool invocation over the A2A bridge records an
:class:`AuditLedgerEntry` that carries a ``key_fingerprint`` (a SHA-256 hash
of the credential material) but **never** the raw credential.  Each entry is
signed by a :class:`AbstractKMSSigner` so the record cannot be silently tampered
with after the fact.

Two signers are provided:

- :class:`LocalHMACSigner` — HMAC-SHA256 with a caller-supplied secret; suitable
  for local development, tests, and environments without a managed KMS.
- A production KMS backend can be injected by implementing
  :class:`AbstractKMSSigner` and passing the instance to :class:`AuditLedger`.

Append-only semantics are enforced by the public API: :meth:`AuditLedger.append`
and :meth:`AuditLedger.verify` are the only entry-points; there is no
``update`` or ``delete``.

## Classes

- **`AuditLedgerEntry(BaseModel)`** — Append-only, KMS-signed record of a credentialed tool invocation.
- **`AbstractKMSSigner(ABC)`** — Injectable signing/verification backend for :class:`AuditLedger`.
- **`LocalHMACSigner(AbstractKMSSigner)`** — HMAC-SHA256 signer for local development and testing.
- **`AzureKeyVaultSigner(AbstractKMSSigner)`** — Azure Key Vault backed KMS signer for production environments.
- **`AuditLedger`** — Append-only, KMS-signed credential-invocation ledger.

## Functions

- `def derive_key_fingerprint(credential_material: Any) -> str` — Return the SHA-256 hex digest of ``credential_material``.
