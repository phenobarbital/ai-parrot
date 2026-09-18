---
id: F002
query_id: Q002
type: read
intent: Pipeline extension points
executed_at: 2026-09-17T01:24:16Z
parent_id: null
depth: 0
---

# F002 — Pipeline extension points

## Summary

Reel scenes hardcode Veo 3.1 and omit duration; music and assembly are shared. Veo uses generate_videos plus operation polling; model capabilities use a two-model set excluding Lite. No Omni generation implementation was found in scoped provider searches.

## Citations

- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:844-1140 — GoogleGeneration.video_generation.
- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1905-2449 — generate_video_reel, _process_scene, _generate_reel_music, _create_reel_assembly.
- packages/ai-parrot-client-google/src/parrot/clients/google/models.py:41-69 — GoogleModel.
