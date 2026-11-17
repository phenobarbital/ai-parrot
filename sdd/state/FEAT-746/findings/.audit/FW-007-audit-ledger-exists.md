---
id: FW-007
query_id: Q006
type: wiki_page
intent: "Orient: the AuditLedger (signed, append-only) the brainstorm says already exists."
executed_at: 2026-10-25T22:44:49Z
duration_ms: 0
parent_id: null
depth: 2
---

# FW-007 — AuditLedger EXISTS (parrot/security/audit_ledger.py): append-only, KMS-signed, but credential-invocation-shaped; semantic layer plans a separate ledger reusing only the signers

## Summary

`parrot.security.audit_ledger.AuditLedger` (FEAT-260/TASK-1642) is real: `append(user_id, channel, tool, provider, credential_material)` builds an `AuditLedgerEntry` (fixed fields: entry_id, user_id, channel, tool, provider, key_fingerprint, signature, created_at), signs `canonical_bytes()` with an `AbstractKMSSigner` (`LocalHMACSigner`, `AzureKeyVaultSigner`), keeps entries in memory and optionally forwards JSON to an async `storage(json_str)` callable; only `append`/`verify`/`get_entry` exist. Its schema cannot carry capability/policy/data-class/cost fields, so the FEAT-704 semantic layer deliberately defines its own `SemanticAuditEntry`/`SemanticAuditLedger` reusing the signers and the storage-callable contract (TASK-4474, pending). The brainstorm's "served ledger is the signed, append-only AuditLedger already defined" holds for the *mechanism*, not for the *schema*; the established pattern is "own entry model + core signers". `parrot/auth/audit.py` is a deprecated alias.

## Citations

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  symbol: `AuditLedger`
  wiki_page_id: file:packages/ai-parrot/src/parrot/security/audit_ledger.py (score 0.45; ingested 2026-10-18)
  excerpt: |
    class AuditLedger:
        def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None)
        async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry
        async def verify(self, entry_id) -> bool; def get_entry(self, entry_id); def entry_count(self)
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  symbol: `AuditLedgerEntry`
  excerpt: |
    class AuditLedgerEntry(BaseModel): entry_id, user_id, channel, tool, provider, key_fingerprint, signature="", created_at
        def canonical_bytes(self) -> bytes  # sorted-key JSON of all fields except signature
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  symbol: `AbstractKMSSigner`
  excerpt: |
    class AbstractKMSSigner(ABC): async sign(data: bytes) -> str; async verify(data: bytes, signature: str) -> bool
    class LocalHMACSigner(AbstractKMSSigner); class AzureKeyVaultSigner(AbstractKMSSigner)
- path: `sdd/tasks/active/TASK-4474-semantic-audit-ledger.md`
  wiki_page_id: file:sdd/tasks/active/TASK-4474-semantic-audit-ledger.md (score 0.76)
  excerpt: |
    "AuditLedger itself (not used — credential-shaped)"; SemanticAuditLedger(signer, storage, max_entries) reusing
    AbstractKMSSigner + async storage(json_str); postgres_audit_storage(dsn_or_pool) + semantic_audit_events.sql
- path: `packages/ai-parrot/src/parrot/security/security_events.sql`
  excerpt: |
    (referenced by TASK-4474 as the DDL pattern: CREATE TABLE IF NOT EXISTS + JSONB + per-column indexes)
- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/audit.py (score 0.55)
  excerpt: |
    DEPRECATED: Use parrot.security.audit_ledger instead.

## Notes

- Storage failure in `AuditLedger.append` is swallowed (in-memory is source of truth); the semantic design adds `required=True` to fail closed. The served ledger for a cross-boundary protocol would want the fail-closed variant.
