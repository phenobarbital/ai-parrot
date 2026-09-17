---
id: F009
query_id: Q009
type: read
intent: Verify Gemini review against current orchestration and request contracts
executed_at: 2026-09-17
parent_id: F002
depth: 1
---

# F009 — Model selection and scene timing defects confirmed

## Summary

POST removes model before schema validation and uses it to construct the client. Scene breakdown explicitly selects Gemini 2.5 Flash; video explicitly selects Veo 3.1. Scene duration defaults to five seconds but is never forwarded to video_generation, whose default is eight; assembly does not trim clips. This establishes an eight-second request per scene, not a guarantee that every provider output or final reel is exactly eight seconds per scene. Failed scenes and provider output variation invalidate the review's unconditional 32-second claim.

Both background and foreground image generation omit an explicit image model. Music is attempted even without explicit music controls, using summed target durations plus five seconds; all music exceptions become None. Safety fallback catches only RuntimeError containing a substring and removes the starting image. Immediate SDK exceptions bypass that branch. Proposed fix: normalize errors and remove altered-input safety retries, rather than expanding that retry's exception tuple.

## Citations

- packages/ai-parrot-server/src/parrot/handlers/video_reel.py:199–246 — VideoReelHandler.post; extracted model and client construction.
- packages/ai-parrot/src/parrot/models/google.py:376–453 — VideoReelScene.duration and VideoReelRequest; no stage-specific model fields.
- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:844–1055 — video_generation; two-ID capability test, ignored unsupported fields, duration and audio defaults.
- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1524–1625 — generate_image; independent image-model selection.
- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:1905–2205 — generate_video_reel, _breakdown_prompt_to_scenes, _process_scene; hardcoded stages and safety fallback.
- packages/ai-parrot-client-google/src/parrot/clients/google/generation.py:2249–2435 — _generate_reel_music and _create_reel_assembly; duration estimate, swallowed music errors and untrimmed assembly.
- packages/ai-parrot-client-google/src/parrot/clients/google/client.py:630–690 — get_client; self.model can affect SDK location/version selection. Therefore “zero effect on the pipeline” is too broad, although it does not select director/video stage models.

## Notes

Wiki orientation: mem-a397a182dfcc, read after focused query; status reported stale sources, so the contracts above were checked in source. No application edits.
