---
type: Wiki Overview
title: 'TASK-1609: Mode B — document & test the /ws/userinfo structured-output contract'
id: doc:sdd-tasks-completed-task-1609-document-test-ws-userinfo-contract-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `session_id`-keyed structured-output channel (`/ws/userinfo`) is the
---

# TASK-1609: Mode B — document & test the /ws/userinfo structured-output contract

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1607
**Assigned-to**: unassigned

---

## Context

The `session_id`-keyed structured-output channel (`/ws/userinfo`) is the
delivery surface for Mode B (and A/C) structured payloads. The SvelteKit
frontend guide already assumes it. Make it a documented, tested first-class
contract. (Spec §4 M-B2.)

---

## Scope

- Document the contract: a browser subscribes on `/ws/userinfo` with
  `{"type":"subscribe","content":{"channel": <session_id>}}`; the backend
  delivers `StructuredOutputMessage`-shaped JSON (`{type, session_id, payload,
  turn_id}`) on that channel; types ∈ {chart, data, canvas, tool_call}.
- Add an integration test proving end-to-end delivery keyed by `session_id`,
  including the cross-worker case via the Redis transport (FakeRedis acceptable).
- Update `docs/frontend/liveavatar-fullmode-sveltekit-guide.md` to reference the
  exact subscribe message + envelope (align with code).

**NOT in scope**: the publisher (TASK-1607); transport rename (TASK-1603).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/frontend/liveavatar-fullmode-sveltekit-guide.md` | MODIFY | document subscribe + envelope |
| `docs/api-reference/` or `docs/API_ENDPOINTS.md` | MODIFY | add `/ws/userinfo` structured-output contract |
| `packages/ai-parrot-server/tests/handlers/test_ws_userinfo_structured.py` | CREATE | session_id-keyed delivery incl. cross-worker |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures
```python
# handlers/user.py  UserSocketManager
#   route /ws/userinfo (registered in app setup; app['user_socket_manager'])
#   subscribe handler: msg_type == 'subscribe' -> _subscribe_to_channel(ws, channel)  (:667/:323)
#   broadcast_to_channel(channel, message, exclude_ws)  (:357, in-process)
# liveavatar/output_transport.py  run_output_subscriber → local broadcast (cross-process bridge)
# liveavatar/models.py  StructuredOutputMessage{type, session_id, payload, turn_id}  (post TASK-1599)
```

### Does NOT Exist
- ~~a REST endpoint that returns structured outputs~~ — they are pushed over `/ws/userinfo`
- ~~`UserSocketManager.broadcast_to_channel` reaching other processes by itself~~ — only via the Redis transport

---

## Implementation Notes
- The doc must match the real subscribe message format in `user.py` exactly.
- Keep the envelope description consistent with `StructuredOutputMessage`.

---

## Acceptance Criteria
- [ ] Contract documented (subscribe message + envelope + type enum) in the frontend guide and API docs.
- [ ] Test: a payload published for `session_id=X` reaches only the WS subscribed to channel `X`, including when published from a different worker (FakeRedis).
- [ ] Docs match code (no drift).

---

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
