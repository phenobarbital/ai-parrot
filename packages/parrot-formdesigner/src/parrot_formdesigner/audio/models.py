"""Audio form session data models for parrot-formdesigner.

Pydantic models shared by the audio renderer and WebSocket handler.
These models define the data contract for an audio form session.

Added by FEAT-224 (FormDesigner Audio Renderer).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class VoiceMode(str, Enum):
    """How a question participates in the audio form flow.

    Introduced by FEAT-236 (Audio Renderer Form) to replace the prior
    "silently drop non-voiceable fields" behavior with an explicit
    voice-capability taxonomy so that no required field is ever lost.

    Members:
        VOICE: Narrate the question and accept a spoken or typed answer.
        PROMPT_SELECT: Narrate the question; the answer comes from a UI
            selection (radio/selector), not free speech.
        VISUAL_FALLBACK: Too complex to voice; render a single-field
            visual fallback inline to complete the answer.
    """

    VOICE = "voice"
    PROMPT_SELECT = "prompt_select"
    VISUAL_FALLBACK = "visual_fallback"


class AudioSessionConfig(BaseModel):
    """Configuration for an audio form session.

    Attributes:
        form_id: Unique identifier of the form to render in audio mode.
        locale: BCP 47 language tag for TTS and label resolution.
        tts_backend: Preferred TTS backend. Defaults to "supertonic" (a
            sub-second ONNX backend) with a graceful fallback to "google"
            at synthesis time (FEAT-236).
        tts_voice: Optional voice name to pass to the TTS backend.
        tts_mime_format: MIME type of the TTS audio output. Defaults to
            "audio/wav" since the SuperTonic backend emits WAV.
        auto_advance: When True, advance to the next question immediately
            after a valid answer without waiting for explicit confirmation.
        enumerate_options: When True, read the option labels aloud for
            PROMPT_SELECT questions (e.g. "Choose one: red, green, blue").
        stt_confirm_threshold: STT confidence below which a speech answer
            triggers a read-back confirmation turn before being stored.
    """

    model_config = ConfigDict(extra="forbid")

    form_id: str
    locale: str = "en"
    tts_backend: Literal["supertonic", "google"] = "supertonic"
    tts_voice: Optional[str] = None
    tts_mime_format: str = "audio/wav"
    auto_advance: bool = True
    enumerate_options: bool = True
    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)


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
        voice_mode: The VoiceMode taxonomy classification for this
            question (FEAT-236).
        render_mode: Client-facing render hint derived from voice_mode —
            "voice" (speak + answer), "select" (UI selection), or
            "visual" (single-field visual fallback).
        sensitive: When True, the client must mute TTS read-back of the
            value (e.g. password fields).
        fallback_html: Pre-rendered single-field HTML for VISUAL_FALLBACK
            questions, or None.
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
    voice_mode: VoiceMode = VoiceMode.VOICE
    render_mode: Literal["voice", "select", "visual"] = "voice"
    sensitive: bool = False
    fallback_html: Optional[str] = None


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
            'speech' for STT-transcribed audio, 'selection' for a UI
            selection on a PROMPT_SELECT question (FEAT-236).
        confidence: STT confidence score (0.0–1.0) when source='speech'.
        raw_transcript: Raw unprocessed transcript when source='speech'.
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    value: str
    source: Literal["text", "speech", "selection"] = "text"
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
        config: The resolved AudioSessionConfig for this session (FEAT-236),
            set at start_session. None until the session starts.
        pending: A low-confidence speech answer awaiting a confirm/repeat
            turn (FEAT-236). None when no answer is pending confirmation.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    form_id: str
    user_id: str
    current_index: int = 0
    answers: dict[str, AudioAnswer] = Field(default_factory=dict)
    manifest: Optional[AudioFormManifest] = None
    completed: bool = False
    config: Optional[AudioSessionConfig] = None
    pending: Optional[AudioAnswer] = None
