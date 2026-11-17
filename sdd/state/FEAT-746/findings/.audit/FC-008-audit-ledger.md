---
id: FC-008
query_id: [Q025, Q042]
type: read
intent: "AuditLedger: does a signed append-only ledger exist in code (not just specs)? What does an entry carry and where is it stored?"
executed_at: 2026-10-25T22:44:44Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-008 — AuditLedger exists (parrot/security/audit_ledger.py): KMS/HMAC-signed, append-only, but credential-invocation shaped, in-memory by default, with a pluggable storage coroutine

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
