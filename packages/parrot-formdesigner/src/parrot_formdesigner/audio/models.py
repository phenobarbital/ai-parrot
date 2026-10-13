"""Audio form session data models for parrot-formdesigner.

Pydantic models shared by the audio renderer and WebSocket handler.
These models define the data contract for an audio form session.

Added by FEAT-224 (FormDesigner Audio Renderer).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.llm_validation import PlausibilityReport
from ..core.voice import FieldVoiceMeta, UiCue  # noqa: F401  (UiCue re-exported)
from ..services.rule_evaluator import RuleResolution


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


class Phase(str, Enum):
    """Audio session engine phase (FEAT-649). Re-exported by ``audio/events.py``."""

    IDLE = "idle"
    PLANNING = "planning"
    ASKING = "asking"
    ACCEPTING = "accepting"
    CONFIRMING = "confirming"
    PLAUSIBILITY = "plausibility"
    REVIEW = "review"
    REVIEW_EDITING = "review_editing"
    SUBMITTING = "submitting"
    COMPLETE = "complete"
    ABORTED = "aborted"


class OptionMatch(BaseModel):
    """A transcript resolved to one option (or boolean / scale value)."""

    value: Any
    label: str
    method: Literal["exact", "ordinal", "yes_no", "numeric", "contains", "fuzzy", "llm"]
    score: float = Field(ge=0.0, le=1.0)


class NarrationPlan(BaseModel):
    """Deterministic narration for one turn: full text + ordered audio segment keys."""

    text: str
    audio_keys: list[str] = Field(default_factory=list)
    segments: dict[str, str] = Field(default_factory=dict)  # key -> text to synthesise


class ReviewItemData(BaseModel):
    """One line of the final review (position is 1-based, as narrated)."""

    position: int = Field(ge=1)
    field_id: str
    label: str
    answer_text: str
    skipped: bool = False
    flagged: bool = False
    sensitive: bool = False


class AudioSessionConfig(BaseModel):
    """Configuration for an audio form session.

    Attributes:
        form_uid: Immutable UUID of the form to render in audio mode
            (FEAT-389 — identity is form_uid-only; the mutable form_id
            slug is never used here).
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

    form_uid: str
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
        field_uid: Immutable UUID of the FormField this question maps to
            (FEAT-393). WS wire messages still key on field_id by design
            (spec §8) — this is additive session-manifest identity only.
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
        accept_content_types: List of acceptable MIME types for this field's
            answer. When it contains "application/json" the client may submit
            a dict instead of a plain string (FEAT-488).
        answer_envelope: When "voice", the dict the client submits must be a
            VoiceAnswerEnvelope ({answer, blob_ref?, data_url?}) — the server
            validates that shape and rejects anything else. None means a
            submitted dict is treated as arbitrary JSON (FEAT-488).
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    field_id: str
    field_uid: uuid.UUID
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
    accept_content_types: Optional[list[str]] = None
    answer_envelope: Optional[Literal["voice"]] = None
    # FEAT-649 — sections, hint, narration and hands-free cues
    section_uid: Optional[str] = None
    section_title: Optional[str] = None
    subsection_title: Optional[str] = None
    hint: Optional[str] = None
    prompt: Optional[str] = None
    narration: Optional[NarrationPlan] = None
    ui_cue: Optional[UiCue] = None
    answer_modes: list[str] = Field(default_factory=list)
    voice_meta: Optional[FieldVoiceMeta] = None
    llm_validation: bool = False


class AudioFormManifest(BaseModel):
    """Session manifest returned by AudioFormRenderer.render().

    Describes the sequential list of questions and the WebSocket endpoint
    for the interactive audio session.

    Attributes:
        form_uid: Immutable UUID of the form (FEAT-389).
        title: Human-readable form title.
        total_questions: Number of questions in the audio session.
        questions: Ordered list of audio questions.
        ws_endpoint: WebSocket URL template for the interactive session.
        locale: Resolved locale used for this manifest.
    """

    model_config = ConfigDict(extra="forbid")

    form_uid: str
    title: str
    total_questions: int
    questions: list[AudioQuestion]
    ws_endpoint: str
    locale: str = "en"


class AudioAnswer(BaseModel):
    """An answer to a single audio question.

    Attributes:
        field_id: The field_id this answer corresponds to.
        field_uid: Immutable UUID of the FormField this answer corresponds
            to (FEAT-393), when known. Optional — answers may be
            reconstructed from wire data that carries no UID.
        value: The answer value (typed/transcribed text, or a list for
            MULTI_SELECT).
        source: Origin of the answer — 'text' for keyboard input,
            'speech' for STT-transcribed audio, 'selection' for a UI
            selection on a PROMPT_SELECT question (FEAT-236).
        confidence: STT confidence score (0.0–1.0) when source='speech'.
        raw_transcript: Raw unprocessed transcript when source='speech'.
        blob_ref: Reference to the stored audio recording, if any.
        audio_mime: MIME type of the recording.
        audio_bytes_len: Size of the recording in bytes.
        duration_ms: Recording duration in milliseconds.
        matched: Option match resolved from the transcript, if any.
        stt_language: Language reported by the STT engine.
        normalized_by: Post-processor that produced ``value`` (FEAT-653): 'rules', 'llm' or None.
        llm_confidence: Confidence reported by the LLM post-processor, when it produced ``value``.
        answered_at: When the answer was accepted.
        version: Answer version, incremented on every re-answer.
    """

    model_config = ConfigDict(extra="forbid")

    field_id: str
    field_uid: Optional[uuid.UUID] = None
    value: Any
    source: Literal["text", "speech", "selection"] = "text"
    confidence: Optional[float] = None
    raw_transcript: Optional[str] = None
    # FEAT-649 — recording evidence and matching
    blob_ref: Optional[str] = None
    audio_mime: Optional[str] = None
    audio_bytes_len: Optional[int] = None
    duration_ms: Optional[int] = None
    matched: Optional[OptionMatch] = None
    stt_language: Optional[str] = None
    normalized_by: Optional[Literal["rules", "llm"]] = None  # FEAT-653 post-processor provenance
    llm_confidence: Optional[float] = None
    answered_at: Optional[datetime] = None
    version: int = Field(default=1, ge=1)


class AudioSessionState(BaseModel):
    """Server-side state for an active audio form session.

    One instance is created per WebSocket connection. Not persisted by
    default; use Redis if resumable sessions are needed (spec open question).

    Attributes:
        session_id: Unique identifier for this session.
        form_uid: Immutable UUID of the form being filled in this session
            (FEAT-389).
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
        phase: Current engine phase (FEAT-649).
        cursor: field_id of the question currently asked.
        history: Ordered field_ids visited (for back navigation).
        plan: Ordered field_ids of the visible/required plan.
        return_to_review: True when an edit should return to the review.
        review_cursor: Zero-based index of the review item being read.
        resolution: Latest rule resolution (visible/required/computed).
        tenant: Tenant identifier, when known.
        locale: Session locale.
        submission_id: Pre-generated id making the commit idempotent.
        protocol_version: Wire protocol version (1 = legacy).
        plausibility: Latest plausibility report, if any.
        flagged: field_id -> answer version flagged (one flag per version).
        timezone: Client IANA timezone (FEAT-653); set on every start/resume, never snapshotted.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    form_uid: str
    user_id: str
    current_index: int = 0
    answers: dict[str, AudioAnswer] = Field(default_factory=dict)
    manifest: Optional[AudioFormManifest] = None
    completed: bool = False
    config: Optional[AudioSessionConfig] = None
    pending: Optional[AudioAnswer] = None
    # FEAT-649 — engine state
    phase: Phase = Phase.IDLE
    cursor: Optional[str] = None
    history: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    return_to_review: bool = False
    review_cursor: int = 0
    resolution: Optional[RuleResolution] = None
    tenant: Optional[str] = None
    locale: str = "en"
    submission_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    protocol_version: int = 1
    plausibility: Optional[PlausibilityReport] = None
    flagged: dict[str, int] = Field(default_factory=dict)
    timezone: Optional[str] = None  # FEAT-653: client IANA timezone; set on every start/resume, never snapshotted
