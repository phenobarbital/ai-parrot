---
id: F003
query_id: Q003
type: read
intent: Persisted review and reproductions
executed_at: 2026-09-17T01:24:16Z
parent_id: null
depth: 0
---

# F003 — Persisted review and reproductions

## Summary

Prior review confirmed URL-to-Path corruption, PCM/WAV mismatch and multipart errors. AIMessage already has metadata and artifacts suitable for additive URL-bearing descriptors; preserve files as local paths. Review snapshot is copied into this state directory so ignored artifacts are not the sole evidence. Previous test result: 42 pass, 3 fail, 20 fixture errors, 1 skip; not rerun during proposal.

## Citations

- artifacts/video_reel_review.md — all eleven findings.
- artifacts/logs/video_reel_review_probe.log — five offline reproductions.
- artifacts/logs/video_reel_review_pytest.log — historical test result.
- packages/ai-parrot/src/parrot/models/responses.py:91,152-158,1077 — AIMessage.files, metadata, artifacts, AIMessageFactory.from_video.
- packages/ai-parrot/src/parrot/clients/base.py:2697-2724 — AbstractClient._save_audio_file.
