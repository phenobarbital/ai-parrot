---
type: Wiki Overview
title: 'TASK-1675: Reconcile audit ledgers + Azure Key Vault signer'
id: doc:sdd-tasks-completed-task-1675-audit-ledger-reconciliation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 8 + resolved questions (canonical = `parrot.security.audit_ledger`;
relates_to:
- concept: mod:parrot.auth.audit
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
---

# TASK-1675: Reconcile audit ledgers + Azure Key Vault signer

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1667
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 + resolved questions (canonical = `parrot.security.audit_ledger`;
pluggable signer with Azure Key Vault backend). Eliminates the two-ledger split.

---

## Scope

- Make `parrot.security.audit_ledger.AuditLedger` canonical. Migrate callers of
  `parrot.auth.audit.AuditLedger.record()` (notably `BFTokenServiceResolver._record_audit`)
  to `AuditLedger.append(...)`; remove/deprecate `parrot/auth/audit.py`.
- Add `AzureKeyVaultSigner(AbstractKMSSigner)` as a production backend; keep
  `LocalHMACSigner` as the dev default.
- Tests: a single ledger is used; `verify()` round-trips an HMAC-signed entry; Azure signer
  is import-guarded (skips cleanly when the SDK/cred is absent).

**NOT in scope**: broker audit-append wiring (already in TASK-1667); surfaces.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/audit_ledger.py` | MODIFY | add `AzureKeyVaultSigner`; canonical entry point |
| `packages/ai-parrot/src/parrot/auth/audit.py` | MODIFY/REMOVE | migrate `.record()` callers; deprecate |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/auth.py` | MODIFY | `_record_audit` → `AuditLedger.append` |
| `packages/ai-parrot/tests/unit/test_audit_reconciliation.py` | CREATE | single-ledger + signer tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.security.audit_ledger import AuditLedger, AuditLedgerEntry, AbstractKMSSigner, LocalHMACSigner  # security/audit_ledger.py:203,79,134,165
```

### Existing Signatures to Use
```python
# parrot/security/audit_ledger.py
class AuditLedgerEntry(BaseModel)            # :79  entry_id,user_id,channel,tool,provider,key_fingerprint,signature,created_at
class AbstractKMSSigner(ABC):               # :134
    async def sign(self, data: bytes) -> str
    async def verify(self, data: bytes, signature: str) -> bool
class LocalHMACSigner(AbstractKMSSigner): __init__(secret: Optional[bytes]=None)  # :165
class AuditLedger: __init__(signer=None, storage=None)  # :203
    async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry  # :245
    async def verify(self, entry_id: str) -> bool  # :314

# parrot/auth/audit.py  (TO MIGRATE)
class AuditLedger: def record(self, entry: AuditEntry) -> None  # :46
@dataclass class AuditEntry(timestamp,user_id,channel,tool,connection,key_fingerprint,action)  # :21
```

### Does NOT Exist
- ~~`AzureKeyVaultSigner`~~ — create it (subclass `AbstractKMSSigner`).
- ~~a single shared ledger today~~ — two exist; this task unifies on the security one.

---

## Implementation Notes
- Keep `AbstractKMSSigner` async; `AzureKeyVaultSigner` uses `azure-keyvault-keys` +
  `azure-identity` (import-guarded; raise a clear error if used without the extra).
- Preserve `key_fingerprint` semantics (SHA-256); do not log raw credential material.

## Acceptance Criteria
- [ ] `parrot.auth.audit` callers re-pointed to `parrot.security.audit_ledger`.
- [ ] `AzureKeyVaultSigner` exists and is import-guarded; `LocalHMACSigner` stays dev default.
- [ ] `verify()` passes for an appended entry.
- [ ] `pytest packages/ai-parrot/tests/unit/test_audit_reconciliation.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
