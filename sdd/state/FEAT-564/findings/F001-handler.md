---
id: F001
query_id: Q001
type: read
intent: Handler and request contract
executed_at: 2026-09-17T01:24:16Z
parent_id: null
depth: 0
---

# F001 — Handler and request contract

## Summary

POST enqueues a job and lazily imports GoogleGenAIClient. There is no video_model field. Uploads compact empty slots and reuse basenames. JSON object shape, cleanup and query polling need repair.

## Citations

- packages/ai-parrot-server/src/parrot/handlers/video_reel.py:119-335 — VideoReelHandler._parse_multipart, post, get, _get_job_status.
- packages/ai-parrot/src/parrot/models/google.py:376-453 — VideoReelScene, VideoReelRequest.
