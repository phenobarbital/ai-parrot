---
type: Wiki Entity
title: AvatarTurnSpeaker
id: class:parrot.integrations.liveavatar.speaker.AvatarTurnSpeaker
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Speak one chat turn through an already-started LiveAvatar session.
---

# AvatarTurnSpeaker

Defined in [`parrot.integrations.liveavatar.speaker`](../summaries/mod:parrot.integrations.liveavatar.speaker.md).

```python
class AvatarTurnSpeaker
```

Speak one chat turn through an already-started LiveAvatar session.

Supports two audio sinks (FEAT-256):
- **avatar-ON** (default): PCM is pushed to the LiveAvatar ``agent.speak``
  WebSocket via :class:`~avatar_ws.AvatarWebSocket`.
- **avatar-OFF**: PCM is pushed to a
  :class:`~room_audio_publisher.RoomAudioPublisher` (direct LiveKit track).
  Pass the publisher as ``room_publisher`` to activate this mode.

Args:
    handle: The active :class:`AvatarSessionHandle` (from ``/start``), which
        carries the avatar media-server ``ws_url`` and ``session_token``.
        Required for avatar-ON mode; ignored (but still required for the
        constructor signature) in avatar-OFF mode.
    synthesize_pcm_fn: Async callable ``(text: str) -> bytes`` returning raw
        PCM at the rate the avatar expects (24 kHz mono 16-bit LE).  In
        production this is :meth:`AvatarVoiceProvider.synthesize_pcm`.
    ws_session: Optional shared ``aiohttp.ClientSession`` for the WS
        (avatar-ON only; ignored when ``room_publisher`` is set).
    room_publisher: Optional :class:`~room_audio_publisher.RoomAudioPublisher`
        for the avatar-OFF path (FEAT-256).  When set the LiveAvatar WS is
        never opened; PCM goes to the room audio track instead.

## Methods

- `def feed(self, chunk: str) -> None` — Feed a streamed text chunk; queue any newly completed sentences.
- `def collected_pcm(self) -> bytes` — Return all PCM synthesized this turn (for a replay/play button).
- `async def finish(self) -> None` — Flush the remaining buffer, wait for playback, and flush the avatar.
- `async def interrupt(self) -> None` — Cancel in-flight audio (barge-in / interrupt).
- `async def aclose(self) -> None` — Tear down the consumer task and close the WebSocket (idempotent).
