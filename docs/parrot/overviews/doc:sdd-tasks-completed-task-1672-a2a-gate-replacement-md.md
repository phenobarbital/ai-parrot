---
type: Wiki Overview
title: 'TASK-1672: Replace the A2AServer credential gate with broker calls'
id: doc:sdd-tasks-completed-task-1672-a2a-gate-replacement-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 6 + resolved question (replace the gate). Removes the embedded
  registry +
relates_to:
- concept: mod:parrot.auth.broker
  rel: mentions
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.identity
  rel: mentions
---

# TASK-1672: Replace the A2AServer credential gate with broker calls

**Feature**: FEAT-264 — Unified Credential Broker
**Spec**: `sdd/specs/unified-credential-broker.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1667, TASK-1669, TASK-1671
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 + resolved question (replace the gate). Removes the embedded registry +
`wire_*` sugar from `A2AServer` and routes gating through the shared broker, while keeping
the suspend/consent/resume flow as the A2A renderer. FEAT-263 vertical flows must still
pass (adapter-backed replacement).

---

## Scope

- Remove `wire_jira_resolver`, `wire_fireflies_resolver`, `wire_workiq_resolver` (:539/:571/:613)
  and the embedded `_credential_resolvers` gate in `_try_invoke_with_gate` (:718).
- Route gating through `broker.resolve(...)`; on `NeedsAuth`, reuse `_on_missing_credential`
  (:373) to suspend + return the consent link; keep `resume_from_oauth_callback` (:473).
- Feed `_extract_identity` (:289) through the `CanonicalIdentityMapper` (TASK-1671).
- Keep the `message/send` happy path unchanged; keep `AgentCard.to_dict` untouched.
- Tests: gating goes through broker; `wire_*` gone; suspend/consent/resume unchanged;
  FEAT-263 Fireflies/work.iq A2A tests still pass.

**NOT in scope**: the broker (1667), the core seam (1669), MSAgentSDK surface (1673/1674).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | drop registry+gate+`wire_*`; call broker; keep extract/suspend/resume |
| `packages/ai-parrot-server/tests/integration/test_a2a_fireflies_vertical.py` | MODIFY | adapt to broker-backed gating (regression) |
| `packages/ai-parrot-server/tests/integration/test_a2a_workiq_vertical.py` | MODIFY | adapt to broker-backed gating (regression) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.broker import CredentialBroker                 # TASK-1667
from parrot.auth.credentials import NeedsAuth                    # TASK-1667
from parrot.auth.identity import CanonicalIdentityMapper         # TASK-1671
```

### Existing Signatures to Use
```python
# parrot/a2a/server.py
class A2AServer:                                                 # :50
    def __init__(self, agent, ..., credential_resolvers=None, suspended_store=None, audit_ledger=None)  # :84
    self._credential_resolvers: Dict[str, Any]                  # :134  LIFT to broker
    def _extract_identity(self, message) -> Optional[str]       # :289  KEEP, feed mapper
    def register_credential_resolver(self, provider, resolver)  # :352  generic API
    async def _on_missing_credential(self, ...)                 # :373  becomes NeedsAuth renderer
    async def resume_from_oauth_callback(self, interaction_id, user_input="")  # :473  KEEP
    def wire_jira_resolver / wire_fireflies_resolver / wire_workiq_resolver(...)  # :539/:571/:613  DELETE
    async def _try_invoke_with_gate(self, ...)                  # :718  REPLACE with broker.resolve
```

### Does NOT Exist
- ~~`AgentCard.supportedInterfaces`~~ — intentionally NOT emitted; do not add.
- ~~a broker reference on `A2AServer` today~~ — pass it in via `__init__` in this task.

---

## Implementation Notes
- Keep `__init__` backward-compatible: accept the broker (preferred) and keep
  `credential_resolvers=` as a deprecated shim that builds a broker, so callers migrate
  gradually. Do NOT reintroduce per-provider `wire_*`.
- The A2A `channel` ("a2a:copilot") is passed to the broker for audit context only;
  vault keying uses the canonical identity.

## Acceptance Criteria
- [ ] `wire_*` methods removed; gating routes through `broker.resolve`.
- [ ] Missing credential still suspends + returns a TEXT consent link (no secret).
- [ ] `resume_from_oauth_callback` resumes via nonce as before.
- [ ] FEAT-263 Fireflies + work.iq A2A integration tests pass (regression).
- [ ] `message/send` happy path unchanged; `ruff` clean.

## Agent Instructions
Standard SDD flow. Run the FEAT-263 vertical tests as regression before marking done.

## Completion Note
Implemented. `wire_jira_resolver`, `wire_fireflies_resolver`, `wire_workiq_resolver` removed from A2AServer. `__init__` now accepts `broker: Optional[CredentialBroker]` (preferred) and `identity_mapper: Optional[CanonicalIdentityMapper]`; `credential_resolvers=` dict builds a broker shim for backward compat. `_try_invoke_with_gate` routes through `broker.resolve(provider, channel, user_id, tool_name=tool_name)`, handles `NeedsAuth` by calling `_on_missing_credential(…, auth_url=result.auth_url)`. Broker handles audit internally. `_extract_identity` feeds metadata through mapper when set. All 3 vertical integration test files (jira, fireflies, workiq) updated to use `CredentialBroker` directly. 35 integration tests pass; ruff clean.
