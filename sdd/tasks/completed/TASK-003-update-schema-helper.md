# TASK-003: Update GoogleGenerationHelper with Music Schema

**Feature**: REST API — Lyria Music Generation
**Spec**: `docs/sdd/specs/rest-api-for-lyria-music.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-001
**Assigned-to**: unassigned

---

## Context

> Keeps the centralized schema catalog in sync. Implements spec Section 3 — Module 3.
> After TASK-001 defines `MusicGenerationRequest`, this task adds it to `GoogleGenerationHelper.list_schemas()`.

---

## Scope

- Import `MusicGenerationRequest` in `parrot/handlers/google_generation.py`.
- Add `"music_generation_request": MusicGenerationRequest.model_json_schema()` to the `list_schemas()` return dict.

**NOT in scope**: Creating the model (TASK-001), handler (TASK-002), tests (TASK-004).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/google_generation.py` | MODIFY | Import model, add to `list_schemas()` |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/handlers/google_generation.py — GoogleGenerationHelper.list_schemas()
# Existing:
@staticmethod
def list_schemas() -> dict[str, dict[str, Any]]:
    return {
        "video_generation_prompt": VideoGenerationPrompt.model_json_schema(),
        "image_generation_prompt": ImageGenerationPrompt.model_json_schema(),
        "conversational_script_config": ConversationalScriptConfig.model_json_schema(),
        # ADD:
        "music_generation_request": MusicGenerationRequest.model_json_schema(),
    }
```

### References in Codebase
- `parrot/handlers/google_generation.py:50-55` — current `list_schemas()`

---

## Acceptance Criteria

- [x] `list_schemas()` includes `"music_generation_request"` key
- [x] GET `?resource=schemas` on `GoogleGeneration` endpoint includes the music schema
- [x] No linting errors: `ruff check parrot/handlers/google_generation.py`

---

## Test Specification

```python
from parrot.handlers.google_generation import GoogleGenerationHelper

def test_list_schemas_includes_music():
    schemas = GoogleGenerationHelper.list_schemas()
    assert "music_generation_request" in schemas
    assert "properties" in schemas["music_generation_request"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-001 must be in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-003-update-schema-helper.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Antigravity
**Date**: 2026-02-19
**Notes**: Added `MusicGenerationRequest` to the import from `parrot.models` and added `"music_generation_request": MusicGenerationRequest.model_json_schema()` to `list_schemas()`. File compiles clean; model verified importable with all 8 fields (prompt, genre, mood, bpm, temperature, density, brightness, timeout).

**Deviations from spec**: none
