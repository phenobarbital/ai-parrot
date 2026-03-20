# TASK-004: Write Tests for LyriaMusicHandler

**Feature**: REST API — Lyria Music Generation
**Spec**: `docs/sdd/specs/rest-api-for-lyria-music.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-001, TASK-002
**Assigned-to**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f

---

## Context

> Validation task for FEAT-009. Ensures the model, handler, and schema helper all work correctly.
> Implements spec Section 3 — Module 4 and Section 4 — Test Specification.

---

## Scope

- Create `tests/test_lyria_music_handler.py` with unit and integration tests.
- Test model validation (valid, missing prompt, out-of-range BPM).
- Test handler `post()` with mocked `GoogleGenAIClient.generate_music` (streaming and download modes).
- Test handler `get()` catalog response.
- Test `GoogleGenerationHelper.list_schemas()` includes music schema.

**NOT in scope**: Actual Lyria API calls (all mocked).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_lyria_music_handler.py` | CREATE | Full test suite |

---

## Implementation Notes

### Pattern to Follow
```python
# Follow tests/test_google_reel.py for mocking GoogleGenAIClient
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.models.google import MusicGenerationRequest

@pytest.fixture
def music_payload():
    return {
        "prompt": "Relaxing lo-fi beats for a rainy afternoon",
        "genre": "Lo-Fi Hip Hop",
        "mood": "Chill",
        "bpm": 85,
        "temperature": 1.0,
        "density": 0.4,
        "brightness": 0.3,
        "timeout": 60,
    }
```

### Key Constraints
- Use `pytest` + `pytest-asyncio`
- Mock `GoogleGenAIClient` — never call real Lyria API
- Use `aiohttp.test_utils` if available, or mock `self.request` directly

### References in Codebase
- `tests/test_google_reel.py` — existing mock pattern for `GoogleGenAIClient`
- `tests/conftest.py` — mock `BaseHandler` / `BaseView` setup

---

## Acceptance Criteria

- [ ] All tests pass: `pytest tests/test_lyria_music_handler.py -v`
- [ ] Tests cover: valid POST, invalid POST (missing prompt, bad BPM), GET catalog, download mode
- [ ] `GoogleGenAIClient.generate_music` is mocked (no real API calls)
- [ ] No linting errors: `ruff check tests/test_lyria_music_handler.py`

---

## Test Specification

| Test | Description |
|---|---|
| `test_model_valid_minimal` | `MusicGenerationRequest(prompt="x")` succeeds |
| `test_model_missing_prompt` | Missing prompt raises `ValidationError` |
| `test_model_bpm_out_of_range` | `bpm=250` raises `ValidationError` |
| `test_model_json_schema` | Schema has all 8 properties |
| `test_post_valid_stream` | POST returns 200 with `audio/wav` chunked response |
| `test_post_valid_download` | POST with `stream: false` returns 200 with `Content-Length` |
| `test_post_invalid_payload` | POST with bad data returns 400 |
| `test_get_catalog` | GET returns JSON with `genres`, `moods`, `parameters`, `schema` |
| `test_get_catalog_genres_complete` | All `MusicGenre` values present |
| `test_schema_helper_includes_music` | `list_schemas()` has `music_generation_request` |

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-001 and TASK-002 must be in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-004-lyria-music-tests.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f
**Date**: 2026-02-19
**Notes**: 21 tests across 4 classes: TestMusicGenerationRequestModel (8), TestLyriaMusicHandlerPost (6), TestLyriaMusicHandlerGet (5), TestSchemaHelper (2). All pass, ruff clean.

**Deviations from spec**: Added extra tests beyond the 10 specified (density/brightness/temperature validation, bad JSON, generation error, moods completeness, parameter ranges). Total 21 vs spec's 10.
