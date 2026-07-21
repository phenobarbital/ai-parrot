---
type: Wiki Overview
title: 'TASK-1667: CredentialBroker + ResolverFactory + signal/config models'
id: doc:sdd-tasks-completed-task-1667-credential-broker-core-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation of the feature (spec §2, §3 Module 1). Provides the surface-agnostic
relates_to:
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
---

# TASK-1667: CredentialBroker + ResolverFactory + signal/config models

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of the feature (spec §2, §3 Module 1). Provides the surface-agnostic
`CredentialBroker`, the `CredentialResolverFactory` (auth_kind → strategy), and the
Pydantic models/signal that every other module consumes. No surface logic here.

---

## Scope

- Add `ProviderCredentialConfig`, `ResolvedCredential`, `NeedsAuth` Pydantic v2 models
  and the surface-neutral `CredentialRequired(provider, auth_url, auth_kind)` exception.
- Implement `CredentialResolverFactory.build(cfg) -> CredentialResolver` mapping
  `auth: obo | oauth2 | static_key | mcp` to a strategy (strategies themselves are
  adapted in TASK-1668; here the factory dispatches and raises clearly on unknown kinds).
- Implement `CredentialBroker`: `register()`, `from_config()`, and
  `async resolve(provider, channel, user_id, **ctx) -> ResolvedCredential | NeedsAuth`.
  On success append to the canonical `AuditLedger`; on `resolver.resolve()==None`, return
  `NeedsAuth(get_auth_url(...))`. Fail closed when no resolver for the provider.
- Unit tests for build/resolve/needsauth/audit and fail-closed.

**NOT in scope**: the tool-loop seam (TASK-1669), strategy adaptation (TASK-1668),
agent wiring (TASK-1670), identity mapping (TASK-1671), surfaces (1672–1674).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/broker.py` | CREATE | `CredentialBroker`, `CredentialResolverFactory` |
| `packages/ai-parrot/src/parrot/auth/credentials.py` | MODIFY | add `ProviderCredentialConfig`, `ResolvedCredential`, `NeedsAuth`, `CredentialRequired` |
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | export the new symbols |
| `packages/ai-parrot/tests/unit/test_credential_broker.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import (
    CredentialResolver, OAuthCredentialResolver, StaticCredentialResolver,
)  # verified: packages/ai-parrot/src/parrot/auth/credentials.py:27,49,81
from parrot.security.audit_ledger import AuditLedger, LocalHMACSigner  # security/audit_ledger.py:203,165
```

### Existing Signatures to Use
```python
# parrot/auth/credentials.py:27
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]  # :31  None == not authorized
    async def get_auth_url(self, channel: str, user_id: str) -> str       # abstract
    async def is_connected(self, channel: str, user_id: str) -> bool      # default: resolve() is not None

# parrot/security/audit_ledger.py:203
class AuditLedger:
    def __init__(self, signer=None, storage=None)                         # :203
    async def append(self, *, user_id, channel, tool, provider, credential_material) -> AuditLedgerEntry  # :245
    async def verify(self, entry_id: str) -> bool                         # :314
```

### Does NOT Exist
- ~~`parrot.auth.broker`~~ — create it in this task.
- ~~`ProviderCredentialConfig` / `ResolvedCredential` / `NeedsAuth`~~ — new in this task.
- ~~a core `CredentialRequired`~~ — only a msagentsdk-local one exists (`integrations/msagentsdk/auth.py:41`); this task creates the canonical core one.

---

## Implementation Notes

### Key Constraints
- async/await throughout; Pydantic v2; `self.logger`.
- `resolve()` returning `None` from a strategy is the documented "not authorized" signal —
  translate to `NeedsAuth`, never raise from the broker itself.
- Secret material lives only on `ResolvedCredential.secret`; never log it (log the
  `key_fingerprint` only). Audit append computes the fingerprint via the ledger.
- `from_config()` must be pure construction (no I/O) so it is callable from
  `AbstractBot.configure()` (TASK-1670).

### References in Codebase
- `parrot/auth/credentials.py` — the ABC + two existing strategies to dispatch to.
- `parrot/a2a/server.py:352` `register_credential_resolver` — the generic registry shape to generalize.

---

## Acceptance Criteria
- [ ] `from parrot.auth.broker import CredentialBroker, CredentialResolverFactory` works.
- [ ] `from parrot.auth.credentials import ProviderCredentialConfig, ResolvedCredential, NeedsAuth, CredentialRequired` works.
- [ ] `resolve()` returns `ResolvedCredential` on success (+ audit appended) and `NeedsAuth` on miss.
- [ ] Adding a provider on an existing auth kind needs only a `ProviderCredentialConfig` (test proves no new code).
- [ ] No resolver for a provider → fail closed (clear error), never a service-identity fallback.
- [ ] `pytest packages/ai-parrot/tests/unit/test_credential_broker.py -v` passes; `ruff check` clean.

---

## Agent Instructions
Standard SDD flow (verify contract first, implement, test, move to completed, update index).

## Completion Note
*(Agent fills this in when done)*
