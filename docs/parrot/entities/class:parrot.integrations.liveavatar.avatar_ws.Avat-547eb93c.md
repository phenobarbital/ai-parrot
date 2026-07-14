---
type: Wiki Entity
title: AvatarWebSocket
id: class:parrot.integrations.liveavatar.avatar_ws.AvatarWebSocket
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: WebSocket bridge that pushes PCM audio frames to the LiveAvatar media server.
---

# AvatarWebSocket

Defined in [`parrot.integrations.liveavatar.avatar_ws`](../summaries/mod:parrot.integrations.liveavatar.avatar_ws.md).

```python
class AvatarWebSocket
```

WebSocket bridge that pushes PCM audio frames to the LiveAvatar media server.

Emits the ``agent.speak``, ``agent.speak_end``, and ``agent.interrupt``
protocol frames required by the LiveAvatar LITE mode.

No resampling is applied: input PCM is assumed to be 24 kHz mono 16-bit,
which is exactly what Supertonic produces.

Usage::

    async with AvatarWebSocket(handle) as ws:
        await ws.start_speaking()
        await ws.send_audio_frame(pcm_bytes)
        await ws.finish_speaking()

Args:
    handle: The active :class:`AvatarSessionHandle` providing the WS URL
        and session token.
    session: Optional external ``aiohttp.ClientSession``.  When ``None``
        the class creates and owns one.
    assume_connected: When ``True`` the connected gate is opened as soon as
        the WS handshake completes, instead of waiting for a fresh
        ``session.state_updated == "connected"`` event.  Use this when
        attaching to an **already-started, already-connected** session (the
        per-turn :class:`AvatarTurnSpeaker` reuse path): the server only
        emits the ``connected`` state once, at the moment the session first
        becomes connected — a WS that attaches later never sees a re-emitted
        event, so waiting for it would always time out.  The one-shot
        orchestrator, which opens its WS at the exact connect transition,
        leaves this ``False`` and genuinely waits for the event.

## Methods

- `async def start_speaking(self) -> None` — Block until the avatar media server is ready to receive audio.
- `async def send_audio_frame(self, pcm: bytes) -> None` — Push PCM audio to the avatar as base64 ``agent.speak`` messages.
- `async def finish_speaking(self) -> None` — Send the ``agent.speak_end`` frame to flush the playback buffer.
- `async def interrupt(self) -> None` — Send the ``agent.interrupt`` frame to clear scheduled audio.
