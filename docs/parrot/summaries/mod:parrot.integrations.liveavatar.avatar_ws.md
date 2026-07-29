---
type: Wiki Summary
title: parrot.integrations.liveavatar.avatar_ws
id: mod:parrot.integrations.liveavatar.avatar_ws
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Avatar audio bridge — WebSocket PCM push (FEAT-242 Phase A — Module 2).
relates_to:
- concept: class:parrot.integrations.liveavatar.avatar_ws.AvatarWebSocket
  rel: defines
- concept: mod:parrot.integrations.liveavatar.models
  rel: references
---

# `parrot.integrations.liveavatar.avatar_ws`

Avatar audio bridge — WebSocket PCM push (FEAT-242 Phase A — Module 2).

Ports the LiveAvatar starter ``avatar_ws.py`` (websockets library) to
``aiohttp`` per project standards.

Responsibilities:
- Wait for ``session.state_updated == "connected"`` before sending any frames.
- Emit ``agent.speak`` / ``agent.speak_end`` / ``agent.interrupt`` protocol frames.
- Send PCM as base64 INSIDE the ``agent.speak`` JSON message (the LITE-mode
  protocol carries audio in-band, not as raw binary WS frames):
    ``{"type": "agent.speak", "audio": "<base64 PCM 16-bit 24 kHz>"}``
  PCM (already 24 kHz mono 16-bit from Supertonic) is sliced into chunks:
    - First chunk: ≈ 400 ms  (~19 200 bytes)
    - Subsequent:  ≈ 1 s     (~48 000 bytes)
    - Hard cap:    1 MB per packet
- Reconnect on WS disconnect.  There is NO in-band auth handshake — the
  ``ws_url`` returned by ``/v1/sessions/start`` is already authenticated.
- Input PCM is already 24 kHz mono 16-bit — no resampling is done.

Protocol reference: https://docs.liveavatar.com/docs/lite-mode/events

PCM size constants (from supertonic_backend.py, verified):
    _SAMPLE_RATE = 24000
    _CHANNELS    = 1      (mono)
    _SAMPLE_WIDTH = 2     (16-bit / 2 bytes per sample)
    => 1 s = 24000 * 1 * 2 = 48 000 bytes
    => 400 ms ≈ 9 600 samples * 2 bytes = 19 200 bytes

## Classes

- **`AvatarWebSocket`** — WebSocket bridge that pushes PCM audio frames to the LiveAvatar media server.
