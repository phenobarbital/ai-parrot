"""Audio form session data models for parrot-formdesigner.

Pydantic models shared by the audio renderer and WebSocket handler.
These models define the data contract for an audio form session.

Added by FEAT-224 (FormDesigner Audio Renderer).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class AudioSessionConfig(BaseModel):
    """Configuration for an audio form session.

    Attributes:
        form_id: Unique identifier of the form to render in audio mode.
        locale: BCP 47 language tag for TTS and label resolution.
        tts_voice: Optional voice name to pass to the TTS backend.
        tts_mime_format: MIME type of the TTS audio output.
        auto_advance: When True, advance to the next question immediately
            after a valid answer without waiting for explicit confirmation.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    locale: str = "en"
    tts_voice: Optional[str] = None
    tts_mime_format: str = "audio/ogg"
    auto_advance: bool = True


class AudioQuestion(BaseModel):
    """A single question in the audio form session.

    Attributes:
        index: Zero-based position in the sequential question list.
        field_id: The FormField.field_id this question maps to.
        field_type: The FieldType value string (e.g. 'text', 'select').
        label: Resolved question text shown/spoken to the user.
        description: Optional extended description or help text.
        required: Whether an answer is mandatory.
        audio_prompt: Pre-synthesized TTS audio bytes, or None if not
            yet synthesized.
        constraints: Optional validation constraints dict.
        options: Option list for SELECT/MULTI_SELECT fields, each entry
            has at least 'value' and 'label' keys.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    field_id: str
    field_type: str
    label: str
    description: Optional[str] = None
    required: bool = False
    audio_prompt: Optional[bytes] = None
    constraints: Optional[dict] = None
    options: Optional[list[dict]] = None


class AudioFormManifest(BaseModel):
    """Session manifest returned by AudioFormRenderer.render().

    Describes the sequential list of questions and the WebSocket endpoint
    for the interactive audio session.

    Attributes:
        form_id: The form identifier.
        title: Human-readable form title.
        total_questions: Number of questions in the audio session.
        questions: Ordered list of audio questions.
        ws_endpoint: WebSocket URL template for the interactive session.
        locale: Resolved locale used for this manifest.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    title: str
    total_questions: int
    questions: list[AudioQuestion]
    ws_endpoint: str
    locale: str = "en"


class AudioAnswer(BaseModel):
    """An answer to a single audio question.

    Attributes:
        field_id: The field_id this answer corresponds to.
        value: The answer text (either typed or transcribed).
        source: Origin of the answer — 'text' for keyboard input,
            'speech' for STT-transcribed audio.
        confidence: STT confidence score (0.0–1.0) when source='speech'.
        raw_transcript: Raw unprocessed transcript when source='speech'.
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    value: str
    source: Literal["text", "speech"] = "text"
    confidence: Optional[float] = None
    raw_transcript: Optional[str] = None


class AudioSessionState(BaseModel):
    """Server-side state for an active audio form session.

    One instance is created per WebSocket connection. Not persisted by
    default; use Redis if resumable sessions are needed (spec open question).

    Attributes:
        session_id: Unique identifier for this session.
        form_id: The form being filled in this session.
        user_id: Authenticated user ID from JWT.
        current_index: Zero-based index of the current question.
        answers: Map of field_id → AudioAnswer for completed questions.
        manifest: The session manifest (set after start_session).
        completed: True when all required questions have been answered
            and the form has been submitted.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    form_id: str
    user_id: str
    current_index: int = 0
    answers: dict[str, AudioAnswer] = Field(default_factory=dict)
    manifest: Optional[AudioFormManifest] = None
    completed: bool = False
