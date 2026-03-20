# TASK-008: Write Tests for VideoReelHandler

**Feature**: REST API — Generate Video Reel
**Spec**: `docs/sdd/specs/rest-api-generate-video-reel.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-005, TASK-006
**Assigned-to**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f

---

## Context

> Validation task for FEAT-008. Ensures the handler, schema helper, and route registration all work correctly.
> Implements Section 3 — Module 4 and Section 4 — Test Specification.

---

## Scope

- Create `tests/test_video_reel_handler.py` with unit and integration tests.
- Test handler `post()` with mocked `GoogleGenAIClient.generate_video_reel` (valid payload, invalid payload).
- Test handler `get()` schema response (includes all types/enums).
- Test `GoogleGenerationHelper.list_schemas()` includes `video_reel_request`.
- Test invalid payloads (missing prompt, bad types).

**NOT in scope**: Actual video generation API calls (all mocked).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_video_reel_handler.py` | CREATE | Full test suite |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow tests/test_lyria_music_handler.py for mocking pattern:
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.models.google import VideoReelRequest

@pytest.fixture
def video_reel_payload():
    return {
        "prompt": "A cinematic reel about ocean conservation",
        "music_genre": "Chillout",
        "aspect_ratio": "9:16",
    }
```

### Key Constraints
- Use `pytest` + `pytest-asyncio`
- Mock `GoogleGenAIClient` — never call real APIs
- Mock `BaseHandler` methods (`request`, `error`, `json_response`) using same pattern as `test_lyria_music_handler.py`
- `generate_video_reel` returns an `AIMessage`-like object (mock it)

### References in Codebase
- `tests/test_lyria_music_handler.py` — handler-level mock pattern
- `tests/test_google_reel.py` — client-level mock pattern for `generate_video_reel`
- `tests/conftest.py` — stub setup

---

## Acceptance Criteria

- [ ] All tests pass: `pytest tests/test_video_reel_handler.py -v`
- [ ] Tests cover: valid POST, invalid POST (missing prompt), GET schema, schema includes enums
- [ ] `GoogleGenAIClient.generate_video_reel` is mocked (no real API calls)
- [ ] `list_schemas()` includes `video_reel_request` (verified in test)
- [ ] No linting errors: `ruff check tests/test_video_reel_handler.py`

---

## Test Specification

| Test | Description |
|---|---|
| `test_post_valid_payload` | POST with valid `VideoReelRequest` body returns 200 with result |
| `test_post_invalid_payload` | POST without `prompt` returns 400 |
| `test_post_invalid_json` | POST with unparseable body returns 400 |
| `test_get_schema` | GET returns JSON Schema with all required fields/definitions |
| `test_schema_includes_enums` | GET schema includes `AspectRatio`, `MusicGenre`, `MusicMood` values |
| `test_model_valid_minimal` | `VideoReelRequest(prompt="x")` succeeds with defaults |
| `test_model_missing_prompt` | Missing prompt raises `ValidationError` |
| `test_schema_helper_includes_video_reel` | `list_schemas()` dict has `video_reel_request` key |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-005 and TASK-006 must be in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-008-video-reel-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f
**Date**: 2026-02-19
**Notes**: 21 tests across 4 classes: TestVideoReelRequestModel (7), TestVideoReelHandlerPost (6), TestVideoReelHandlerGet (6), TestSchemaHelper (2). All pass, ruff clean.

**Deviations from spec**: Added extra tests beyond spec (scenes, control key extraction, client cleanup, scene schema). Total 21 vs spec's 8.
