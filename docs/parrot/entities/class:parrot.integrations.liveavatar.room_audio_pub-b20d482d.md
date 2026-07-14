---
type: Wiki Entity
title: RoomAudioPublisher
id: class:parrot.integrations.liveavatar.room_audio_publisher.RoomAudioPublisher
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Headless LiveKit participant that publishes a Supertonic audio track.
---

# RoomAudioPublisher

Defined in [`parrot.integrations.liveavatar.room_audio_publisher`](../summaries/mod:parrot.integrations.liveavatar.room_audio_publisher.md).

```python
class RoomAudioPublisher
```

Headless LiveKit participant that publishes a Supertonic audio track.

Created via :meth:`start` (class-method factory) which performs the async
room connection and track publication.  After creation the publisher is
ready to receive PCM via :meth:`capture_pcm`.

Attributes:
    room: The connected ``livekit.rtc.Room`` instance.
    source: The ``livekit.rtc.AudioSource`` that frames are pushed into.
    track: The published ``livekit.rtc.LocalAudioTrack``.

## Methods

- `async def start(cls, tokens: LiveKitRoomTokens, *, sample_rate: int=_SAMPLE_RATE, num_channels: int=_NUM_CHANNELS) -> 'RoomAudioPublisher'` — Connect to the LiveKit room and publish an audio track.
- `async def capture_pcm(self, pcm: bytes) -> None` — Push a block of raw PCM audio into the room audio track.
- `async def flush(self) -> None` — Signal a barge-in / interrupt: drop in-flight audio.
- `async def aclose(self) -> None` — Disconnect from the room and release resources (idempotent).
