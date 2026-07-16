---
type: Wiki Overview
title: 'TASK-1607: Mode B — backend output-bifurcation helper'
id: doc:sdd-tasks-completed-task-1607-fullmode-output-bifurcation-helper-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Mode B (FULL mode, FEAT-248) currently leaves all output bifurcation to the
---

# TASK-1607: Mode B — backend output-bifurcation helper

**Feature**: FEAT-249 — LiveAvatar + Voice Consolidation
**Spec**: `sdd/specs/liveavatar-voice-consolidation.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1603, TASK-1604
**Assigned-to**: unassigned

---

## Context

Mode B (FULL mode, FEAT-248) currently leaves all output bifurcation to the
frontend. Add an **opt-in, frontend-overridable** backend path: when a FULL-mode
session is active for a `session_id`, `AgentTalk` streaming flattens speakable
text per sentence (returned to the client to forward as `avatar.speak_text`) and
publishes structured payloads to `/ws/userinfo` via the kept Redis transport.
(Spec §2 Mode B, §4 M-B1.)

---

## Scope

- In `AgentTalk` streaming (`agent.py`), when a FULL-mode session is registered
  for the request's `session_id` AND the caller opts in (flag, e.g.
  `avatar_bifurcate=true`):
  - Run each `ask_stream` chunk through `SpeakableFlattener.feed()` / `flush()`;
    surface speakable **sentences** in the streamed response.
  - For structured payloads (`is_structured` / `data` / `code` / `tool_calls` /
    `output_mode`), build `StructuredOutputMessage{type, session_id, payload,
    turn_id}` and publish via `OutputBridge` → `RedisBroadcastForwarder` (the
    transport from TASK-1603) so it reaches the `/ws/userinfo` channel keyed by
    `session_id`, regardless of which gunicorn worker holds the WS.
- Default OFF / frontend-overridable: when the flag is absent, behavior is
  today's (frontend drives `speak_text`).
- Unit tests with fakes (fake bot stream, fake bridge/forwarder).

**NOT in scope**: the `/ws/userinfo` contract docs/tests (TASK-1609); pluggable
STT (TASK-1608); the FULL session minting (already in `avatar_fullmode.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | opt-in bifurcation in `AgentTalk` stream path |
| `packages/ai-parrot-server/tests/handlers/test_fullmode_bifurcation.py` | CREATE | speakable-per-sentence + structured-published |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Signatures
```python
# liveavatar/speakable.py
class SpeakableFlattener:                 # :79
    def feed(self, chunk: str) -> List[str]: ...   # :100  (emits complete sentences)
    def flush(self) -> List[str]: ...              # :116  (tail)
# liveavatar/models.py  (post TASK-1599)
class StructuredOutputMessage(BaseModel):
    type: str; session_id: str; payload: Dict[str, Any]; turn_id: Optional[str] = None
# liveavatar/output_bridge.py
class OutputBridge:                       # :25
    def __init__(self, socket_manager): ...        # :35  (duck-typed sink)
    async def publish(self, msg: StructuredOutputMessage): ...  # :39
# liveavatar/output_transport.py  RedisBroadcastForwarder (:40)  — inject as the sink
# parrot/models/responses.py  AIMessage:  .response/.to_text (speakable),
#   is_structured (:198), structured_output (:194), data (:86), code (:90),
#   tool_calls (:129), output_mode (:210), session_id (:150), turn_id (:153)
# handlers/agent.py  AgentTalk (:100); stream handling _handle_stream_response (~:2546);
#   ask_stream chunk loop (~:2565); FULL sessions live in app['avatar_fullmode_sessions']
#   (FULLMODE_SESSIONS_KEY in handlers/avatar_fullmode.py:50)
```

### Does NOT Exist
- ~~a backend `avatar.speak_text` sender~~ — that command is sent by the frontend over the LiveKit data channel; the backend only returns the flattened sentences
- ~~an in-process-only structured-output path~~ — must go through the Redis transport (multi-process server)

---

## Implementation Notes
- One `SpeakableFlattener` instance per turn (not thread-safe).
- Reuse `app['avatar_fullmode_sessions']` to detect an active FULL session.
- The publish path MUST use the Redis forwarder (TASK-1603), not a direct
  in-process `UserSocketManager.broadcast_to_channel`, so it works cross-worker.
- Keep the helper additive: zero impact when the opt-in flag is off.

---

## Acceptance Criteria
- [ ] With the opt-in flag + active FULL session: streamed output is split into speakable sentences; structured payloads are published as `StructuredOutputMessage` on the `session_id` channel via the Redis transport.
- [ ] With the flag off: behavior unchanged (frontend-driven).
- [ ] `pytest .../test_fullmode_bifurcation.py -q` green (fakes).

---

## Agent Instructions
Standard SDD flow.

## Completion Note
*(Agent fills this in when done)*
