---
id: F011
query_id: Q011
type: read
intent: Verify Lyria availability and failure policy
executed_at: 2026-09-17
parent_id: F003
depth: 1
---

# F011 — Public experimental music API, deployment access unverified

## Summary

Google publicly documents models/lyria-realtime-exp via client.aio.live.music.connect. The current example uses v1beta; repository code forces v1alpha. This warrants a version compatibility check, not an assertion that v1alpha necessarily fails. The private-allowlist claim and “virtually all standard users” failure prediction are unsupported. Access, quota, region and websocket connectivity remain deployment-specific and were not tested live.

Music should have explicit off/optional/required behavior, bounded execution and machine-readable failure status. Optional failure may preserve a reel but must not disappear into logs. Preserve current best-effort behavior by default in separate-audio mode; native/muted skip this service. PCM metadata still requires verification: the repository describes 48kHz stereo while the current guide's player example uses 44.1kHz; do not hardcode from either without stream/contract evidence.

## Citations

- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1162–1211 — generate_music_stream, documented PCM assumptions, v1alpha and model.
- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:2249–2306 — _generate_reel_music; unconditional synthesized prompt, WAV creation and failure suppression.
- [Lyria RealTime guide](https://ai.google.dev/gemini-api/docs/realtime-music-generation), checked 2026-09-17: experimental status, public Python example with v1beta, model ID and JavaScript PCM player settings.

## Notes

No paid calls, credentials, dependency changes, or new music provider integration.
