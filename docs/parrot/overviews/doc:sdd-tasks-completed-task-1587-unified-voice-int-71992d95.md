---
type: Wiki Overview
title: 'TASK-1587: Integration tests for unified voice control'
id: doc:sdd-tasks-completed-task-1587-unified-voice-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 4** of FEAT-244. The per-task unit tests (TASK-1584/85/86)
relates_to:
- concept: mod:parrot.handlers.liveavatar_output
  rel: mentions
- concept: mod:parrot.handlers.stream
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_transport
  rel: mentions
---

# TASK-1587: Integration tests for unified voice control

**Feature**: FEAT-244 — Unified Voice Control on the StreamHandler WebSocket
**Spec**: `sdd/specs/unified-voice-control-streamhandler.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1584, TASK-1585, TASK-1586
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of FEAT-244. The per-task unit tests (TASK-1584/85/86)
cover each piece in isolation. This task adds the **cross-module integration
tests** that prove the end-to-end behavior the spec promises: a structured-output
envelope published to Redis reaches a `StreamHandler` socket subscribed to that
`session_id`, and one socket can interleave text (`stream_request`) and voice
(`voice_start`) for the same session without interference.

---

## Scope

- Add `test_end_to_end_structured_output_to_stream_ws`: drive the real
  `run_output_subscriber` with a fake Redis pub/sub that yields one envelope
  `{"channel": "sess-1", "message": {...StructuredOutputMessage...}}`, wired
  through the TASK-1586 fan-out sink to a `StreamHandler` whose fake socket is
  subscribed to `sess-1`; assert the socket received the message.
- Add `test_text_and_voice_same_socket`: on one `StreamHandler` socket, run a
  `stream_request` (mocked `bot.ask_stream`) and a `voice_start` (mocked
  `start_voice_native`) in sequence; assert both produce their respective frames
  and the channel subscription from `voice_start` persists.
- Place tests under `packages/ai-parrot-server/tests/` (integration-style, no
  real Redis/LiveKit — use fakes/mocks).

**NOT in scope**: changing production code (if a test reveals a gap, the fix
belongs to the relevant module's task, not here). No real network, Redis, or
LiveKit connections.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/test_unified_voice_integration.py` | CREATE | Cross-module integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.stream import StreamHandler                  # stream.py:11
from parrot.integrations.liveavatar.output_transport import run_output_subscriber  # output_transport.py:100
# Fan-out sink from TASK-1586:
from parrot.handlers.liveavatar_output import _FanOutSink         # created by TASK-1586
```

### Existing Signatures to Use
```python
# output_transport.run_output_subscriber(redis_client, socket_manager, *, channel="liveavatar:structured-outputs")
#   consumes redis_client.pubsub().listen() yielding {"type":"message","data": <json str>}  # output_transport.py:118-135
#   the json str is {"channel": <session_id>, "message": {...}}                              # output_transport.py:18

# StreamHandler (TASK-1585):
#   self.channel_subscriptions: dict[str, set]
#   async def broadcast_to_channel(self, channel, message, exclude_ws=None)
#   async def _handle_message(self, ws, data, bot, request)   # handles stream_request + voice_start
```

### Does NOT Exist
- ~~A real Redis or LiveKit dependency in tests~~ — use a fake `pubsub` async iterator and mocks.
- ~~A combined `bot.ask_stream` + voice helper in one call~~ — they are separate code paths exercised by separate messages on the same socket.

---

## Implementation Notes

### Pattern to Follow
Build a minimal fake Redis whose `pubsub().listen()` is an async generator
yielding one `{"type": "message", "data": json.dumps(envelope)}` then stopping
(raise `asyncio.CancelledError` or break) so `run_output_subscriber` returns.
Mirror the existing fakes in `test_liveavatar_output.py` if present.

### Key Constraints
- Tests must be deterministic and fast (no sleeps; drive the generator directly).
- Use the SAME `session_id` for the channel subscription and the envelope's
  `channel` field — that is the FEAT-243 invariant under test.

### References in Codebase
- `packages/ai-parrot-server/tests/test_liveavatar_output.py` — existing subscriber test fakes.
- `output_transport.py:100-138` — subscriber loop under test.

---

## Acceptance Criteria

- [ ] `test_end_to_end_structured_output_to_stream_ws` proves a Redis envelope reaches the subscribed StreamHandler socket.
- [ ] `test_text_and_voice_same_socket` proves text + voice coexist on one socket.
- [ ] Tests use only fakes/mocks (no real Redis/LiveKit/network).
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_unified_voice_integration.py -v`
- [ ] Full suite green: `pytest packages/ai-parrot-server/tests/ -v`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_unified_voice_integration.py
import json
import pytest
from parrot.handlers.stream import StreamHandler
from parrot.handlers.liveavatar_output import _FanOutSink
from parrot.integrations.liveavatar.output_transport import run_output_subscriber


class FakeWS:
    def __init__(self): self.closed = False; self.sent = []
    async def send_str(self, s): self.sent.append(s)


class _OneShotPubSub:
    def __init__(self, envelope): self._envelope = envelope
    async def subscribe(self, channel): ...
    async def unsubscribe(self, channel): ...
    async def listen(self):
        yield {"type": "message", "data": json.dumps(self._envelope)}


class FakeRedis:
    def __init__(self, envelope): self._envelope = envelope
    def pubsub(self): return _OneShotPubSub(self._envelope)


async def test_end_to_end_structured_output_to_stream_ws():
    handler = StreamHandler()
    ws = FakeWS()
    handler.channel_subscriptions["sess-1"] = {ws}
    envelope = {"channel": "sess-1",
                "message": {"type": "data", "session_id": "sess-1",
                            "payload": {"data": {"x": 1}}, "turn_id": None}}
    sink = _FanOutSink([handler])
    await run_output_subscriber(FakeRedis(envelope), sink, channel="liveavatar:structured-outputs")
    assert any('"data"' in s for s in ws.sent)
```

---

## Agent Instructions

1. Read the spec (§4) and the three implementation tasks.
2. Confirm TASK-1584/85/86 are in `sdd/tasks/completed/` before starting.
3. Update index status → `in-progress`.
4. Implement the integration tests per scope.
5. Run the targeted + full server test suite.
6. Move this file to `sdd/tasks/completed/` and update index → `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-18
**Notes**: Created `test_unified_voice_integration.py` with 4 integration tests:
`test_end_to_end_structured_output_to_stream_ws`, `test_end_to_end_unsubscribed_socket_gets_nothing`,
`test_end_to_end_fanout_delivers_to_both_managers`, and `test_text_and_voice_same_socket`.
All 4 pass. Full server test suite: 324 passing, 2 pre-existing failures
(`test_start_launches_subscriber_and_stop_tears_down` + `test_handlers_host_only_stubs`)
that are unrelated to FEAT-244.
**Deviations from spec**: Added 2 additional edge-case integration tests beyond the spec's minimum.
