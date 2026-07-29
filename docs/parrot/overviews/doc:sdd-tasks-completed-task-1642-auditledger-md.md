---
type: Wiki Overview
title: 'TASK-1642: AuditLedger — append-only, KMS-signed credential-invocation ledger'
id: doc:sdd-tasks-completed-task-1642-auditledger-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **A4**. The brainstorm asserted an `AuditLedger` as
  an
relates_to:
- concept: mod:parrot.security
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
---

# TASK-1642: AuditLedger — append-only, KMS-signed credential-invocation ledger

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module **A4**. The brainstorm asserted an `AuditLedger` as an
invariant, but research found **it does not exist anywhere** in the codebase
(zero matches for `AuditLedger` / `key_fingerprint`). The operator confirmed it
is in scope as a **full append-only, KMS-signed** ledger. It records a
`key_fingerprint` (never the secret) for every credentialed tool invocation and
is wired into the A2A credential path (TASK-1644 / TASK-1645) at invocation time.

This task is greenfield and shares no files with the A2A bridge tasks, so it can
be built in parallel.

---

## Scope

- Implement `AuditLedgerEntry` (Pydantic v2) and `AuditLedger` in a new module.
- `AuditLedger.append(entry)` persists an entry; `AuditLedger.verify(entry_id)`
  re-checks the KMS signature.
- Derive `key_fingerprint` as a stable hash of the credential material (never
  store or log the raw secret).
- Sign each entry's canonical bytes via a KMS abstraction; provide a local-dev
  signing fallback behind the same interface (decision: pick the signing
  primitive here — see Open Questions in spec §7).
- Append-only semantics: no update/delete API.

**NOT in scope**: A2A wiring (TASK-1644/1645), any tool implementation, the
identity extraction (TASK-1643).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/security/audit_ledger.py` | CREATE | `AuditLedgerEntry` + `AuditLedger` (append/verify, KMS) |
| `packages/ai-parrot/src/parrot/security/__init__.py` | MODIFY | export `AuditLedger`, `AuditLedgerEntry` (create dir/file if missing) |
| `packages/ai-parrot/tests/unit/test_audit_ledger.py` | CREATE | unit tests |

> Verify whether `packages/ai-parrot/src/parrot/security/` exists; the core
> `parrot/security/` package is referenced in CONTEXT but confirm before placing.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field   # used throughout the codebase
```

### Existing Signatures to Use
```python
# Target data shape (from spec §2 Data Models) — implement this:
class AuditLedgerEntry(BaseModel):
    entry_id: str
    user_id: str            # canonical identity (email)
    channel: str            # e.g. "a2a:copilot"
    tool: str
    provider: str           # "jira" | "o365" | "work-iq" | "fireflies" | "stub"
    key_fingerprint: str    # hash of credential — NEVER the secret
    signature: str          # KMS signature over canonical bytes
    created_at: datetime
```

### Does NOT Exist  (confirmed via grep 2026-06-26 — DO NOT import these)
- ~~`parrot.security.audit_ledger.AuditLedger`~~ — you are creating it
- ~~`AuditLog`~~, ~~`audit_ledger` module~~, ~~any existing `key_fingerprint`~~ — none exist
- Do not assume a KMS client is already wired — introduce the abstraction here.

---

## Implementation Notes

### Key Constraints
- async throughout (`async def append`, `async def verify`).
- Pydantic v2 models; `self.logger` at append/verify.
- NEVER log or persist the raw credential — only `key_fingerprint`.
- Append-only: do not expose mutate/delete.
- KMS signing behind an injectable interface so the backend can be swapped and a
  local-dev signer used in tests.

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/oauth2/persistence.py` — async persistence pattern to mirror.

---

## Acceptance Criteria

- [ ] `from parrot.security.audit_ledger import AuditLedger, AuditLedgerEntry` works.
- [ ] `append` then `verify` round-trips a valid signature.
- [ ] Entry carries `key_fingerprint`, never the raw secret (negative test).
- [ ] No update/delete API exposed (append-only).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/test_audit_ledger.py -v`
- [ ] `ruff check` clean on the new module.

---

## Test Specification
```python
# packages/ai-parrot/tests/unit/test_audit_ledger.py
import pytest
from parrot.security.audit_ledger import AuditLedger, AuditLedgerEntry

class TestAuditLedger:
    async def test_append_then_verify(self): ...
    async def test_fingerprint_not_secret(self): ...   # entry never contains the raw token
    def test_no_mutation_api(self): ...                # append-only
```

---

## Agent Instructions
Standard SDD flow: read the spec §2/§3/§6, verify the contract, set index status
to in-progress, implement, run tests, move to `completed/` + update the per-spec
index on completion.

### Completion Note
Implemented `AuditLedgerEntry` (Pydantic v2) and `AuditLedger` in
`packages/ai-parrot/src/parrot/security/audit_ledger.py`. The signer
abstraction (`AbstractKMSSigner`) allows swapping in a managed KMS;
`LocalHMACSigner` (HMAC-SHA256) is the local-dev/test fallback. The
`derive_key_fingerprint` function hashes credential material with SHA-256.
Exported from `parrot.security.__init__`. Append-only: no update/delete API.
18/18 unit tests pass. Ruff clean.
