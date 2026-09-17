---
id: F010
query_id: Q010
type: read
intent: Separate SDK configuration fields from backend support and model availability
executed_at: 2026-09-17
parent_id: F008
depth: 1
---

# F010 — Provider claims require API-specific qualification

## Summary

Official Gemini documentation still lists Veo 3.1 preview IDs. Vertex release notes recommend GA IDs; this does not establish Developer API aliases. Standard/Fast and Lite differ: Lite lacks asset-reference guidance and 4k. A substring match cannot safely grant capabilities. Starting-image animation is distinct from asset-reference guidance; only the latter imposes the reference-guidance duration constraint. Region restrictions also require validation.

Installed google-genai is 2.23.0, matching prior research, not the review's 2.24.0. GenerateVideosConfig already has generate_audio, but the Developer API converter rejects non-None values; the Vertex converter maps it. A field's presence is insufficient compatibility evidence. Veo's Developer API audio is native; preserve or remove the resulting soundtrack locally according to the selected mode.

## Citations

- .venv/lib/python3.12/site-packages/google/genai/models.py:1943–2030 — _GenerateVideosConfig_to_mldev rejects generate_audio.
- .venv/lib/python3.12/site-packages/google/genai/models.py:2158–2163 — Vertex mapping of generate_audio.
- .venv/lib/python3.12/site-packages/google/genai/errors.py:294 — ClientError inherits APIError.
- packages/ai-parrot-client-google/pyproject.toml:17 — declared floor google-genai>=2.18.1.
- uv.lock — locked google-genai 2.23.0; offline importlib.metadata probe also returned 2.23.0 and confirmed the config field.
- [Gemini Veo guide](https://ai.google.dev/gemini-api/docs/veo), checked 2026-09-17: API parameters, features, limitations and model versions.
- [Vertex release notes](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes), March 3, 2026 entry: preview endpoint migrations to GA.

## Notes

Do not claim SDK 2.24.0 certification. Pin or guard a tested version during implementation and exercise public async submission/poll/download contracts. Veo 2 needs its own verified capability entry if later enabled; it is not silently granted Veo 3 features. Current docs contain inconsistencies (Lite duration notes mention unsupported reference guidance); reject unsupported features and treat unresolved combinations as verification gates.
