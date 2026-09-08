---
id: F012
query_id: Q007
type: web
intent: LiveKit explicitly supports one broadcaster and many viewers
executed_at: 2026-09-07T05:42:49.930842+00:00
depth: 1
---

# F012 — LiveKit explicitly supports one broadcaster and many viewers

## Summary

Official LiveKit media documentation describes one broadcaster publishing audio/video with many subscribe-only viewers. Published tracks can be received by multiple room participants, including later joiners. Participant identities must be unique within a room; duplicate identities disconnect older connections. Combining this with LiveAvatar BYO LiveKit establishes architectural feasibility of one avatar session serving many viewers. This is a documented composition, not a performed integration test, an unlimited-capacity claim, or a promise of identical frame timing across browsers.

## Citations

- [livestreaming use case](https://docs.livekit.io/transport/media/) (accessed 2026-09-07)
- [identity uniqueness](https://docs.livekit.io/intro/basics/rooms-participants-tracks/participants/) (accessed 2026-09-07)
- [existing and future track subscription](https://docs.livekit.io/intro/basics/rooms-participants-tracks/tracks/) (accessed 2026-09-07)
