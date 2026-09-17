---
id: F008
query_id: Q008
type: read
intent: Veo remains a supported backend
executed_at: 2026-09-17T01:24:16Z
parent_id: null
depth: 0
---

# F008 — Veo remains a supported backend

## Summary

Veo 3.1 standard/Fast/Lite are documented model IDs. Existing request construction uppercases person-generation values contrary to documented lowercase strings. SDK mismatch is confirmed; live API rejection was not reproduced. Capability and regional validation must be explicit.

## Citations

- https://ai.google.dev/gemini-api/docs/veo — checked during preceding review.
- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:965-987 — person-generation wire values.
- artifacts/logs/video_reel_review_probe.log — uppercase survives SDK serialization.
