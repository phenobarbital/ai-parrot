---
type: feature
base_branch: dev
feature_id: FEAT-788
projects: [ai-parrot, ai-parrot-integrations]
tags: [roost, bugfix, ledger]
discovered_from: issue:d09c6c185547
---
# FEAT-788 — Roost review fixes (attenuation, expected_schema, audit direction)

**Status**: approved · **Parent**: FEAT-747 (local-inter-agent, merged) · **Issue**: `issue:d09c6c185547`

## Problem
The FEAT-747 code review found four defects. One (`cfp` dropping the scorer) and the
`swarm_toolkit` hop seeding / `unknown_agent` mapping are already fixed on `dev`. Three remain:

1. **AC-14 attenuation never applied.** `GrantPolicy.attenuate` has no caller outside `grant.py`.
2. **`expected_schema` dropped.** `RoostEndpoint.query` does `del expected_schema`; no schema
   failure is ever produced, so `AgentSwarmToolkit._ask_via_roost` can never return `schema_error`.
3. **Audit direction keyed on wire direction, not role.** `endpoint.py` records every inbound
   message as `served` and every outbound as `received`. `audit.py` documents `served` = the
   serving agent's side, `received` = the caller's side, so a caller logs its own opener as
   `received` correctly but the reply it receives as `served`, and a server logs its reply as `received`.

## Design
- **M1 audit role.** `RoostAuditLedger.record()` derives the counterpart from the message itself
  (inbound when `msg.sender.name != self_name` → receiver is `self_name`; outbound → first receiver
  or capability filter), independent of `direction`. `RoostEndpoint` picks `direction` by role:
  `received` when this agent is the conversation's `initiator` (engine state), else `served`.
- **M2 expected_schema.** Add `FailureCode.SCHEMA`. `RoostEndpoint.query` validates the answer
  with `jsonschema` (Draft 2020-12, already a core dependency) when `expected_schema` is given and
  raises `RoostFailure(FailureInfo(code=SCHEMA, ...))` on mismatch (or an invalid schema).
  `_ask_via_roost` maps `SCHEMA` → `"schema_error"`.
- **M3 attenuation (v0 scope intersection, per FEAT-747 Q3).** `cfp` sends the requester's
  grant scopes in the ACCEPT content (`{"grant_scopes": [...]}`). The awardee, on an inbound
  ACCEPT, stores `GrantPolicy.attenuate(requester_grant, own config.grant)` per conversation and
  exposes it via `RoostEndpoint.effective_grant(conversation_id)`. `_run_tool` on a conversation
  with an awarded grant refuses (`failure(POLICY)`) a tool outside it.

## Acceptance Criteria
- [ ] AC-1 Caller-side entries (opener + reply) are `received`; server-side entries (inbound opener + its reply) are `served`; receiver fields name the right counterpart.
- [ ] AC-2 `query(expected_schema=...)` raises `RoostFailure` with `FailureCode.SCHEMA` on a non-conforming answer and returns the answer when it conforms.
- [ ] AC-3 `_ask_via_roost` returns `{"status": "schema_error"}` for a SCHEMA failure.
- [ ] AC-4 After an award, the winner's `effective_grant(cid)` is the intersection of requester and awardee scopes; a tool outside it is refused.
- [ ] AC-5 Existing `packages/ai-parrot/tests/roost/` and Matrix crew tests stay green.

## Out of scope
Biscuit token attenuation (FEAT-746 follow-up); `issue:0f5ee739eca8` conversation_id carriage.
