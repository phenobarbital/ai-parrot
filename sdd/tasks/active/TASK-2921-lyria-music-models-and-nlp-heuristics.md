# TASK-2921: Lyria Music Data Models and Natural Language Prompt Heuristics

**Feature**: FEAT-534 — Lyria Toolkit for Natural Language Music Generation
**Spec**: `sdd/specs/lyria-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models and §3 Module 1. Google Lyria requires structured music generation parameters (`bpm`, `genre`, `mood`, `density`, `brightness`, `temperature`, `duration_seconds`, `negative_prompt`, `seed`).
This task creates `LyriaMusicParameters` and `LyriaMusicResult` models in `packages/ai-parrot-tools/src/parrot_tools/google/lyria_models.py`, along with a robust natural-language keyword and regex parsing function (`parse_natural_music_request`) that converts unstructured queries like *"a soft ambient music with slow tempo"* or *"30s high energy techno"* into valid structured parameters.

---

## Scope

- Create `packages/ai-parrot-tools/src/parrot_tools/google/lyria_models.py`.
- Implement `LyriaMusicParameters(BaseModel)`:
  - `prompt: str` (non-empty string description)
  - `duration_seconds: int = 10` (constrained: `ge=1, le=120`, default: 10)
  - `genre: Optional[str] = None`
  - `mood: Optional[str] = None`
  - `bpm: int = 90` (`ge=60, le=200`, default: 90)
  - `temperature: float = 1.0` (`ge=0.0, le=3.0`, default: 1.0)
  - `density: float = 0.5` (`ge=0.0, le=1.0`, default: 0.5)
  - `brightness: float = 0.5` (`ge=0.0, le=1.0`, default: 0.5)
  - `negative_prompt: Optional[str] = None`
  - `seed: Optional[int] = None`
- Implement `LyriaMusicResult(BaseModel)`:
  - `status: Literal["success", "error"] = "success"`
  - `file_path: str`
  - `duration_seconds: float`
  - `sample_rate: int = 48000`
  - `channels: int = 2`
  - `format: str = "wav"`
  - `size_bytes: int`
  - `parameters: LyriaMusicParameters`
  - `error_message: Optional[str] = None`
- Implement `parse_natural_music_request(text: str, default_duration: int = 10) -> LyriaMusicParameters`:
  - Extracts duration from patterns like `15s`, `15 seconds`, `for 20 sec` (defaults to `default_duration` if not mentioned).
  - Extracts tempo indicators:
    - "slow" / "slow tempo" / "largo" / "adagio" -> `bpm=70`
    - "fast" / "upbeat" / "fast tempo" / "allegro" -> `bpm=130`
    - "medium" / "moderate" / "moderato" -> `bpm=95`
    - Explicit BPM: e.g. "120 bpm" -> `bpm=120`
  - Extracts density indicators:
    - "soft" / "sparse" / "minimal" / "gentle" / "mellow" -> `density=0.3`
    - "dense" / "busy" / "complex" / "heavy" -> `density=0.8`
  - Extracts brightness indicators:
    - "dark" / "warm" / "deep" / "mellow" -> `brightness=0.3`
    - "bright" / "crisp" / "sharp" -> `brightness=0.8`
  - Detects matching genres from `MusicGenre` (e.g. "ambient", "techno", "lo-fi", "classical", "rock", "jazz").
  - Detects matching moods from `MusicMood` (e.g. "chill", "dreamy", "ambient", "ethereal").
  - Cleans and isolates the descriptive core prompt.

**NOT in scope**:
- Network calls to Google Lyria (handled in TASK-2923).
- WAV file encoding or disk I/O (handled in TASK-2922).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/google/lyria_models.py` | CREATE | Pydantic data models & natural language prompt heuristic extractor |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/models/google.py:69, 141
from parrot.models.google import MusicGenre, MusicMood
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/google.py:69
class MusicGenre(str, Enum):
    ACID_JAZZ = "Acid Jazz"
    AMBIENT = "Ambient"
    CHILLOUT = "Chillout"
    LO_FI_HIP_HOP = "Lo-Fi Hip Hop"
    TECHNO = "Techno"
    # ... 60+ genres

# packages/ai-parrot/src/parrot/models/google.py:141
class MusicMood(str, Enum):
    AMBIENT = "Ambient"
    CHILL = "Chill"
    DREAMY = "Dreamy"
    ETHEREAL_AMBIENCE = "Ethereal Ambience"
    SUBDUED_MELODY = "Subdued Melody"
    # ... 30+ moods
```

### Does NOT Exist
- ~~`parrot.models.google.LyriaMusicParameters`~~ — Does not exist; created in this module.
- ~~`MusicGenerationRequest.duration_seconds`~~ — Does not exist on the base request.

---

## Implementation Notes (Detailed Code Reference)

### Complete Code Structure for `lyria_models.py`

```python
"""Data models and NLP parameter parsing for Google Lyria music generation."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from parrot.models.google import MusicGenre, MusicMood


class LyriaMusicParameters(BaseModel):
    """Parameters for a Lyria music generation request."""

    prompt: str = Field(
        ...,
        min_length=1,
        description="Descriptive text prompt for the music style, instruments, and composition.",
    )
    duration_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
        description="Duration of music in seconds (1 to 120, default 10).",
    )
    genre: Optional[str] = Field(
        default=None,
        description="Music genre (e.g., 'Ambient', 'Chillout', 'Lo-Fi Hip Hop', 'Classical').",
    )
    mood: Optional[str] = Field(
        default=None,
        description="Mood description (e.g., 'Ambient', 'Chill', 'Dreamy', 'Ethereal Ambience').",
    )
    bpm: int = Field(
        default=90,
        ge=60,
        le=200,
        description="Tempo in beats per minute (60-200, default 90). Slow=60-80, Medium=90-110, Fast=120-160.",
    )
    temperature: float = Field(
        default=1.0,
        ge=0.0,
        le=3.0,
        description="Creativity/randomness parameter (0.0 to 3.0, default 1.0).",
    )
    density: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Note density (0.0 to 1.0). Sparse/soft=0.2-0.4, Dense/complex=0.7-0.9.",
    )
    brightness: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Tonal brightness (0.0 to 1.0). Warm/dark=0.2-0.4, Bright/sharp=0.7-0.9.",
    )
    negative_prompt: Optional[str] = Field(
        default=None,
        description="Musical elements or instruments to exclude (e.g. 'drums, vocals').",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Deterministic integer seed for reproducible generation.",
    )

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Prompt cannot be empty or whitespace")
        return cleaned


class LyriaMusicResult(BaseModel):
    """Result object returned after music generation."""

    status: Literal["success", "error"] = "success"
    file_path: str = Field(..., description="Absolute path to the output WAV file on disk.")
    duration_seconds: float = Field(..., description="Length of audio file in seconds.")
    sample_rate: int = Field(default=48000, description="Audio sample rate in Hz.")
    channels: int = Field(default=2, description="Number of audio channels (2 = stereo).")
    format: str = Field(default="wav", description="Audio container format.")
    size_bytes: int = Field(..., description="File size in bytes.")
    parameters: LyriaMusicParameters = Field(..., description="Resolved parameters.")
    error_message: Optional[str] = Field(default=None, description="Error details if failed.")


def parse_natural_music_request(text: str, default_duration: int = 10) -> LyriaMusicParameters:
    """Parse a natural language description into structured LyriaMusicParameters.

    Examples:
        >>> p = parse_natural_music_request("a soft ambient music with slow tempo")
        >>> p.duration_seconds == 10
        >>> p.bpm == 70
        >>> p.density == 0.3
        >>> p.genre == "Ambient"
    """
    raw = text.strip()
    lower = raw.lower()

    # 1. Parse Duration
    duration = default_duration
    dur_match = re.search(r"(\d+)\s*(?:s|sec|seconds)", lower)
    if dur_match:
        val = int(dur_match.group(1))
        duration = max(1, min(120, val))

    # 2. Parse BPM / Tempo
    bpm = 90
    bpm_match = re.search(r"(\d+)\s*bpm", lower)
    if bpm_match:
        val = int(bpm_match.group(1))
        bpm = max(60, min(200, val))
    elif any(w in lower for w in ["slow tempo", "slow", "largo", "adagio", "relaxed pace"]):
        bpm = 70
    elif any(w in lower for w in ["fast tempo", "fast", "allegro", "presto", "high tempo", "upbeat", "energetic"]):
        bpm = 130
    elif any(w in lower for w in ["medium tempo", "moderate tempo", "moderato", "mid tempo"]):
        bpm = 95

    # 3. Parse Density
    density = 0.5
    if any(w in lower for w in ["soft", "gentle", "minimal", "minimalist", "sparse", "light", "subdued"]):
        density = 0.3
    elif any(w in lower for w in ["dense", "complex", "busy", "intense", "heavy"]):
        density = 0.8

    # 4. Parse Brightness
    brightness = 0.5
    if any(w in lower for w in ["dark", "deep", "warm", "mellow", "lo-fi", "gloomy", "ominous"]):
        brightness = 0.3
    elif any(w in lower for w in ["bright", "sharp", "crisp", "sparkling", "shiny", "crystalline"]):
        brightness = 0.8

    # 5. Detect Genre match
    matched_genre: Optional[str] = None
    for g in MusicGenre:
        if g.value.lower() in lower:
            matched_genre = g.value
            break

    # 6. Detect Mood match
    matched_mood: Optional[str] = None
    for m in MusicMood:
        if m.value.lower() in lower:
            matched_mood = m.value
            break

    # Fallbacks for genre/mood based on common synonyms
    if not matched_genre:
        if "ambient" in lower:
            matched_genre = MusicGenre.AMBIENT.value
        elif "chillout" in lower or "chill out" in lower:
            matched_genre = MusicGenre.CHILLOUT.value
        elif "lo-fi" in lower or "lofi" in lower:
            matched_genre = MusicGenre.LO_FI_HIP_HOP.value
        elif "techno" in lower:
            matched_genre = MusicGenre.TECHNO.value
        elif "rock" in lower:
            matched_genre = MusicGenre.CLASSIC_ROCK.value

    if not matched_mood:
        if "ambient" in lower:
            matched_mood = MusicMood.AMBIENT.value
        elif "chill" in lower or "relaxed" in lower or "relaxing" in lower:
            matched_mood = MusicMood.CHILL.value
        elif "dreamy" in lower:
            matched_mood = MusicMood.DREAMY.value
        elif "ethereal" in lower:
            matched_mood = MusicMood.ETHEREAL_AMBIENCE.value
        elif "soft" in lower:
            matched_mood = MusicMood.SUBDUED_MELODY.value

    return LyriaMusicParameters(
        prompt=raw,
        duration_seconds=duration,
        genre=matched_genre,
        mood=matched_mood,
        bpm=bpm,
        temperature=1.0,
        density=density,
        brightness=brightness,
    )
```

---

## Acceptance Criteria

- [ ] `LyriaMusicParameters` and `LyriaMusicResult` models defined with full field constraints.
- [ ] `parse_natural_music_request("a soft ambient music with slow tempo")` outputs:
  - `duration_seconds == 10`
  - `bpm == 70`
  - `density == 0.3`
  - `genre == "Ambient"`
  - `mood in ("Ambient", "Subdued Melody", "Chill")`
- [ ] Explicit duration in text like *"generate 25 seconds of synthwave"* correctly sets `duration_seconds = 25`.
- [ ] Boundary validation enforces `1 <= duration_seconds <= 120` and `60 <= bpm <= 200`.
