---
id: F006
query_id: Q006, [Q025, Q042]
type: read
intent: "AuditLedger: does a signed append-only ledger exist in code (not just specs)? What does an entry carry and where is it stored?"
executed_at: 2026-10-25T22:44:44Z
duration_ms: 0
parent_id: null
depth: 2
merged_from: FC-008, FW-007
lane_origin: FC-008-audit-ledger, FW-007-audit-ledger-exists
---

# F006 — AuditLedger exists (parrot/security/audit_ledger.py): KMS/HMAC-signed, append-only, but credential-invocation shaped, in-memory by default, with a pluggable storage coroutine

## Summary

The canonical ledger is `parrot.security.audit_ledger.AuditLedger` (FEAT-260/264). `AuditLedgerEntry` fields: `entry_id, user_id, channel, tool, provider, key_fingerprint, signature, created_at`, with `canonical_bytes()` for signing. Signers: `AbstractKMSSigner` → `LocalHMACSigner`, `AzureKeyVaultSigner`. `AuditLedger(signer=None, storage=None)` keeps `self._entries: Dict[str, AuditLedgerEntry]` in memory and accepts an optional storage coroutine; the public API is only `append(*, user_id, channel, tool, provider, credential_material)` and `verify(entry_id)` (no update/delete). It is wired into `A2AServer` through `CredentialBroker(audit_ledger=...)` (FC-001). `parrot/auth/audit.py` is a DEPRECATED predecessor. The entry schema has no capability id, args digest, policy applied, data classes, result digest or cost — the brainstorm's "served ledger" record is a superset that needs a new entry type (or generic payload) and a durable backend. Separately, `ai-parrot-server` `parrot/autonomous/ledger.py` has an append-only `EventLedger` with `PostgresLedgerBackend` (not read).

## Citations

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 1-18
  symbol: module docstring
  excerpt: |
    """Append-only, KMS-signed credential-invocation ledger (FEAT-260 / TASK-1642).
    Append-only semantics are enforced by the public API: :meth:`AuditLedger.append`
    and :meth:`AuditLedger.verify` are the only entry-points; there is no
    update or delete.
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 80-105
  symbol: `AuditLedgerEntry`
  excerpt: |
    class AuditLedgerEntry(BaseModel):
        entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        user_id: str
        channel: str
        tool: str
        provider: str
        key_fingerprint: str
        signature: str = ""
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 135-154
  symbol: `AbstractKMSSigner.sign`, `verify`
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 166-199
  symbol: `LocalHMACSigner`, `AzureKeyVaultSigner`
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 296-335
  symbol: `AuditLedger.__init__`
  excerpt: |
    class AuditLedger:
        """Append-only, KMS-signed credential-invocation ledger.
        Entries are stored in-memory by default.  An optional *storage* backend
        def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None) -> None:
            self._entries: Dict[str, AuditLedgerEntry] = {}
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 338-346
  symbol: `AuditLedger.append`
  excerpt: |
    async def append(self, *, user_id: str, channel: str, tool: str, provider: str,
                     credential_material: Any) -> AuditLedgerEntry:
- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 407-444
  symbol: `AuditLedger.verify`, `get_entry`, `entry_count`
- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  lines: 1-4
  symbol: module docstring (deprecated)
  excerpt: |
    """DEPRECATED: Use parrot.security.audit_ledger instead.
- path: `packages/ai-parrot/src/parrot/auth/audit.py`
  lines: 65
  symbol: `AuditLedger` (deprecated)
- path: `packages/ai-parrot-server/src/parrot/autonomous/ledger.py`
  lines: 12
  symbol: `PostgresLedgerBackend` (docstring mention)
  excerpt: |
    - PostgresLedgerBackend: Postgres append-only implementation.
- path: `packages/ai-parrot-server/src/parrot/autonomous/ledger.py`
  lines: 247
  symbol: `EventLedger` contract
  excerpt: |
    All writes are append-only. Implementations MUST guarantee a

## Notes

The msagentsdk integration also consumes the ledger (`integrations/msagentsdk/auth.py:32`). `observability/recorders/run_ledger.py` exists (not read) — possibly a usage ledger. [cross-lane: type=wiki_query, intent="run ledger recorder" to see if it records per-call cost]


<!-- merged from FW-007 -->

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

- [citation-check: stale] packages/ai-parrot/src/parrot/security/audit_ledger.py — `sign`/`verify`/`__init__` are ambiguous (defined on AbstractKMSSigner 143/154, LocalHMACSigner 183/187, AzureKeyVaultSigner 253/269, AuditLedger.__init__ 327); the cited line ranges disambiguate, bare symbol names do not.
