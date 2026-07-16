---
type: Wiki Overview
title: 'TASK-003: Avatar audio bridge — WebSocket PCM push (M2)'
id: doc:sdd-tasks-completed-task-003-avatar-ws-pcm-bridge-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements **Module 2** (spec §3): the avatar audio bridge that pushes PCM
  frames'
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
---

# TASK-003: Avatar audio bridge — WebSocket PCM push (M2)

**Feature**: FEAT-242 — LiveAvatar Phase A (avatar as the "mouth" of AgentChat)
**Spec**: `sdd/specs/liveavatar-phase-a-mouth.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** (spec §3): the avatar audio bridge that pushes PCM frames
to the LiveAvatar media-server over a WebSocket. Ports the starter's
`avatar_ws.py` (websockets) to `aiohttp`. Capability: `liveavatar-audio-bridge`.

---

## Scope

- Implement `AvatarWebSocket` in `avatar_ws.py` with the four async methods from
  spec §2: `start_speaking`, `send_audio_frame(pcm: bytes)`, `finish_speaking`,
  `interrupt`.
- Audio is already PCM **24 kHz mono 16-bit** (produced by Supertonic in
  TASK-006) — pass through with NO resampling. Keep a mono mixdown guard only as
  a defensive no-op for already-mono input.
- Chunking: first chunk ~400 ms, then ~1 s; never exceed **1 MB per packet**.
- Gate: send NO commands until `session.state_updated == "connected"`.
- Reconnect with `start` replay on WS disconnect.
- Emit protocol frames `agent.speak` / `agent.speak_end` / `agent.interrupt`
  (confirm exact frame names against the starter / API at impl).

**NOT in scope**: TTS / PCM generation (TASK-006 calls `synthesize_pcm`), HTTP
session lifecycle (TASK-002), orchestration (TASK-006). This task receives PCM
bytes and a connected `ws_url` from its caller.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/avatar_ws.py` | CREATE | `AvatarWebSocket` |
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/__init__.py` | MODIFY | Re-export `AvatarWebSocket` |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_avatar_ws.py` | CREATE | Unit tests (fake WS) |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-18.

### Verified Imports
```python
import aiohttp                                   # aiohttp WSMsgType / ws_connect (NEVER websockets)
import asyncio
import logging
from typing import Optional
from parrot.integrations.liveavatar.models import AvatarSessionHandle   # from TASK-001
```

### Existing Signatures to Use
```python
# Public interface to implement (spec §2):
class AvatarWebSocket:
    async def start_speaking(self) -> None: ...
    async def send_audio_frame(self, pcm: bytes) -> None: ...   # PCM 24k mono 16-bit
    async def finish_speaking(self) -> None: ...
    async def interrupt(self) -> None: ...

# PCM format the frames carry (verified — supertonic_backend.py):
#   _SAMPLE_RATE = 24000   (line 41)
#   _CHANNELS = 1          (line 42)
#   _SAMPLE_WIDTH = 2      (line 43, 16-bit)
# 1 second of audio = 24000 * 2 = 48000 bytes mono => ~400ms ≈ 19200 bytes.

# aiohttp WS usage (verified pattern, server side):
#   packages/ai-parrot-server/src/parrot/handlers/stream.py:197  stream_websocket
```

### Does NOT Exist (do NOT reference)
- ~~`websockets` library~~ — use `aiohttp.ClientSession.ws_connect`.
- ~~a resampler need~~ — input is ALREADY 24 kHz mono 16-bit; do NOT resample.
- ~~`LiveAvatarClient.send_audio`~~ — audio goes over THIS WS class, not the HTTP client.

---

## Implementation Notes

### Pattern to Follow
```python
class AvatarWebSocket:
    def __init__(self, handle: AvatarSessionHandle):
        self.handle = handle
        self.logger = logging.getLogger(__name__)
        self._connected = asyncio.Event()   # set on session.state_updated == "connected"

    async def _await_connected(self):
        await self._connected.wait()
```

### Key Constraints
- Async throughout; `aiohttp` WS only.
- First chunk ≈400 ms (~19.2 KB), subsequent ≈1 s (~48 KB), hard cap 1 MB/packet.
- No `agent.speak`/audio frames before `_connected` is set.
- Reconnect loop replays the `start` handshake before resuming frames.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/stream.py:197` — aiohttp WS reference
- starter `avatar_ws.py` — port reconnect+replay + frame names

---

## Acceptance Criteria

- [ ] `from parrot.integrations.liveavatar import AvatarWebSocket` works
- [ ] `test_avatar_ws_chunking`: first chunk ~400 ms, then ~1 s; no packet > 1 MB
- [ ] `test_avatar_ws_waits_for_connected`: no commands sent before `session.state_updated == "connected"`
- [ ] `test_avatar_ws_reconnect_replay`: reconnect replays `start`
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_avatar_ws.py -v`
- [ ] No lint errors: `ruff check .../liveavatar/avatar_ws.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/liveavatar/test_avatar_ws.py
import pytest
from parrot.integrations.liveavatar import AvatarWebSocket
from parrot.integrations.liveavatar.models import AvatarSessionHandle


@pytest.fixture
def handle():
    return AvatarSessionHandle(session_id="s", liveavatar_session_id="ls",
                               session_token="t", ws_url="wss://ws", agent_name="bot")


async def test_avatar_ws_waits_for_connected(handle):
    """No commands flushed until session.state_updated == 'connected'."""
    ...  # fake WS records sends; assert none before connected event


async def test_avatar_ws_chunking(handle):
    """First chunk ~400ms, then ~1s; ≤1MB packets."""
    ...  # feed 3s of PCM; assert chunk sizes


async def test_avatar_ws_reconnect_replay(handle):
    """Reconnect replays the start handshake."""
    ...
```

---

## Agent Instructions

1. Read spec §3 Module 2 and §7 gotchas (connected-gate, reconnect, PCM limits).
2. Verify the Codebase Contract.
3. Implement `AvatarWebSocket` over `aiohttp`.
4. Run tests + ruff. Move file to `completed/`, update index, fill Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-18
**Notes**: All 8 unit tests pass, lint clean. Connected gate implemented via
``asyncio.Event``; no frames sent before ``session.state_updated == connected``.
First chunk = 19 200 bytes (400 ms), subsequent = 48 000 bytes (1 s), hard cap
1 MB. Reconnect replays ``session.start`` handshake. No resampling applied.
**Deviations from spec**: None.
