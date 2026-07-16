---
type: Wiki Overview
title: 'TASK-1646: Stub credentialed tool + end-to-end bridge proof (v1 acceptance)'
id: doc:sdd-tasks-completed-task-1646-stub-tool-e2e-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **A5** — the operator-chosen **tool-agnostic** v1
  proof.
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.stub_credentialed_tool
  rel: mentions
---

# TASK-1646: Stub credentialed tool + end-to-end bridge proof (v1 acceptance)

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1642, TASK-1644, TASK-1645
**Assigned-to**: unassigned

---

## Context

Implements spec Module **A5** — the operator-chosen **tool-agnostic** v1 proof.
A minimal stub/echo tool that declares a credential requirement lets us validate
the entire bridge (task → suspend → consent link → simulated callback → vault →
resume → result → audit) without any external IdP. This is what the v1
acceptance criteria are written against; the real verticals (jira/fireflies/
work-iq) are gated Group B tasks.

---

## Scope

- Implement a minimal credentialed **stub tool** (e.g. echoes its input) that
  declares it needs a per-user credential for a `provider="stub"`.
- Provide a fake/static `CredentialResolver` for `provider="stub"` whose
  `resolve` returns `None` until a simulated callback persists a credential.
- Write the **integration test** exercising the full happy path through the
  bridge (TASK-1643/1644/1645) plus a TTL-expiry path.
- Assert the AuditLedger entry is written with `key_fingerprint` and no secret.

**NOT in scope**: any real IdP, jira/fireflies/work-iq (Group B), modifying the
bridge logic (that is TASK-1644/1645).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/stub_credentialed_tool.py` | CREATE | minimal credentialed stub tool |
| `packages/ai-parrot-server/tests/integration/test_a2a_bridge_e2e.py` | CREATE | full task→suspend→callback→resume→audit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.tools.abstract import AbstractTool   # verified: packages/ai-parrot/src/parrot/tools/abstract.py:98
from parrot.auth.credentials import CredentialResolver, StaticCredentialResolver
# verified: auth/__init__.py:46-48
from parrot.security.audit_ledger import AuditLedger   # from TASK-1642
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/abstract.py
class AbstractTool(EventEmitterMixin, ABC):    # :98
    # output scrubbing happens once at the tool-output boundary (:625) —
    # the stub tool benefits from this automatically; do NOT re-scrub.

# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...  # :31
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...       # :40
```

### Does NOT Exist  (DO NOT reference)
- ~~`parrot.tools.stub_credentialed_tool`~~ — you are creating it
- ~~a built-in test credentialed tool~~ — none exists; create the stub
- ~~`@tool` auto-credential decorator~~ — credential need is declared explicitly, not via a magic decorator

---

## Implementation Notes

### Pattern to Follow
- Follow an existing simple tool under `packages/ai-parrot/src/parrot/tools/` for
  the `AbstractTool` subclass shape (name, description, args_schema, `_execute`/`run`).
- The integration test drives `A2AServer.process_message` with a fake redis
  (`SuspendedExecutionStore`) and a fake resolver, then simulates the OAuth
  callback to trigger `resume_from_oauth_callback`.

### Key Constraints
- async; Pydantic args schema; `self.logger`.
- The stub must NOT emit a secret in its output (relies on the scrubber seam).

### References in Codebase
- `packages/ai-parrot/tests/test_a2a_tools.py` — existing A2A tool test patterns.

---

## Acceptance Criteria  (these ARE the v1 spec acceptance criteria)
- [ ] `test_stub_end_to_end` passes: task → suspend (TEXT consent link, no secret)
      → simulated callback → vault persist → resume → tool result → audit entry.
- [ ] Audit entry has `key_fingerprint`, never the secret.
- [ ] TTL-expiry path returns a graceful re-prompt.
- [ ] Negative: stub tool with no credential never executes under a service identity.
- [ ] `from parrot.tools.stub_credentialed_tool import StubCredentialedTool` works.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/integration/test_a2a_bridge_e2e.py -v`

---

## Test Specification
```python
async def test_stub_end_to_end(): ...
async def test_resume_after_ttl_expiry(): ...
async def test_no_service_identity_fallback(): ...
```

---

## Agent Instructions
Standard SDD flow. All of TASK-1642/1644/1645 must be in `completed/`. This task
closes out the v1 (Group A) acceptance criteria from spec §5.

### Completion Note
Implemented the v1 e2e bridge proof (FEAT-260 / TASK-1646):
- `StubCredentialedTool` in `parrot/tools/stub_credentialed_tool.py`: extends `AbstractTool`,
  declares `credential_provider = "stub"`, implements `_execute(message, metadata) -> str`
  (echo pattern). Importable as `from parrot.tools.stub_credentialed_tool import StubCredentialedTool`.
- 9/9 integration tests pass covering: full happy-path (suspend → callback → resume →
  second call → COMPLETED + audit entry), TTL-expiry graceful path, no-service-identity
  negative tests, stub tool import and execution. Ruff clean.
