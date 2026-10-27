---
id: FW-007
query_id: Q006
type: wiki_page
intent: "Orient: AuditLedger — signed append-only ledger referenced by both brainstorms."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-007 — AuditLedger exists (security/audit_ledger.py): append-only, KMS-signed, but scoped to credentialed tool invocations over the A2A bridge; in-memory store

## Summary

`security/audit_ledger.py` (FEAT-260 / TASK-1642, reconciled in TASK-1675) defines `AuditLedgerEntry` (with `canonical_bytes()` for signing; carries `key_fingerprint` = sha256 of credential material, never the raw credential), `AbstractKMSSigner.sign/verify`, `LocalHMACSigner`, `AzureKeyVaultSigner`, and `AuditLedger(signer, storage)` with `append()` / `verify(entry_id)` / `get_entry` / `entry_count` — 'there is no update or delete'. Its documented scope is 'every credentialed tool invocation over the A2A bridge'; `entry_count` says 'in the in-memory store', so persistence is backend-injected via `storage`. `auth/audit.py` is DEPRECATED in favour of `parrot.security.audit_ledger`. A separate semantic-layer audit ledger (TASK-4474, active, 'signed semantic audit ledger + Postgres sink') is being built by a parallel feature. The brainstorm's assumption 'the signed, append-only AuditLedger already defined for ai-parrot' is CONFIRMED structurally, but its entry shape is credential-centric (not caller/capability/policy/data-class/result-digest) and would need a new entry type or a sibling ledger.

## Citations

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 1-30
  symbol: `module docstring`
  wiki_page_id: file:packages/ai-parrot/src/parrot/security/audit_ledger.py (score=0.50)
  excerpt: |
    Append-only, KMS-signed credential-invocation ledger (FEAT-260 / TASK-1642).
    Every credentialed tool invocation over the A2A bridge records an AuditLedgerEntry ... signed by an AbstractKMSSigner
    Append-only semantics are enforced by the public API: AuditLedger.append and AuditLedger.verify are the only entry-points
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: n/a (API outline)
  symbol: `AuditLedgerEntry / AbstractKMSSigner / LocalHMACSigner / AzureKeyVaultSigner / AuditLedger`
  excerpt: |
    class AuditLedger: __init__(self, signer, storage); append(); verify(entry_id); get_entry(entry_id); entry_count()
- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  lines: n/a
  symbol: `DEPRECATED shim`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/audit.py (score=0.73)
  excerpt: |
    DEPRECATED: Use parrot.security.audit_ledger instead.
- path: `sdd/tasks/completed/TASK-1642-auditledger.md`
  lines: n/a
  symbol: `TASK-1642 AuditLedger`
  wiki_page_id: file:sdd/tasks/completed/TASK-1642-auditledger.md (score=1.00)
- path: `sdd/tasks/active/TASK-4474-semantic-audit-ledger.md`
  lines: n/a
  symbol: `TASK-4474 (parallel, active) signed semantic audit ledger + Postgres sink`
  wiki_page_id: file:sdd/tasks/active/TASK-4474-semantic-audit-ledger.md (score=0.45)

## Notes

`[cross-lane: type=read, intent=audit_ledger.py AuditLedgerEntry field list + the storage protocol signature to judge reuse for performative-level audit lines]`. Also `auth/broker/core.py::CredentialBroker` (FEAT-264) is the surface that writes to this ledger.
