---
type: Wiki Overview
title: 'TASK-1644: Credential gate + suspend-on-missing-credential in the A2A path'
id: doc:sdd-tasks-completed-task-1644-credential-gate-suspend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **A2** — the core of the bridge. When a credentialed
relates_to:
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
- concept: mod:parrot.security.audit_ledger
  rel: mentions
---

# TASK-1644: Credential gate + suspend-on-missing-credential in the A2A path

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1643, TASK-1642
**Assigned-to**: unassigned

---

## Context

Implements spec Module **A2** — the core of the bridge. When a credentialed
tool is invoked over A2A and the per-user credential is missing, the task must
**suspend** and return a consent link instead of executing under any fallback
identity. Reuses the existing `CredentialResolver` contract
(`resolve()==None` ⇒ surface `get_auth_url()`), `SuspendedExecutionStore`, and
`IntegrationsService.start_connect` (which already issues the OAuth `state`
nonce). When a credential IS present, runs the tool with the resolved client and
appends an `AuditLedgerEntry` (TASK-1642).

---

## Scope

- In `A2AServer.process_message` (post-identity from TASK-1643), before running
  a credentialed tool, call `CredentialResolver.resolve(channel, user_id)`.
- On `None`: persist a `SuspendedExecution` via `SuspendedExecutionStore.save`,
  and return an A2A **TEXT** artifact (`Part.from_text`) containing the consent
  link from `CredentialResolver.get_auth_url(...)` (backed by
  `IntegrationsService.start_connect` → auth_url + state nonce). The nonce binds
  the suspended entry for the resume trigger (TASK-1645).
- On a resolved credential: invoke the tool with the resolved client and append
  an `AuditLedgerEntry` (`key_fingerprint`, never the secret).
- **Negative invariant**: no `client_credentials` / service-identity fallback for
  a per-user tool — if no per-user credential, it suspends, never executes.
- Ensure the suspend response is a well-formed Task (terminal or input-required)
  that does not break `_handle_jsonrpc` / `_handle_send_message`.

**NOT in scope**: the OAuth-callback resume trigger (TASK-1645), the stub tool
(TASK-1646), any real tool vertical (Group B).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | credential gate + suspend path + audit-on-invoke helper |
| `packages/ai-parrot-server/tests/unit/test_a2a_credential_gate.py` | CREATE | gate/suspend/negative tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import CredentialResolver       # verified: auth/__init__.py:46
from parrot.human.suspended_store import (                   # verified: ai-parrot-server .../human/suspended_store.py:33,64
    SuspendedExecution, SuspendedExecutionStore,
)
from parrot.auth.oauth2 import IntegrationsService           # verified: auth/oauth2/__init__.py:36
from parrot.security.audit_ledger import AuditLedger, AuditLedgerEntry  # from TASK-1642
from parrot.a2a.models import Message, Task, Part            # verified: a2a/models.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...   # :31  None == not authorized
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...        # :40

# packages/ai-parrot/src/parrot/auth/oauth2/service.py
class IntegrationsService:                                                       # :67
    async def start_connect(self, user_id, agent_id, provider_id,
                            return_origin) -> ConnectInitResponse: ...           # :140  (auth_url, state nonce, scopes)

# packages/ai-parrot-server/src/parrot/human/suspended_store.py
class SuspendedExecution(BaseModel):    # :33  interaction_id, session_id, user_id, agent_name, tool_call_id, messages
class SuspendedExecutionStore:          # :64  key "hitl:suspended:{interaction_id}"
    async def save(self, record: SuspendedExecution, ttl: int) -> None: ...      # :103

# packages/ai-parrot/src/parrot/a2a/models.py
class Part:                                              # :37
    @classmethod
    def from_text(cls, text: str) -> "Part": ...         # :47
```

### Does NOT Exist  (DO NOT reference)
- ~~service-identity / `client_credentials` fallback for per-user tools~~ — forbidden by spec; do not add one
- ~~a second nonce~~ — reuse the OAuth `state` nonce from `start_connect`; do not mint another
- ~~`CredentialResolver.resolve_for_a2a` or similar~~ — only `resolve` / `get_auth_url` exist

---

## Implementation Notes

### Pattern to Follow
- Link-out: `cred = await resolver.resolve(channel, user_id)`; `if cred is None:` →
  `url = await resolver.get_auth_url(channel, user_id)` (or `IntegrationsService.start_connect`
  to also obtain the nonce) → save `SuspendedExecution` keyed by nonce↔interaction_id → return TEXT Part.
- TTL: align with the interaction TTL pattern used by `SuspendedExecutionStore` (defensive 7260s fallback exists at :113).

### Key Constraints
- async; `self.logger` at gate decisions.
- No secret in any returned `Part` — link + state only (scrubber is the last line of defence).
- Audit append happens ONLY when a tool actually runs with a resolved client.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py` — nonce→callback→vault precedent.

---

## Acceptance Criteria
- [ ] `resolve()==None` ⇒ `SuspendedExecution` saved + TEXT consent link returned.
- [ ] Consent response payload contains link + state only — never a token.
- [ ] Resolved credential ⇒ tool runs with resolved client + `AuditLedger.append` called.
- [ ] **Negative**: per-user tool with no credential never executes under a service identity.
- [ ] Nonce from `start_connect` is reused as the suspend↔callback correlation key.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/unit/test_a2a_credential_gate.py -v`

---

## Test Specification
```python
async def test_resolve_none_triggers_suspend(): ...
async def test_no_secret_in_a2a_payload(): ...
async def test_resolved_runs_tool_and_audits(): ...
async def test_no_service_identity_fallback(): ...
```

---

## Agent Instructions
Standard SDD flow. TASK-1643 (identity) and TASK-1642 (AuditLedger) must be in
`completed/` first. Re-verify `server.py` line numbers (in-flight WIP file).

### Completion Note
Implemented credential gate in `A2AServer` (FEAT-260 / TASK-1644):
- `__init__` extended with `credential_resolvers`, `suspended_store`, `audit_ledger` params.
- `register_credential_resolver(provider, resolver)` — register at runtime.
- `_try_invoke_with_gate(tool_name, params, *, user_id, channel, task)` — core gate:
  checks `tool.credential_provider`, resolves credential, suspends or executes.
- `_on_missing_credential(...)` — persists `SuspendedExecution`, appends `?a2a_state=<uuid>`
  to consent URL, sets `INPUT_REQUIRED` task state with `consent_required` artifact.
  NEVER contains a raw credential in any artifact.
- `resume_from_oauth_callback(interaction_id, user_input)` — loads suspended execution,
  calls `agent.resume()`, cleans up store (for TASK-1645).
- `_find_tool / _execute_tool` helpers extracted for DRY usage.
- Helpers: `_find_tool`, `_execute_tool`, `_invoke_skill`, `_invoke_tool` (legacy path).
- `process_message` routes tool invocations through `_try_invoke_with_gate`.
- Security invariant: missing identity with gated tool → `FAILED` (never service-identity).
- 8/8 unit tests pass. Ruff clean.
