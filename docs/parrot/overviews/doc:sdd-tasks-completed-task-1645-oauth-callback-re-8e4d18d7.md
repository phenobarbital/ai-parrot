---
type: Wiki Overview
title: 'TASK-1645: OAuth-callback resume trigger (nonce → resume suspended A2A task)'
id: doc:sdd-tasks-completed-task-1645-oauth-callback-resume-trigger-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **A3**. The existing OAuth callback (`oauth2_routes`)
relates_to:
- concept: mod:parrot.auth.oauth2
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
---

# TASK-1645: OAuth-callback resume trigger (nonce → resume suspended A2A task)

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1644
**Assigned-to**: unassigned

---

## Context

Implements spec Module **A3**. The existing OAuth callback (`oauth2_routes`)
resumes the web/chat session; it does NOT know about suspended A2A tasks. This
task adds the **new resume trigger**: after a successful callback, correlate the
OAuth `state` nonce ⇄ `interaction_id`, load the `SuspendedExecution`, and call
`AbstractBot.resume(session_id, user_input, state)` to finish the A2A task. The
credential is already persisted by the existing
`IntegrationsService.persist_credential` / `VaultTokenSync`; this task only adds
the A2A-resume fan-out.

---

## Scope

- Extend the callback path (`make_oauth2_callback` / `setup_oauth2_routes`) with
  a hook that, when the `state` nonce corresponds to a suspended **A2A** task,
  loads the `SuspendedExecution` and resumes it.
- Add the nonce↔interaction_id correlation lookup (reuse the nonce minted in
  TASK-1644; do not create a new one).
- Call `agent.resume(session_id, user_input, state)` and deliver the tool result
  back over the A2A surface; append the `AuditLedgerEntry` for the now-successful
  credentialed invocation (via the helper from TASK-1644).
- `SuspendedExecutionStore.delete(interaction_id)` on successful resume.
- Graceful handling when the suspended entry has expired (TTL) → re-prompt path.

**NOT in scope**: the web/chat resume (already works), tool verticals (Group B),
the stub tool itself (TASK-1646).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2_routes.py` | MODIFY | add A2A-resume hook on successful callback |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | `resume_from_oauth_callback(nonce, user_input)` entry point |
| `packages/ai-parrot-server/tests/unit/test_a2a_resume_trigger.py` | CREATE | resume/expiry tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human.suspended_store import SuspendedExecution, SuspendedExecutionStore
# verified: ai-parrot-server .../human/suspended_store.py:33,64
from parrot.auth.oauth2 import IntegrationsService    # verified: auth/oauth2/__init__.py:36
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2_routes.py
def make_oauth2_callback(provider_id: str): ...        # :151  -> handler; calls manager.handle_callback(code, state) :170
def setup_oauth2_routes(app, provider_id, callback_path): ...  # :202  (route excluded from auth middleware :216)
async def _handle_web_callback(...): ...               # :74   (existing web/chat resume branch)

# packages/ai-parrot/src/parrot/auth/oauth2/service.py
class IntegrationsService:
    async def persist_credential(self, user_id, provider_id, token_set) -> UsersIntegrationRow: ...  # :289

# packages/ai-parrot-server/src/parrot/human/suspended_store.py
class SuspendedExecutionStore:
    async def load(self, interaction_id: str) -> Optional[SuspendedExecution]: ...   # :128
    async def delete(self, interaction_id: str) -> None: ...                         # :149

# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage: ...  # :3462
```

### Does NOT Exist  (DO NOT reference)
- ~~an existing A2A resume trigger~~ — the callback only resumes web/chat today
- ~~`SuspendedExecutionStore` indexed by nonce~~ — it is keyed by `interaction_id`; YOU add the nonce↔interaction_id map
- ~~`AbstractBot.resume_a2a` / `agent.resume_task`~~ — only `resume(session_id, user_input, state)` exists

---

## Implementation Notes

### Key Constraints
- async; `self.logger` at correlate/resume/expire.
- Reuse the TASK-1644 nonce — no second nonce.
- On expiry (`load` returns None), return a graceful re-prompt, not a 500.
- Mind the package boundary: `oauth2_routes` is core `ai-parrot`; the A2A resume
  entry point is in satellite `ai-parrot-server` — wire via a registered hook/callback,
  not a hard import cycle.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/agent.py:1347,1918` — existing `SuspendedExecutionStore` usage on resume.

---

## Acceptance Criteria
- [ ] Callback with a valid A2A nonce loads the `SuspendedExecution` and calls `agent.resume(...)`.
- [ ] Tool result is delivered over A2A; `AuditLedger.append` recorded.
- [ ] Suspended entry deleted on success.
- [ ] Expired entry → graceful re-prompt (no crash).
- [ ] Web/chat callback path unchanged.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/unit/test_a2a_resume_trigger.py -v`

---

## Test Specification
```python
async def test_callback_nonce_resumes_task(): ...
async def test_resume_deletes_suspended_entry(): ...
async def test_resume_after_ttl_expiry(): ...
async def test_web_callback_unchanged(): ...
```

---

## Agent Instructions
Standard SDD flow. TASK-1644 must be in `completed/`. Re-verify line numbers in
both `oauth2_routes.py` and `server.py` (WIP file) before editing.

### Completion Note
Implemented the A2A OAuth resume trigger (FEAT-260 / TASK-1645):
- `register_a2a_resume_hook(app, hook)` added to `oauth2_routes.py` — stores
  an async callable under `app["a2a_oauth_resume_hook"]`. Package boundary intact:
  no import of `A2AServer` (satellite) from core `ai-parrot`.
- `make_oauth2_callback` extended with A2A fan-out: after successful token exchange,
  if `state_payload["a2a_interaction_id"]` is present, the hook is called. Exceptions
  in the hook are logged but do not crash the callback (credential already persisted).
- `A2AServer.resume_from_oauth_callback` (already wired in TASK-1644) serves as the
  hook implementation. It loads the `SuspendedExecution`, calls `agent.resume()`,
  and deletes the suspended entry. Fallback to `agent.ask()` when agent lacks `resume`.
- 9/9 unit tests pass. Ruff clean.
