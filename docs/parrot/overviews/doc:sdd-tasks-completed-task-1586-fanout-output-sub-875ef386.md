---
type: Wiki Overview
title: 'TASK-1586: Fan-out the structured-output subscriber to StreamHandler'
id: doc:sdd-tasks-completed-task-1586-fanout-output-subscriber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** of FEAT-244. The FEAT-243 Redis consumer
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.handlers.liveavatar_output
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_transport
  rel: mentions
---

# TASK-1586: Fan-out the structured-output subscriber to StreamHandler

**Feature**: FEAT-244 — Unified Voice Control on the StreamHandler WebSocket
**Spec**: `sdd/specs/unified-voice-control-streamhandler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1585
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of FEAT-244. The FEAT-243 Redis consumer
(`run_output_subscriber`) currently delivers each structured-output envelope to a
single sink: `app['user_socket_manager']`. This task fans it out so the **same
single subscriber** also delivers to `StreamHandler.broadcast_to_channel`
(TASK-1585), letting structured outputs reach whichever socket subscribed to the
`session_id`. It also wires `app['stream_handler']` in `manager.py` so the
subscriber can find the handler instance. No new Redis subscriber; no worker
changes.

---

## Scope

- In `configure_liveavatar_output_subscriber` (`liveavatar_output.py`), inside
  the `_start` startup hook: build a small fan-out sink object exposing
  `async def broadcast_to_channel(self, channel, message, exclude_ws=None)` that
  forwards to every present manager among `application.get("user_socket_manager")`
  and `application.get("stream_handler")` (skip `None`; one failing sink must not
  block the other — guard each call). Pass that sink as the `socket_manager`
  argument to `run_output_subscriber` instead of the bare `user_socket_manager`.
- Preserve current behavior when only `user_socket_manager` is present (the
  fan-out degrades to a single delivery) so existing deployments are unaffected.
- Keep the existing warning when `user_socket_manager` is absent, but still
  proceed if `stream_handler` is present (structured outputs can go to the
  StreamHandler alone).
- In `manager.py`, where the `StreamHandler` is constructed
  (`st = StreamHandler(); st.configure_routes(self.app)`), add
  `self.app['stream_handler'] = st` immediately after, so it is available before
  the output subscriber's `on_startup` hook runs.
- Write unit tests for the fan-out sink (see Test Specification).

**NOT in scope**: changing `run_output_subscriber` itself, the Redis envelope
schema, the worker, or `UserSocketManager`. The fan-out is the ONLY new piece.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py` | MODIFY | Build + pass the fan-out sink to `run_output_subscriber` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `self.app['stream_handler'] = st` next to `StreamHandler` construction |
| `packages/ai-parrot-server/tests/test_liveavatar_output.py` | MODIFY | Add fan-out sink unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# liveavatar_output.py (already present)
from parrot.conf import REDIS_URL                                 # liveavatar_output.py:23
# lazy inside _start (already present):
from parrot.integrations.liveavatar.output_transport import (
    DEFAULT_OUTPUT_CHANNEL, run_output_subscriber,                # liveavatar_output.py:63
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py
def configure_liveavatar_output_subscriber(app, *, redis_url=None, channel=None) -> web.Application:  # line 33
#   _start(application) hook: line 58
#     socket_manager = application.get("user_socket_manager")     # line 74  (warn+return if None: 75-80)
#     application[_TASK_KEY] = asyncio.create_task(
#         run_output_subscriber(redis, socket_manager, channel=sub_channel))  # line 85

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_transport.py (DO NOT MODIFY)
async def run_output_subscriber(redis_client, socket_manager, *, channel=DEFAULT_OUTPUT_CHANNEL) -> None:  # line 100
#   per message: socket_manager.broadcast_to_channel(channel=envelope["channel"], message=envelope["message"])  # line 127
#   => the fan-out sink MUST implement: async broadcast_to_channel(self, channel, message, exclude_ws=None)

# Sinks the fan-out forwards to (both expose the same duck-typed method):
#   UserSocketManager.broadcast_to_channel(channel, message, exclude_ws=None)   # user.py:357
#   StreamHandler.broadcast_to_channel(channel, message, exclude_ws=None)       # TASK-1585 (stream.py)
```

### Does NOT Exist
- ~~`app['stream_handler']`~~ — not set today; this task sets it in `manager.py`.
- ~~A second `run_output_subscriber` task for the StreamHandler~~ — reuse the single subscriber with the fan-out sink.
- ~~`run_output_subscriber` accepting a list of managers~~ — it takes ONE `socket_manager`; wrap multiple in the fan-out sink instead of changing its signature.
- ~~`StreamHandler` as a `UserSocketManager` subclass~~ — it is not; it only duck-types `broadcast_to_channel`.

---

## Implementation Notes

### Pattern to Follow
```python
class _FanOutSink:
    def __init__(self, managers):
        self._managers = [m for m in managers if m is not None]
    async def broadcast_to_channel(self, channel, message, exclude_ws=None):
        for m in self._managers:
            try:
                await m.broadcast_to_channel(channel, message)
            except Exception:               # one bad sink must not block the other
                logger.exception("fan-out sink delivery failed for %s", channel)

# inside _start:
sink = _FanOutSink([application.get("user_socket_manager"),
                    application.get("stream_handler")])
# proceed only if sink has at least one manager
```

### Key Constraints
- `manager.py` must set `app['stream_handler']` BEFORE `on_startup` hooks fire
  (i.e. at handler-construction time, not inside a startup hook).
- Maintain the existing opt-in: the subscriber still only runs under
  `ENABLE_LIVEAVATAR_VOICE` (the call site in `manager.py` is unchanged).
- Async throughout; reuse the module `logger`.

### References in Codebase
- `liveavatar_output.py:58-91` — the `_start` hook to extend.
- `output_transport.py:100-138` — confirms the single-`socket_manager` contract.
- `manager.py` — locate `st = StreamHandler()` (paired with `st.configure_routes`).

---

## Acceptance Criteria

- [ ] The fan-out sink forwards each envelope to both `user_socket_manager` and `stream_handler` when both are present.
- [ ] With only `user_socket_manager` present, behavior is identical to today.
- [ ] With only `stream_handler` present, structured outputs still deliver.
- [ ] A failure in one sink does not prevent delivery to the other.
- [ ] `app['stream_handler']` is set in `manager.py` before startup hooks run.
- [ ] `run_output_subscriber` and the Redis envelope schema are unchanged.
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_liveavatar_output.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/liveavatar_output.py`

---

## Test Specification

```python
# add to packages/ai-parrot-server/tests/test_liveavatar_output.py

async def test_fanout_delivers_to_both(mocker):
    from parrot.handlers.liveavatar_output import _FanOutSink  # exported for test
    a = mocker.Mock(); a.broadcast_to_channel = mocker.AsyncMock()
    b = mocker.Mock(); b.broadcast_to_channel = mocker.AsyncMock()
    sink = _FanOutSink([a, b])
    await sink.broadcast_to_channel("sess-1", {"type": "data"})
    a.broadcast_to_channel.assert_awaited_once()
    b.broadcast_to_channel.assert_awaited_once()


async def test_fanout_skips_none_and_survives_failure(mocker):
    from parrot.handlers.liveavatar_output import _FanOutSink
    good = mocker.Mock(); good.broadcast_to_channel = mocker.AsyncMock()
    bad = mocker.Mock(); bad.broadcast_to_channel = mocker.AsyncMock(side_effect=RuntimeError("boom"))
    sink = _FanOutSink([None, bad, good])
    await sink.broadcast_to_channel("sess-1", {"type": "data"})  # must not raise
    good.broadcast_to_channel.assert_awaited_once()
```

---

## Agent Instructions

1. Read the spec (§2, §6) and TASK-1585's `broadcast_to_channel`.
2. Verify the Codebase Contract against `liveavatar_output.py`, `output_transport.py`, `manager.py`.
3. Update index status → `in-progress`.
4. Implement per scope; keep `run_output_subscriber` untouched.
5. Run the tests + ruff; verify acceptance criteria.
6. Move this file to `sdd/tasks/completed/` and update index → `done`.
7. Fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.6)
**Date**: 2026-06-18
**Notes**: Added `_FanOutSink` class to `liveavatar_output.py` (exported in `__all__`).
Updated `_start` hook to build `_FanOutSink([user_socket_manager, stream_handler])` and
pass it to `run_output_subscriber`. Added graceful degradation when only one manager is
present. Added `self.app['stream_handler'] = st` in `manager.py` next to the `StreamHandler`
construction. 4 new fan-out tests pass; 1 pre-existing test failure (`test_start_launches_subscriber_and_stop_tears_down`)
is a namespace-package monkeypatching issue that pre-dates this task.
**Deviations from spec**: none
