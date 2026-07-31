---
type: Wiki Overview
title: 'TASK-002: Structured-output → AgentChat UI bridge (`OutputBridge`)'
id: doc:sdd-tasks-completed-task-002-output-bridge-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 **Module 3** and Open Question **P4**. Phase C bifurcates
  the
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_bridge
  rel: mentions
---

# TASK-002: Structured-output → AgentChat UI bridge (`OutputBridge`)

**Feature**: FEAT-243 — LiveAvatar Phase C (voice-native hybrid, ai-parrot as the brain)
**Spec**: `sdd/specs/liveavatar-phase-c-voice-native.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-001
**Assigned-to**: sdd-worker (Opus)

---

## Context

Implements spec §3 **Module 3** and Open Question **P4**. Phase C bifurcates the
ai-parrot response: plain text is spoken by the avatar (TASK-003), while structured
outputs (charts/data/canvas/`tool_call`) are pushed to the **existing AgentChat UI
WebSocket channel** keyed by `session_id` — the same conversation the avatar is
speaking. The `OutputBridge` is the seam that performs that push by calling
`UserSocketManager.broadcast_to_channel()`.

This task is **NOT blocked by FEAT-242** — it depends only on the existing
`UserSocketManager` (verified) and the `StructuredOutputMessage` model from TASK-001.

---

## Scope

- Create `output_bridge.py` under the `liveavatar` package (directly under
  `liveavatar/`, NOT under `livekit_agent/` — per spec §3 Module 3 path).
- Implement `OutputBridge` with an async `publish(msg: StructuredOutputMessage) -> None`
  that serialises the message and calls
  `UserSocketManager.broadcast_to_channel(channel=msg.session_id, message=...)`.
- The bridge takes a `UserSocketManager` instance (dependency-injected) so it is unit
  testable with a fake/mock manager — do NOT reach for a global singleton.
- Use `self.logger`; no `print`.
- Write `test_output_bridge_contract`: publishing a `StructuredOutputMessage` calls
  `broadcast_to_channel` with the channel == `session_id` and a payload matching the
  agreed schema.

**NOT in scope**:
- Defining the Pydantic models (done in TASK-001 — import them).
- Calling `OutputBridge` from `llm_node` (TASK-003 wires it in).
- Any UI / front-end rendering changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_bridge.py` | CREATE | `OutputBridge.publish()` → `broadcast_to_channel` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_output_bridge.py` | CREATE | Bridge contract test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.livekit_agent.models import StructuredOutputMessage  # created in TASK-001
# UserSocketManager is the broadcast target. Verify its import path at implementation:
# class is defined at packages/ai-parrot-server/src/parrot/handlers/user.py:27
# (it lives in the ai-parrot-server package; inject an instance rather than importing
#  a singleton to keep ai-parrot-integrations free of a hard server dependency).
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/user.py:27
class UserSocketManager(WebSocketManager):
    # line 357 — VERIFIED this session:
    async def broadcast_to_channel(
        self,
        channel: str,
        message: Dict[str, Any],
        exclude_ws: Optional[web.WebSocketResponse] = None,
    ): ...
    # Internals (for understanding only): broadcasts to self.channel_subscriptions[channel];
    # silently returns if the channel has no subscribers.
```

### Channel-routing pattern (reference)
```python
# packages/ai-parrot-server/src/parrot/handlers/web_hitl.py
# current_web_session: ContextVar[Optional[str]]  (lines 54-55)  — established pattern of
# keying a WS channel by the session id. Phase C keys broadcast_to_channel by msg.session_id.
```

### Does NOT Exist
- ~~`UserSocketManager.publish_structured` / `.send_to_session`~~ — not real; the only
  channel API is `broadcast_to_channel(channel, message, exclude_ws=None)`.
- ~~a global `OutputBridge` singleton~~ — created here; inject the manager.
- ~~FEAT-242 artifacts~~ — this task does NOT depend on them.

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from parrot.integrations.liveavatar.livekit_agent.models import StructuredOutputMessage


class OutputBridge:
    """Publishes structured ai-parrot outputs to the AgentChat UI WS channel."""

    def __init__(self, socket_manager) -> None:
        self._sockets = socket_manager          # a UserSocketManager instance
        self.logger = logging.getLogger(__name__)

    async def publish(self, msg: StructuredOutputMessage) -> None:
        await self._sockets.broadcast_to_channel(
            channel=msg.session_id,
            message=msg.model_dump(),
        )
        self.logger.debug("Published %s to channel %s", msg.type, msg.session_id)
```

### Key Constraints
- `broadcast_to_channel` is async — `await` it.
- The channel key MUST be `msg.session_id` (spec acceptance: avatar speech and UI
  share the same `session_id`).
- Keep `ai-parrot-integrations` import-clean: type the injected manager loosely
  (duck-typed / `Any`) rather than importing the server class at module top level.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/user.py:357` — `broadcast_to_channel`.
- `packages/ai-parrot-server/src/parrot/handlers/web_hitl.py` — session-keyed channel pattern.

---

## Acceptance Criteria

- [ ] `OutputBridge.publish()` calls `broadcast_to_channel(channel=session_id, message=...)`
- [ ] Message payload matches the `StructuredOutputMessage` schema (P4 contract)
- [ ] Manager is dependency-injected (unit-testable with a fake)
- [ ] No linting errors: `ruff check .../liveavatar/output_bridge.py`
- [ ] `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_output_bridge.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_output_bridge.py
import pytest
from parrot.integrations.liveavatar.output_bridge import OutputBridge
from parrot.integrations.liveavatar.livekit_agent.models import StructuredOutputMessage


class FakeSocketManager:
    def __init__(self):
        self.calls = []

    async def broadcast_to_channel(self, channel, message, exclude_ws=None):
        self.calls.append((channel, message))


@pytest.mark.asyncio
async def test_output_bridge_contract():
    sm = FakeSocketManager()
    bridge = OutputBridge(sm)
    msg = StructuredOutputMessage(type="chart", session_id="s1", payload={"k": "v"})

    await bridge.publish(msg)

    assert len(sm.calls) == 1
    channel, sent = sm.calls[0]
    assert channel == "s1"                 # keyed by session_id
    assert sent["type"] == "chart"
    assert sent["payload"] == {"k": "v"}
```

---

## Agent Instructions

1. **Read the spec** for full context.
2. **Check dependencies** — TASK-001 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-grep `broadcast_to_channel` before coding.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Opus 4.8)
**Date**: 2026-06-18
**Notes**: Created `parrot/integrations/liveavatar/output_bridge.py` (directly
under `liveavatar/`, per spec §3 Module 3 path — NOT under `livekit_agent/`).
`OutputBridge.publish(StructuredOutputMessage)` is async and calls
`socket_manager.broadcast_to_channel(channel=msg.session_id, message=msg.model_dump())`,
keying the AgentChat UI channel by `session_id` (acceptance: avatar speech and UI
share one conversation). The `UserSocketManager` is dependency-injected and
duck-typed (`Any`) so `ai-parrot-integrations` keeps no hard import on the
ai-parrot-server package and the bridge is unit-testable with a fake. Added 3
tests (`test_output_bridge_contract` + turn_id + per-message); full liveavatar
suite = 8 passed; `ruff` clean.

**Deviations from spec**: none. The `StructuredOutputMessage` model is imported
from `livekit_agent.models` (defined in TASK-001 per spec §2 "Data Models")
rather than redefined here — this resolves the spec's minor inconsistency
between §2 (model lives in `livekit_agent/models.py`) and §3 Module 3 ("define
the contract in output_bridge.py"): the model is defined once and imported.
