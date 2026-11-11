---
id: FC-004
query_id: Q016
type: read
intent: "Existing semantic audit: entry shape, signing, storage contract, fail-closed mode — reuse vs a separate AccountingAuditEntry."
executed_at: 2026-11-11T22:45:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-004 — `SemanticAuditLedger` already implements the signed, `storage(json_str)`, fail-closed ledger the old spec designed as `AccountingAuditLedger`

## Summary

`parrot/semantic/audit.py` ships `SemanticAuditEntry` (schema_version, entry_id, identity fields,
`subject_digest`, model + `model_digest` + `policy_digest`, tool, `structured_query`, `compiled_sql`,
`governed_sql`, dialect, driver, rls/mask lists, pbac outcome, outcome, row_count, duration, signature)
with `canonical_bytes()` = sorted-key compact JSON excluding `signature`, and `SemanticAuditLedger(signer,
storage, max_entries)`: signs with `AbstractKMSSigner` (default `LocalHMACSigner`), keeps a bounded deque,
forwards `entry.model_dump_json()` to an async `storage` callable, and with `append(..., required=True)`
raises `SemanticExecutionError("audit_unavailable")` when the sink is missing or fails. A Postgres sink
(`postgres_audit_storage`, table `semantic_audit_events`, DDL shipped as package data) exists. The mechanics
match the old M7 one for one; the differences are the entry fields (no `model_hash`/`snapshot_hash`/
`sql_hash`/`lineage_ref`/`assertion_status`/`target`, and it stores raw `user_id` plus SQL text, which the
old spec's entry deliberately did not) and the mode switch (`required` bool per call vs `FINANCE_AUDIT_MODE`).

## Citations

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 14-14
  symbol: `imports`
  excerpt: |
    from parrot.security import AbstractKMSSigner, LocalHMACSigner

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 23-67
  symbol: `SemanticAuditEntry`
  excerpt: |
    class SemanticAuditEntry(BaseModel):
        schema_version: int = 1
        entry_id: str
        user_id: str
        tenant_id: str
        subject_digest: str
        model_digest: str
        policy_digest: str
        engine: Literal["native"] = "native"
        compiled_sql: str | None
        def canonical_bytes(self) -> bytes:

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 70-93
  symbol: `SemanticAuditLedger`
  excerpt: |
    def __init__(self, signer: AbstractKMSSigner | None = None,
                 storage: Callable[[str], Awaitable[None]] | None = None,
                 max_entries: int = 10_000) -> None:
        self.signer: AbstractKMSSigner = signer or LocalHMACSigner()
        self.entries: deque[SemanticAuditEntry] = deque(maxlen=max_entries)
    @property
    def durable(self) -> bool:
        return self.storage is not None

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 95-124
  symbol: `SemanticAuditLedger.append`
  excerpt: |
    async def append(self, entry: SemanticAuditEntry, *, required: bool = False) -> SemanticAuditEntry:
        entry.signature = await self.signer.sign(entry.canonical_bytes())
        self.entries.append(entry)
        if self.storage is None:
            if required:
                raise SemanticExecutionError("audit_unavailable", "Audit storage is not configured", ...)
        try:
            await self.storage(entry.model_dump_json())
        except Exception as exc:
            if required:
                raise SemanticExecutionError("audit_unavailable", "Audit storage failed", ...) from exc

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 126-137
  symbol: `SemanticAuditLedger.verify`
  excerpt: |
    async def verify(self, entry: SemanticAuditEntry) -> bool:
        if not entry.signature:
            return False
        return await self.signer.verify(entry.canonical_bytes(), entry.signature)

- path: `packages/ai-parrot-semantic/src/parrot/semantic/audit.py`
  lines: 158-206
  symbol: `postgres_audit_storage`
  excerpt: |
    def postgres_audit_storage(dsn_or_pool: str | Any, *, table: str = "semantic_audit_events"
    ) -> Callable[[str], Awaitable[None]]:
        sql = (f"INSERT INTO {quoted} (entry_id, created_at, user_id, tenant_id, model, outcome, payload, signature) "
               "VALUES ($1::uuid, $2, $3, $4, $5, $6, $7::jsonb, $8)")

- path: `packages/ai-parrot-semantic/src/parrot/semantic/toolkit.py`
  lines: 91-93
  symbol: `SemanticLayerToolkit.__init__`
  excerpt: |
    self._ledger = SemanticAuditLedger(signer=signer, storage=audit_storage)
    self._audit_required = self._ledger.durable if audit_required is None else bool(audit_required)
    self.logger.info("semantic audit_required=%s (durable sink=%s)", ...)

## Notes

- The ledger is typed to `SemanticAuditEntry`; an accounting entry would need either a generic/duck-typed
  ledger (anything with `canonical_bytes()`, `signature`, `entry_id`, `model_dump_json()`), a subclass, or
  extra optional fields on the existing entry. `postgres_audit_storage` reads `user_id`, `tenant_id`,
  `model`, `outcome` out of the payload, so an accounting entry reusing that sink must carry those keys.
- The default policy differs: semantic audit is required only when a durable sink is configured
  (`audit_required=None` ⇒ `ledger.durable`); the old FEAT-713 spec defaulted to `required` always.
- The in-memory deque retains entries (bounded 10 000); the old spec said "no in-memory retention".
