---
id: FC-012
query_id: Q035
type: grep
intent: "Locate AuditLedger (both brainstorms depend on it) — file list."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-012 — AuditLedger is a signed credential-invocation ledger, not a message audit

## Summary

`class AuditLedger|AuditLedger\(|audit_ledger` matches `parrot/security/audit_ledger.py` (definition, exported from `security/__init__.py`), consumers `parrot/auth/audit.py`, `auth/broker/core.py`, `bots/abstract.py`, `tools/stub_credentialed_tool.py`, `tools/workiq_tool.py`, `ai-parrot-server/parrot/a2a/server.py`, `mcp/principal_guard.py`, `integrations/msagentsdk/{agent,auth,wrapper}.py`, tests `tests/unit/test_audit_ledger.py`, `test_audit_reconciliation.py`, `test_credential_broker.py`. The ledger is **append-only and KMS-signed** (LocalHMAC or Azure Key Vault) but its entry schema is fixed to credentialed tool calls: `user_id, channel, tool, provider, key_fingerprint, signature, created_at` — no sender/receiver/performative/trace_id fields.

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


## Notes

A per-performative audit line (brainstorm §Security) would need a new entry kind or a sibling ledger; `append()` requires `credential_material`.
