# TASK-001: Define MusicGenerationRequest Pydantic Model

**Feature**: REST API — Lyria Music Generation
**Spec**: `docs/sdd/specs/rest-api-for-lyria-music.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Foundation task for FEAT-009. Defines the request payload model that will be consumed by the handler (TASK-002) and validated at the HTTP boundary.
> Implements spec Section 3 — Module 1.

---

## Scope

- Add `MusicGenerationRequest(BaseModel)` to `parrot/models/google.py`.
- Fields: `prompt` (required str), `genre` (optional `MusicGenre`), `mood` (optional `MusicMood`), `bpm` (int, 60-200, default 90), `temperature` (float, 0.0-3.0, default 1.0), `density` (float, 0.0-1.0, default 0.5), `brightness` (float, 0.0-1.0, default 0.5), `timeout` (int, 10-600, default 300).
- Export `MusicGenerationRequest` from `parrot/models/__init__.py`.
- All fields must use `Field(...)` with `ge`/`le` constraints and descriptions.

**NOT in scope**: Handler implementation (TASK-002), schema helper update (TASK-003), tests (TASK-004).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/models/google.py` | MODIFY | Add `MusicGenerationRequest` class after `MusicMood` |
| `parrot/models/__init__.py` | MODIFY | Export `MusicGenerationRequest` |

---

## Implementation Notes

### Pattern to Follow
```python
# Same pattern as VideoReelRequest in parrot/models/google.py (line 406)
class MusicGenerationRequest(BaseModel):
    """Request payload for Lyria music generation."""
    prompt: str = Field(..., description="Text description of the desired music.")
    genre: Optional[MusicGenre] = Field(None, description="Music genre.")
    mood: Optional[MusicMood] = Field(None, description="Music mood.")
    bpm: int = Field(90, ge=60, le=200, description="Beats per minute (60-200).")
    temperature: float = Field(1.0, ge=0.0, le=3.0, description="Creativity (0.0-3.0).")
    density: float = Field(0.5, ge=0.0, le=1.0, description="Note density (0.0-1.0).")
    brightness: float = Field(0.5, ge=0.0, le=1.0, description="Tonal brightness (0.0-1.0).")
    timeout: int = Field(300, ge=10, le=600, description="Max generation duration in seconds.")
```

### Key Constraints
- Reuse existing `MusicGenre` and `MusicMood` enums (same file).
- Keep alphabetical/logical ordering consistent with existing models.

### References in Codebase
- `parrot/models/google.py` — `VideoReelRequest` (line 406) as pattern
- `parrot/models/google.py` — `MusicGenre` (line 88), `MusicMood` (line 159)

---

## Acceptance Criteria

- [ ] `MusicGenerationRequest` class exists in `parrot/models/google.py`
- [ ] All 8 fields defined with proper types, defaults, and constraints
- [ ] `from parrot.models import MusicGenerationRequest` works
- [ ] `MusicGenerationRequest.model_json_schema()` returns valid JSON schema with constraints
- [ ] No linting errors: `ruff check parrot/models/google.py`

---

## Test Specification

```python
# tests/test_music_generation_model.py
import pytest
from parrot.models.google import MusicGenerationRequest


class TestMusicGenerationRequest:
    def test_valid_minimal(self):
        """Only prompt is required."""
        req = MusicGenerationRequest(prompt="upbeat jazz")
        assert req.prompt == "upbeat jazz"
        assert req.bpm == 90

    def test_valid_full(self):
        """All fields populated."""
        req = MusicGenerationRequest(
            prompt="chill lo-fi",
            genre="Lo-Fi Hip Hop",
            mood="Chill",
            bpm=85,
            temperature=0.8,
            density=0.4,
            brightness=0.3,
            timeout=60,
        )
        assert req.genre.value == "Lo-Fi Hip Hop"

    def test_bpm_out_of_range(self):
        """BPM outside 60-200 raises validation error."""
        with pytest.raises(Exception):
            MusicGenerationRequest(prompt="test", bpm=250)

    def test_json_schema(self):
        """Schema includes all fields."""
        schema = MusicGenerationRequest.model_json_schema()
        assert "prompt" in schema["properties"]
        assert "bpm" in schema["properties"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-001-music-generation-model.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Antigravity Agent
**Date**: 2026-02-19
**Notes**: Added `MusicGenerationRequest(BaseModel)` with 8 fields (prompt, genre, mood, bpm, temperature, density, brightness, timeout) with `ge`/`le` constraints. Exported from `parrot/models/__init__.py`. All verification checks passed.

**Deviations from spec**: none
