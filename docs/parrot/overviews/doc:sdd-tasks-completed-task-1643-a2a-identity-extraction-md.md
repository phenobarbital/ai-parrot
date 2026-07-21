---
type: Wiki Overview
title: 'TASK-1643: A2A per-user identity extraction in process_message'
id: doc:sdd-tasks-completed-task-1643-a2a-identity-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec Module **A1**. `A2AServer.process_message` today delegates
relates_to:
- concept: mod:parrot.a2a.models
  rel: mentions
---

# TASK-1643: A2A per-user identity extraction in process_message

**Feature**: FEAT-263 — AI-Parrot ⇄ M365 Copilot via A2A (per-user credentials)
**Spec**: `sdd/specs/copilot-a2a-percredential.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec Module **A1**. `A2AServer.process_message` today delegates
straight to `agent.ask()` with no notion of who the user is. OQ#1 is resolved:
the Copilot low-code A2A connection **does** deliver a verifiable per-user
identity. This task extracts that identity and threads it through
`process_message` as the canonical key (email, consistent with
`TeamsHumanChannel`), so downstream credential lookups (TASK-1644) can key by it.

This is the head of the `server.py` change-chain; TASK-1644/1645 build on it.

---

## Scope

- Add a `_extract_identity(message/request) -> str` seam to `A2AServer` that
  reads the verifiable per-user identity claim from the inbound A2A request and
  maps it to the canonical id (email).
- Thread the resolved `user_id` through `process_message` so it is available to
  the credential gate (TASK-1644).
- **Document in code** exactly where in the A2A payload the identity claim lands
  (the spec requires this — cite the field path).
- Fail closed: if no verifiable identity is present, do NOT fall back to a
  service identity (set up the seam; the actual gate/refusal lands in TASK-1644).

**NOT in scope**: credential resolution, suspend, audit, tool execution.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | add `_extract_identity`; thread `user_id` into `process_message` |
| `packages/ai-parrot-server/tests/unit/test_a2a_identity.py` | CREATE | identity-extraction unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.a2a.models import Message, Task, TaskState, TaskStatus, Part
# verified: packages/ai-parrot/src/parrot/a2a/models.py (Message:99, Task:231)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/a2a/server.py
class A2AServer:                                              # :31
    async def process_message(self, message: Message) -> Task: ...   # :245 — MODIFY
    async def _ask_agent(self, question: str, message: Message) -> Any: ...  # :277

# packages/ai-parrot/src/parrot/a2a/models.py
class Message:                                                # :99
    message_id: str; role: Role; parts: List[Part]
    context_id: Optional[str]; task_id: Optional[str]
    metadata: Optional[Dict[str, Any]]                        # identity claim likely arrives here / in request headers
    def get_text(self) -> str: ...                            # :138
```

### Does NOT Exist  (DO NOT reference)
- ~~`A2AServer.user_id` / `A2AServer._identity`~~ — no identity attr today
- ~~any existing identity extraction in `server.py`~~ — `process_message` (:245) has none
- ~~`message.user` / `message.identity`~~ — not fields on `Message`

---

## Implementation Notes

### Key Constraints
- async; `self.logger` when identity is found / missing.
- Canonical id = email (match `TeamsHumanChannel` convention).
- Do not modify `AgentCard.to_dict` (out of scope; already correct).
- The identity claim may arrive in the JSON-RPC request (headers / params) rather
  than the `Message` body — inspect the actual request in `_handle_jsonrpc`
  (:691) / `_handle_send_message` (:343) and document the real location.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:1270` — `PermissionContext` per-user construction pattern.

---

## Acceptance Criteria
- [ ] `_extract_identity` returns the canonical id from a representative A2A request.
- [ ] `process_message` carries `user_id` through to the (future) credential gate.
- [ ] No service-identity fallback path is introduced.
- [ ] Code comment documents the exact payload field path of the identity claim.
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/unit/test_a2a_identity.py -v`
- [ ] Existing A2A `message/send` happy path unbroken.

---

## Test Specification
```python
async def test_extract_identity_present(): ...        # claim present -> canonical id
async def test_extract_identity_missing(): ...        # absent -> no service-identity fallback
async def test_process_message_threads_user_id(): ... # user_id reaches the gate seam
```

---

## Agent Instructions
Standard SDD flow. Verify the contract against `server.py` before editing — this
file is also touched by in-flight `wip: a2a server + ms agent sdk`; rebase/confirm
current line numbers first.
