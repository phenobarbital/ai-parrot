# TASK-006: Update GoogleGenerationHelper with Video Reel Schema

**Feature**: REST API — Generate Video Reel
**Spec**: `docs/sdd/specs/rest-api-generate-video-reel.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f

---

## Context

> Implements Section 3 — Module 2 of the spec.
> Adds `video_reel_request` entry to the schema catalog so clients can discover all available generation schemas via the existing GET `/api/v1/google/generation/schemas` endpoint.

---

## Scope

- Add `"video_reel_request": VideoReelRequest.model_json_schema()` to `GoogleGenerationHelper.list_schemas()`.
- Add the necessary import for `VideoReelRequest` if not already present.

**NOT in scope**: handler implementation (TASK-005), tests (TASK-008), route registration (TASK-007).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/google_generation.py` | MODIFY | Add `video_reel_request` to `list_schemas()` |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/handlers/google_generation.py — GoogleGenerationHelper.list_schemas()
# Currently returns:
{
    "video_generation_prompt": VideoGenerationPrompt.model_json_schema(),
    "image_generation_prompt": ImageGenerationPrompt.model_json_schema(),
    "conversational_script_config": ConversationalScriptConfig.model_json_schema(),
    "music_generation_request": MusicGenerationRequest.model_json_schema(),
}
# Add:
    "video_reel_request": VideoReelRequest.model_json_schema(),
```

### Key Constraints
- Ensure `VideoReelRequest` is imported from `parrot.models.google`
- No other changes to the file

### References in Codebase
- `parrot/handlers/google_generation.py:50` — `list_schemas()` method
- `parrot/models/google.py:VideoReelRequest` — the model

---

## Acceptance Criteria

- [ ] `GoogleGenerationHelper.list_schemas()` includes `"video_reel_request"`
- [ ] Schema value is `VideoReelRequest.model_json_schema()`
- [ ] No linting errors: `ruff check parrot/handlers/google_generation.py`
- [ ] No breaking changes to existing schema entries

---

## Test Specification

| Test | Description |
|---|---|
| `test_schema_helper_includes_video_reel` | `list_schemas()` dict has `video_reel_request` key |

*(Full test implementation is in TASK-008)*

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-006-update-schema-helper-reel.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f
**Date**: 2026-02-19
**Notes**: Added `video_reel_request` to `list_schemas()` and exported `VideoReelRequest`/`VideoReelScene` from `parrot.models`.

**Deviations from spec**: Also exported `VideoReelScene` from `parrot.models.__init__.py` for completeness.
