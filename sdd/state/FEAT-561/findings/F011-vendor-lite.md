---
id: F011
query_id: Q007
type: web
intent: LiveAvatar LITE supports externally generated audio and BYO LiveKit
executed_at: 2026-09-07T05:42:49.930842+00:00
depth: 1
---

# F011 — LiveAvatar LITE supports externally generated audio and BYO LiveKit

## Summary

The official LITE events page specifies base64 PCM 16-bit 24 kHz audio for agent.speak, plus end and interrupt commands; text is not a required speak field. Configuration/lifecycle docs support publishing avatar media into supplied LiveKit infrastructure. The current configuration example uses livekit_config.url/token, whereas the repository supplies livekit_url/livekit_room/livekit_client_token; the OpenAPI fetch failed and the rendered reference exposed only FULL fields. Treat accepted payload keys and actual audio/video track publication as a mandatory live contract probe, not a confirmed repository bug or a guaranteed video-only API.

## Citations

- [audio command contract](https://docs.liveavatar.com/docs/lite-mode/events) (accessed 2026-09-07)
- [BYO LiveKit and example keys](https://docs.liveavatar.com/docs/lite-mode/configuration) (accessed 2026-09-07)
- [audio input and room output lifecycle](https://docs.liveavatar.com/docs/lite-mode/lifecycle) (accessed 2026-09-07)
- [rendered reference limitation](https://docs.liveavatar.com/api-reference/sessions/create-session-token) (accessed 2026-09-07)
