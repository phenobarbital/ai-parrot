---
type: Wiki Entity
title: VoiceAvatarSession
id: class:parrot.integrations.liveavatar.voice_session.VoiceAvatarSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Drives a LiveAvatar mouth from a realtime PCM (24 kHz mono 16-bit) stream.
---

# VoiceAvatarSession

Defined in [`parrot.integrations.liveavatar.voice_session`](../summaries/mod:parrot.integrations.liveavatar.voice_session.md).

```python
class VoiceAvatarSession
```

Drives a LiveAvatar mouth from a realtime PCM (24 kHz mono 16-bit) stream.

Create one instance per voice session via the :meth:`start` async class method.
The instance holds the LiveKit room tokens, live :class:`LiveAvatarClient`,
active :class:`AvatarSessionHandle`, and open :class:`AvatarWebSocket`.

Caller responsibilities:
- Run the opt-in gate (``is_avatar_enabled``) BEFORE calling :meth:`start`.
- Call :meth:`aclose` in the cleanup path (idempotent; never raises).

Args:
    _tokens: LiveKit room tokens (viewer + agent).
    _client: Open :class:`LiveAvatarClient` (keep-alive running).
    _handle: Active :class:`AvatarSessionHandle`.
    _ws: Open :class:`AvatarWebSocket` (already past the connected gate).

## Methods

- `async def start(cls, *, agent_id: str, session_id: str, tenant_id: str | None, avatar_id: str | None=None) -> 'VoiceAvatarSession'` — Bring up a full LiveAvatar LITE session for realtime PCM delivery.
- `def viewer_credentials(self) -> dict[str, str]` — Browser-safe viewer credentials for the LiveKit room.
- `async def speak(self, pcm: bytes) -> None` — Push one PCM chunk into the avatar's mouth.
- `async def finish_turn(self) -> None` — Flush the avatar's audio buffer at the end of a turn.
- `async def interrupt(self) -> None` — Clear the avatar's scheduled audio on a barge-in.
- `async def aclose(self) -> None` — Tear down the avatar session. Idempotent, never raises.
