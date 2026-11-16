---
id: FW-005
query_id: Q005
type: wiki_query
intent: "Orient: audit ledger signers and the semantic audit sink — candidates for reuse by an accounting audit entry."
executed_at: 2026-11-11T22:41:00Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-005 — A signed semantic audit ledger already ships in the package (`SemanticAuditEntry` / `SemanticAuditLedger` + a Postgres sink) with the same design the old spec gave `AccountingAuditLedger`: core signers, `storage(json_str)`, `canonical_bytes` without signature, `required=` fail-closed

## Summary

`parrot/semantic/audit.py` defines `SemanticAuditEntry` (schema_version, entry_id, created_at, user/tenant/channel/agent, `subject_digest`, roles, model, `model_digest`, `policy_digest`, `engine: Literal["native"]`, tool, structured_query, raw_sql, compiled_sql, governed_sql, dialect, driver, rls_applied, masked_columns, pbac, outcome, error_code, row_count, duration_ms, signature) and `SemanticAuditLedger(signer, storage, max_entries)`: a bounded in-memory deque, signer defaulting to `LocalHMACSigner`, `append(entry, *, required=False)` that raises when a required sink is missing or fails, `verify()`, and `postgres_audit_storage(dsn_or_pool)` writing to the table created by `sql/semantic_audit_events.sql`. It reuses only `AbstractKMSSigner` / `LocalHMACSigner` from `parrot.security`; the core `AuditLedger` stays credential-invocation shaped. The entry has no `snapshot_hash`, `sql_hash`, `lineage_ref`, `assertion_status` or `target` field, and `engine` is a one-value Literal.

## Citations

- wiki: `file:packages/ai-parrot-semantic/src/parrot/semantic/audit.py` (Q005 score=1.00)
- wiki: `sym:packages/ai-parrot-semantic/src/parrot/semantic/audit.py#SemanticAuditLedger` (Q005 score=0.93)
- wiki: `file:sdd/tasks/completed/TASK-4474-semantic-audit-ledger.md` (Q005 score=0.97)
- wiki: `file:sdd/state/FEAT-746/findings/.audit/FW-007-audit-ledger-exists.md` (Q005 score=0.94)
- wiki: `file:packages/ai-parrot-semantic/tests/test_audit.py` (Q005 score=0.41)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 23-67
  symbol: `SemanticAuditEntry`
  excerpt: |
    class SemanticAuditEntry(BaseModel):
        schema_version: int = 1
        subject_digest: str
        model_digest: str
        policy_digest: str
        engine: Literal["native"] = "native"
        compiled_sql: str | None
        governed_sql: str | None
        signature: str = ""
        def canonical_bytes(self) -> bytes:   # sorted-key compact JSON, excluding signature

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 70-126
  symbol: `SemanticAuditLedger`
  excerpt: |
    def __init__(self, signer: AbstractKMSSigner | None = None,
                 storage: Callable[[str], Awaitable[None]] | None = None, max_entries: int = 10_000) -> None:
        self.signer: AbstractKMSSigner = signer or LocalHMACSigner()
    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
    async def verify(self, entry: SemanticAuditEntry) -> bool:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 158
  symbol: `postgres_audit_storage`
  excerpt: |
    def postgres_audit_storage(   # "Build an async storage callable that INSERTs entries into Postgres."

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 14
  symbol: import
  excerpt: |
    from parrot.security import AbstractKMSSigner, LocalHMACSigner

## Notes

- The old spec's M7 (`AccountingAuditEntry` + `AccountingAuditLedger`, `FINANCE_AUDIT_MODE=required`) duplicates the ledger mechanics that now exist. Open design point for the revision: a second entry type on the same ledger class, an extension of `SemanticAuditEntry`, or a separate ledger — the existing ledger is typed to `SemanticAuditEntry` and its Postgres sink to one table.
- The semantic ledger keeps SQL text in the entry (`compiled_sql`, `governed_sql`); the old accounting design stored hashes plus a `lineage_ref` and rebuilt lineage, "never inline".
- Line numbers from one `grep -n` of definitions; field list from the wiki page content.
