"""Data models and NLP parameter parsing for Google Lyria music generation."""

from __future__ import annotations

import re
from typing import Literal, Optional

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
        """Ensure the prompt is non-empty after stripping whitespace.

        Args:
            v: Raw prompt value.

        Returns:
            The stripped, validated prompt string.

        Raises:
            ValueError: If the prompt is empty or whitespace-only.
        """
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

    Extracts duration, tempo (BPM), note density, tonal brightness, genre,
    and mood hints from free-form text using keyword and regex heuristics.

    Args:
        text: Free-form natural language music request (e.g. "a soft
            ambient music with slow tempo").
        default_duration: Duration in seconds to use when the text does
            not mention an explicit duration.

    Returns:
        A validated :class:`LyriaMusicParameters` instance.

    Examples:
        >>> p = parse_natural_music_request("a soft ambient music with slow tempo")
        >>> p.duration_seconds == 10
        True
        >>> p.bpm == 70
        True
        >>> p.density == 0.3
        True
        >>> p.genre == "Ambient"
        True
    """
    raw = text.strip()
    lower = raw.lower()

    # 1. Parse Duration
    duration = default_duration
    dur_match = re.search(r"(\d+)\s*(?:s|sec|seconds)", lower)
    if dur_match:
        val = int(dur_match.group(1))
        duration = max(1, min(120, val))

    # 2. Parse BPM / Tempo
    bpm = 90
    bpm_match = re.search(r"(\d+)\s*bpm", lower)
    if bpm_match:
        val = int(bpm_match.group(1))
        bpm = max(60, min(200, val))
    elif any(w in lower for w in ["slow tempo", "slow", "largo", "adagio", "relaxed pace"]):
        bpm = 70
    elif any(
        w in lower
        for w in ["fast tempo", "fast", "allegro", "presto", "high tempo", "upbeat", "energetic"]
    ):
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

    # Fallbacks for genre/mood based on common synonyms.
    # NOTE: "Ambient" is not a MusicGenre enum member (only a MusicMood
    # member) — genre is a free-form Optional[str] field, so the literal
    # string is used here rather than a nonexistent MusicGenre.AMBIENT.
    if not matched_genre:
        if "ambient" in lower:
            matched_genre = "Ambient"
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
