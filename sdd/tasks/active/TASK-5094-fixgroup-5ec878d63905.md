# TASK-5094: Roost review fixes — audit role, expected_schema, award attenuation

**Feature**: FEAT-788 fixgroup-5ec878d63905
**Spec**: `sdd/specs/fixgroup-5ec878d63905.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:d09c6c185547`

## Context
Implements M1–M3 of the spec (remaining limbs of the FEAT-747 review issue).

## Scope
- M1: `RoostAuditLedger.record()` receiver derivation independent of `direction`; endpoint chooses direction by initiator role.
- M2: `FailureCode.SCHEMA`; `query()` validates against `expected_schema`; swarm status map `SCHEMA → schema_error`.
- M3: ACCEPT carries requester `grant_scopes`; awardee stores attenuated grant; `effective_grant()`; `_run_tool` enforces it.

**NOT in scope**: Biscuit attenuation; conversation_id carriage on ask_agent.

## Files to Modify
- `packages/ai-parrot/src/parrot/roost/audit.py`
- `packages/ai-parrot/src/parrot/roost/endpoint.py`
- `packages/ai-parrot/src/parrot/roost/performatives.py`
- `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
- `packages/ai-parrot/tests/roost/test_review_fixes_788.py` (new)

## Codebase Contract
- `parrot.roost.grant.GrantPolicy.attenuate(requester, awardee) -> InterAgentGrant` (grant.py:39)
- `parrot.roost.protocols.ConversationState.initiator: AgentAddress` (protocols.py:59)
- `RoostEndpoint.query(..., expected_schema: Optional[dict])` (endpoint.py:492), `cfp` (endpoint.py:563), `_on_message` (endpoint.py:168), `_deliver_outbound` (endpoint.py:337), `_run_tool`
- `RoostAuditLedger.record(msg, *, direction, self_name)` (audit.py:116)
- Does NOT exist: `FailureCode.SCHEMA`, `RoostEndpoint.effective_grant`.

## Acceptance Criteria
Spec AC-1..AC-5.

## Validation Commands
```bash
PYTHONPATH=$PWD/packages/ai-parrot/src:$PWD/packages/ai-parrot-integrations/src pytest packages/ai-parrot/tests/roost -q
ruff check packages/ai-parrot/src/parrot/roost packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py
```

## Completion Note
