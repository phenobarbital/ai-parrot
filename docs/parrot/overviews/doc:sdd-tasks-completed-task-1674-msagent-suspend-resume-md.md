---
type: Wiki Overview
title: 'TASK-1674: MSAgentSDK — suspend + auto-resume on consent (proactive delivery)'
id: doc:sdd-tasks-completed-task-1674-msagent-suspend-resume-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 7 (part 2) + resolved question (request creds AND auto-resume;
  no
relates_to:
- concept: mod:parrot.human.suspended_store
  rel: mentions
---

# TASK-1674: MSAgentSDK — suspend + auto-resume on consent (proactive delivery)

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1673
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (part 2) + resolved question (request creds AND auto-resume; no
re-typing). Gives the MSAgentSDK chat surface suspend/resume parity with A2A.

---

## Scope

- On `CredentialRequired`, persist a suspended record (reuse `SuspendedExecutionStore`)
  keyed by nonce, plus a Bot Framework `ConversationReference` for proactive continuation.
- Make the resume triggers re-run the suspended tool and **proactively deliver** the
  result:
  - OAuth/OBO → `signin/verifyState` (:263) / `signin/tokenExchange` (:288) invokes.
  - static key → the OOB `store_key` capture route (added in TASK-1677) calls back.
- Verify the `microsoft-agents` proactive-continue API (spec §8 open question — confirm
  during implementation) and document the chosen call.
- Tests: resume after sign-in invoke; resume after `store_key`; suspended record carries
  the conversation reference; no user re-typing required.

**NOT in scope**: card rendering (TASK-1673); the OOB capture route + example (TASK-1677).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/agent.py` | MODIFY | suspend on `CredentialRequired`; resume in signin invokes; proactive send |
| `packages/ai-parrot-integrations/src/parrot/integrations/msagentsdk/resume.py` | CREATE | conversation-reference store + proactive-resume helper |
| `packages/ai-parrot-integrations/tests/unit/test_msagent_resume.py` | CREATE | resume-trigger tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human.suspended_store import SuspendedExecution, SuspendedExecutionStore  # ai-parrot-server: human/suspended_store.py:33,64
```

### Existing Signatures to Use
```python
# integrations/msagentsdk/agent.py
async def _handle_signin_verify(self, context)     # :263  signin/verifyState (resume trigger: OAuth/OBO)
async def _handle_signin_exchange(self, context)   # :288  signin/tokenExchange (resume trigger: Teams SSO)
async def _send_text(context, text)                # :404  reply helper

# human/suspended_store.py (ai-parrot-server)
class SuspendedExecution(BaseModel):  # :33  interaction_id, session_id, user_id, agent_name, tool_call_id, messages, created_at
class SuspendedExecutionStore:        # :64  key "hitl:suspended:{interaction_id}"
    async def save(self, record, ttl: int) -> None   # :103
    async def load(self, interaction_id) -> Optional[SuspendedExecution]  # :128
    async def delete(self, interaction_id) -> None   # :149
```

### Does NOT Exist
- ~~a chat-path resume trigger today~~ — only A2A has `resume_from_oauth_callback`; this task adds the MSAgentSDK equivalent.
- ~~a stored `ConversationReference` for proactive resume~~ — create the store in `resume.py`.

---

## Implementation Notes
- Reuse `SuspendedExecutionStore` (do NOT invent a new store); add only the conversation
  reference needed for proactive delivery.
- The proactive `continue_conversation` / `process_proactive` API of
  `microsoft-agents-hosting-aiohttp ~=0.9` must be confirmed; keep the SDK import lazy
  (pattern used throughout msagentsdk).

## Acceptance Criteria
- [ ] A static-key/OBO miss suspends; consent completion auto-resumes and proactively delivers the result.
- [ ] `signin/verifyState`/`tokenExchange` and the `store_key` callback both resume correctly.
- [ ] User never re-types the original question.
- [ ] `pytest packages/ai-parrot-integrations/tests/unit/test_msagent_resume.py -v` passes; `ruff` clean.

## Agent Instructions
Standard SDD flow. Confirm the proactive SDK API and record it in the Completion Note.

## Completion Note
*(Agent fills this in when done)*
