# TASK-105: Rename generate_music to generate_music_stream

**Feature**: google-lyria-music-generation
**Spec**: `sdd/specs/google-lyria-music-generation.spec.md`
**Status**: in-progress
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: ad88ddfc-fd84-406a-9983-d6470af955f8

---

## Context

This task implements Module 3 from the spec. It renames the existing `generate_music()` method to `generate_music_stream()` for API clarity, and adds a deprecated alias.

The goal is to distinguish between:
- `generate_music_stream()` — Lyria RealTime, yields PCM bytes
- `generate_music_batch()` — Vertex AI batch, returns WAV files

---

## Scope

- Rename `generate_music` method to `generate_music_stream`
- Add deprecated `generate_music` alias that calls `generate_music_stream`
- Update docstring to clarify it's streaming

**NOT in scope**:
- Updating internal callers (TASK-106)
- Updating external example code

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/clients/google/generation.py` | MODIFY | Rename method, add deprecation alias |

---

## Implementation Notes

### Pattern to Follow

```python
import warnings
from typing import AsyncIterator

async def generate_music_stream(
    self,
    prompt: str,
    genre: Optional[Union[str, MusicGenre]] = None,
    mood: Optional[Union[str, MusicMood]] = None,
    bpm: int = 90,
    temperature: float = 1.0,
    density: float = 0.5,
    brightness: float = 0.5,
    timeout: int = 300
) -> AsyncIterator[bytes]:
    """
    Stream music using Lyria RealTime API.

    Yields raw 48kHz stereo PCM audio chunks. Use generate_music_batch()
    if you want complete WAV files instead of a stream.

    Args:
        prompt: Text description of the music.
        genre: Music genre (see MusicGenre enum).
        mood: Mood description (see MusicMood enum).
        bpm: Beats per minute (60-200).
        temperature: Creativity (0.0-3.0).
        density: Note density (0.0-1.0).
        brightness: Tonal brightness (0.0-1.0).
        timeout: Max duration in seconds to keep the connection open.

    Yields:
        Audio chunks (bytes) in raw PCM format.

    Note:
        Renamed from generate_music() for API clarity.
    """
    # ... existing implementation unchanged ...


# Deprecation alias
async def generate_music(
    self,
    prompt: str,
    genre: Optional[Union[str, MusicGenre]] = None,
    mood: Optional[Union[str, MusicMood]] = None,
    bpm: int = 90,
    temperature: float = 1.0,
    density: float = 0.5,
    brightness: float = 0.5,
    timeout: int = 300
) -> AsyncIterator[bytes]:
    """
    Deprecated: Use generate_music_stream() instead.

    This method is deprecated and will be removed in a future version.
    """
    warnings.warn(
        "generate_music() is deprecated, use generate_music_stream() instead",
        DeprecationWarning,
        stacklevel=2
    )
    async for chunk in self.generate_music_stream(
        prompt=prompt,
        genre=genre,
        mood=mood,
        bpm=bpm,
        temperature=temperature,
        density=density,
        brightness=brightness,
        timeout=timeout
    ):
        yield chunk
```

### Key Constraints

- Keep the existing implementation unchanged, just rename
- The deprecated alias must yield the same type (async iterator)
- Use `warnings.warn()` with `DeprecationWarning`
- Update docstring to mention `generate_music_batch()` as alternative

### References in Codebase

- `parrot/clients/google/generation.py:1093` — existing `generate_music` method

---

## Acceptance Criteria

- [ ] Method renamed from `generate_music` to `generate_music_stream`
- [ ] `generate_music_stream` has updated docstring mentioning batch alternative
- [ ] Deprecated `generate_music` alias exists and calls `generate_music_stream`
- [ ] Deprecation warning emitted when calling `generate_music`
- [ ] Async iterator behavior preserved in alias
- [ ] No linting errors: `ruff check parrot/clients/google/generation.py`

---

## Test Specification

```python
# tests/test_lyria_deprecation.py
import pytest
import warnings
from parrot.clients.google import GoogleGenAIClient


class TestGenerateMusicDeprecation:
    @pytest.fixture
    def client(self):
        return GoogleGenAIClient()

    def test_generate_music_stream_exists(self, client):
        """generate_music_stream method exists."""
        assert hasattr(client, 'generate_music_stream')
        assert callable(client.generate_music_stream)

    def test_generate_music_deprecated(self, client):
        """generate_music emits DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Just check the warning is raised, don't actually call
            # (would need mocking for full test)
            assert hasattr(client, 'generate_music')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/google-lyria-music-generation.spec.md`
2. **Check dependencies** — this task has none
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** the rename and deprecation alias
5. **Run linter**: `ruff check parrot/clients/google/generation.py`
6. **Move this file** to `sdd/tasks/completed/TASK-105-rename-generate-music.md`
7. **Update index** → `"done"`

---

## Completion Note

**Completed by**: Antigravity (ad88ddfc-fd84-406a-9983-d6470af955f8)
**Date**: 2026-03-02
**Notes**: Renamed `generate_music` to `generate_music_stream` and added a deprecated alias. Updated docstrings to mention `generate_music_batch` as a future alternative for non-streaming generation. Verified with unit tests.

**Deviations from spec**: None.
