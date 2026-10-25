---
id: F009
query_id: Q035, Q006
type: grep, wiki_page
intent: "Locate AuditLedger (both brainstorms depend on it) — file list."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-012, FW-007
---

# F009 — AuditLedger is a signed credential-invocation ledger, not a message audit

## Summary

**[FC-012] AuditLedger is a signed credential-invocation ledger, not a message audit** — `class AuditLedger|AuditLedger\(|audit_ledger` matches `parrot/security/audit_ledger.py` (definition, exported from `security/__init__.py`), consumers `parrot/auth/audit.py`, `auth/broker/core.py`, `bots/abstract.py`, `tools/stub_credentialed_tool.py`, `tools/workiq_tool.py`, `ai-parrot-server/parrot/a2a/server.py`, `mcp/principal_guard.py`, `integrations/msagentsdk/{agent,auth,wrapper}.py`, tests `tests/unit/test_audit_ledger.py`, `test_audit_reconciliation.py`, `test_credential_broker.py`. The ledger is **append-only and KMS-signed** (LocalHMAC or Azure Key Vault) but its entry schema is fixed to credentialed tool calls: `user_id, channel, tool, provider, key_fingerprint, signature, created_at` — no sender/receiver/performative/trace_id fields.

**[FW-007] AuditLedger exists (security/audit_ledger.py): append-only, KMS-signed, but scoped to credentialed tool invocations over the A2A bridge; in-memory store** — `security/audit_ledger.py` (FEAT-260 / TASK-1642, reconciled in TASK-1675) defines `AuditLedgerEntry` (with `canonical_bytes()` for signing; carries `key_fingerprint` = sha256 of credential material, never the raw credential), `AbstractKMSSigner.sign/verify`, `LocalHMACSigner`, `AzureKeyVaultSigner`, and `AuditLedger(signer, storage)` with `append()` / `verify(entry_id)` / `get_entry` / `entry_count` — 'there is no update or delete'. Its documented scope is 'every credentialed tool invocation over the A2A bridge'; `entry_count` says 'in the in-memory store', so persistence is backend-injected via `storage`. `auth/audit.py` is DEPRECATED in favour of `parrot.security.audit_ledger`. A separate semantic-layer audit ledger (TASK-4474, active, 'signed semantic audit ledger + Postgres sink') is being built by a parallel feature. The brainstorm's assumption 'the signed, append-only AuditLedger already defined for ai-parrot' is CONFIRMED structurally, but its entry shape is credential-centric (not caller/capability/policy/data-class/result-digest) and would need a new entry type or a sibling ledger.


## Citations

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 80-107
  symbol: `AuditLedgerEntry`
  excerpt: |
    class AuditLedgerEntry(BaseModel):
        entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
        user_id: str
        channel: str          # e.g. "a2a:copilot"
        tool: str
        provider: str
        key_fingerprint: str
        signature: str = ""
        created_at: datetime

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 135-160
  symbol: `AbstractKMSSigner`
  excerpt: |
    async def sign(self, data: bytes) -> str:  async def verify(self, data: bytes, signature: str) -> bool:

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 296-336
  symbol: `AuditLedger.__init__`
  excerpt: |
    def __init__(self, signer: Optional[AbstractKMSSigner] = None, storage: Optional[Any] = None):
        self._entries: Dict[str, AuditLedgerEntry] = {}   # in-memory

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 338-406
  symbol: `AuditLedger.append`
  excerpt: |
    async def append(self, *, user_id: str, channel: str, tool: str, provider: str, credential_material: Any) -> AuditLedgerEntry:
        key_fingerprint = derive_key_fingerprint(credential_material)
        entry.signature = await self._signer.sign(canonical)
        if self._storage is not None: await self._storage(entry.model_dump_json())

- path: `packages/ai-parrot/src/parrot/security/audit_ledger.py`
  lines: 407-444
  symbol: `AuditLedger.verify / get_entry / entry_count`
  excerpt: |
    async def verify(self, entry_id: str) -> bool:

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

[FC-012] A per-performative audit line (brainstorm §Security) would need a new entry kind or a sibling ledger; `append()` requires `credential_material`.

[FW-007] `[cross-lane: type=read, intent=audit_ledger.py AuditLedgerEntry field list + the storage protocol signature to judge reuse for performative-level audit lines]`. Also `auth/broker/core.py::CredentialBroker` (FEAT-264) is the surface that writes to this ledger.
