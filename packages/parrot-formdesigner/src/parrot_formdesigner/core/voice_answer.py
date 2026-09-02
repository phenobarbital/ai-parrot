"""Canonical value shape for voice-note answers (FEAT-488).

A TEXT_AREA field with accept_content_types containing "application/json"
may receive a VoiceAnswerEnvelope dict as its submission value. The validator
passes it through unchanged; the consumer is responsible for parsing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class VoiceAnswerEnvelope(BaseModel):
    """Dual payload for a voice-note answer on a text field.

    Attributes:
        answer: Transcription / text answer (required).
        blob_ref: Server-side voice note storage reference.
            Pre-populated by the audio renderer before submission.
            None when no blob has been stored (text-only fallback).
        data_url: Inline base64 audio data URL for small notes.
            None when the audio is stored server-side via blob_ref.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(..., description="Transcribed text answer")
    blob_ref: str | None = Field(default=None, description="Server-side audio reference")
    data_url: str | None = Field(default=None, description="Inline base64 audio data URL")
