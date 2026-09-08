---
id: F013
query_id: Q007
type: web
intent: AWS Nova 2 Sonic documents compatible PCM output
executed_at: 2026-09-07T05:42:49.930842+00:00
depth: 1
---

# F013 — AWS Nova 2 Sonic documents compatible PCM output

## Summary

AWS Nova 2 input/output event docs include mono 16-bit LPCM output at 24 kHz and base64-encoded audio. They support the repository output format used for LiveAvatar without a second TTS pass. The docs permit more sample rates than the current repository adapter; keep repository 16k input/24k output as the implementation contract unless separately expanded.

## Citations

- [input and output event configuration](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-input-events.html) (accessed 2026-09-07)
- [audio output configuration](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-output-events.html) (accessed 2026-09-07)
