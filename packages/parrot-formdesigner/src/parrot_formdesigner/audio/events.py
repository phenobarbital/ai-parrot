"""Audio form protocol v2 events (FEAT-649).

Client inbound messages, adapter-internal events, wire messages and I/O
requests exchanged between ``AudioFormSession`` (engine) and the WS adapter.
"""

from __future__ import annotations

import typing
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ..core.llm_validation import PlausibilityReport, PlausibilityVerdict
from ..core.voice import HandsFreeConfig
from .models import NarrationPlan, OptionMatch, Phase, ReviewItemData, UiCue

__all__ = [
    "Phase",
    "UnknownMessageType",
    # client inbound
    "StartSession",
    "AnswerText",
    "AnswerSelection",
    "AnswerPayload",
    "ConfirmAnswer",
    "SkipQuestion",
    "GoBack",
    "RepeatQuestion",
    "EndSession",
    "Ping",
    "ReviewConfirm",
    "ReviewEdit",
    # adapter-internal inbound
    "AudioReceived",
    "TranscriptReady",
    "PlanReady",
    "BlobStored",
    "SnapshotSaved",
    "PlausibilityDone",
    "SubmitDone",
    "IOFailed",
    "ClientInbound",
    "InboundEvent",
    # wire
    "SessionStarted",
    "AudioSegment",
    "Question",
    "Transcription",
    "ConfirmRequest",
    "AnswerAccepted",
    "AnswerRejected",
    "CommandAck",
    "PlanUpdated",
    "SectionEnter",
    "QuestionSkipped",
    "AnswerCleared",
    "ReviewStart",
    "ReviewItem",
    "ReviewPrompt",
    "PlausibilityResult",
    "ValidationErrors",
    "SessionResumed",
    "FormComplete",
    "SessionEnded",
    "Error",
    "Pong",
    "WireMessage",
    # I/O requests
    "Synthesize",
    "Transcribe",
    "StoreBlob",
    "DeleteBlob",
    "SaveSnapshot",
    "RunPlausibility",
    "Submit",
    "Replan",
    "IORequest",
    "Outbound",
    "is_io_request",
    "parse_inbound",
]


class UnknownMessageType(ValueError):
    """Raised by parse_inbound for an unknown or internal message type."""


class _Inbound(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartSession(_Inbound):
    type: Literal["start_session"]
    form_uid: str
    locale: str = "en"
    protocol_version: int = 1
    prefetch: bool = True
    resume_session_id: str | None = None
    stt_confirm_threshold: float | None = None
    # v1 session-config keys (api/audio_ws.py:413-421)
    tts_backend: Literal["supertonic", "google"] | None = None
    tts_voice: str | None = None
    tts_mime_format: str | None = None
    auto_advance: bool | None = None
    enumerate_options: bool | None = None


class AnswerText(_Inbound):
    type: Literal["answer_text"]
    field_id: str
    value: str = ""


class AnswerSelection(_Inbound):
    type: Literal["answer_selection"]
    field_id: str
    value: Any = None
    values: list[Any] | None = None


class AnswerPayload(_Inbound):
    type: Literal["answer_payload"]
    field_id: str
    value: Any = None


class ConfirmAnswer(_Inbound):
    type: Literal["confirm_answer"]
    field_id: str = ""
    confirmed: bool = False


class SkipQuestion(_Inbound):
    type: Literal["skip_question"]
    field_id: str | None = None


class GoBack(_Inbound):
    type: Literal["go_back"]
    to_field_id: str | None = None
    to_index: int | None = None  # v1


class RepeatQuestion(_Inbound):
    type: Literal["repeat_question"]


class EndSession(_Inbound):
    type: Literal["end_session"]


class Ping(_Inbound):
    type: Literal["ping"]


class ReviewConfirm(_Inbound):
    type: Literal["review_confirm"]
    confirmed: bool


class ReviewEdit(_Inbound):
    type: Literal["review_edit"]
    field_id: str


class AudioReceived(_Inbound):
    type: Literal["_audio"]
    audio: bytes
    mime: str | None = None


class TranscriptReady(_Inbound):
    type: Literal["_transcript"]
    field_id: str
    text: str
    language: str | None = None
    confidence: float | None = None
    audio_mime: str
    audio_bytes_len: int
    duration_ms: int | None = None


class PlanReady(_Inbound):
    type: Literal["_plan_ready"]
    plan: list[str]
    delta: dict[str, Any]  # dumped audio.planner.PlanDelta (TASK-4217)


class BlobStored(_Inbound):
    type: Literal["_blob_stored"]
    field_id: str
    blob_ref: str
    version: int


class SnapshotSaved(_Inbound):
    type: Literal["_snapshot_saved"]
    revision: int


class PlausibilityDone(_Inbound):
    type: Literal["_plausibility_done"]
    report: PlausibilityReport


class SubmitDone(_Inbound):
    type: Literal["_submit_done"]
    outcome: dict[str, Any]  # dumped services.submission_pipeline.SubmitOutcome (TASK-4222)


class IOFailed(_Inbound):
    type: Literal["_io_failed"]
    request: str  # the failed I/O request's type literal
    code: str
    detail: str | None = None


_CLIENT_TYPES = (
    StartSession,
    AnswerText,
    AnswerSelection,
    AnswerPayload,
    ConfirmAnswer,
    SkipQuestion,
    GoBack,
    RepeatQuestion,
    EndSession,
    Ping,
    ReviewConfirm,
    ReviewEdit,
)
ClientInbound = Annotated[
    Union[
        StartSession,
        AnswerText,
        AnswerSelection,
        AnswerPayload,
        ConfirmAnswer,
        SkipQuestion,
        GoBack,
        RepeatQuestion,
        EndSession,
        Ping,
        ReviewConfirm,
        ReviewEdit,
    ],
    Field(discriminator="type"),
]
InboundEvent = Annotated[
    Union[
        StartSession,
        AnswerText,
        AnswerSelection,
        AnswerPayload,
        ConfirmAnswer,
        SkipQuestion,
        GoBack,
        RepeatQuestion,
        EndSession,
        Ping,
        ReviewConfirm,
        ReviewEdit,
        AudioReceived,
        TranscriptReady,
        PlanReady,
        BlobStored,
        SnapshotSaved,
        PlausibilityDone,
        SubmitDone,
        IOFailed,
    ],
    Field(discriminator="type"),
]
_CLIENT_BY_TYPE: dict[str, type[_Inbound]] = {
    typing.get_args(m.model_fields["type"].annotation)[0]: m for m in _CLIENT_TYPES
}
_CLIENT_ADAPTER: TypeAdapter = TypeAdapter(ClientInbound)


class _Wire(BaseModel):
    def to_wire(self) -> dict[str, Any]:
        """JSON-ready dict; absent optionals omitted (v1 handler parity)."""
        return self.model_dump(mode="json", exclude_none=True)


class SessionStarted(_Wire):
    type: Literal["session_started"] = "session_started"
    session_id: str
    total_questions: int
    title: str
    protocol_version: int = 1
    hands_free: HandsFreeConfig | None = None
    max_recording_seconds: int | None = None
    prefetch_count: int | None = None


class AudioSegment(_Wire):  # header; the adapter sends the bytes as the next binary frame
    type: Literal["audio_segment"] = "audio_segment"
    key: str
    mime: str
    kind: str  # "question" | "hint" | "options" | "system" | "review"
    text: str


class Question(_Wire):
    type: Literal["question"] = "question"
    index: int
    field_id: str
    label: str
    required: bool
    field_type: str
    voice_mode: str
    render_mode: str
    sensitive: bool
    description: str | None = None
    audio: str | None = None  # base64 — only v1 or prefetch=False
    options: list[dict[str, Any]] | None = None
    fallback_html: str | None = None
    hint: str | None = None
    section_uid: str | None = None
    ui_cue: UiCue | None = None
    answer_modes: list[str] | None = None
    narration: NarrationPlan | None = None


class Transcription(_Wire):
    type: Literal["transcription"] = "transcription"
    field_id: str
    text: str
    confidence: float | None = None


class ConfirmRequest(_Wire):
    type: Literal["confirm_request"] = "confirm_request"
    field_id: str
    transcript: str
    confidence: float | None = None
    matched: OptionMatch | None = None
    alternatives: list[OptionMatch] | None = None
    purpose: Literal["answer", "stop"] = "answer"  # "stop": confirming a spoken STOP, not an answer (additive)


class AnswerAccepted(_Wire):
    type: Literal["answer_accepted"] = "answer_accepted"
    field_id: str
    source: str
    value: Any = None  # omitted for sensitive fields
    matched: OptionMatch | None = None
    blob_ref: str | None = None


class AnswerRejected(_Wire):
    type: Literal["answer_rejected"] = "answer_rejected"
    field_id: str
    error: str
    code: str | None = None


class CommandAck(_Wire):
    type: Literal["command_ack"] = "command_ack"
    command: str
    field_id: str | None = None


class PlanUpdated(_Wire):
    type: Literal["plan_updated"] = "plan_updated"
    order: list[str]
    hidden: list[str] = Field(default_factory=list)
    cleared: list[str] = Field(default_factory=list)
    required_changed: dict[str, bool] = Field(default_factory=dict)
    hidden_by_cap: list[str] = Field(default_factory=list)


class SectionEnter(_Wire):
    type: Literal["section_enter"] = "section_enter"
    section_uid: str
    title: str | None = None


class QuestionSkipped(_Wire):
    type: Literal["question_skipped"] = "question_skipped"
    field_id: str
    reason: str


class AnswerCleared(_Wire):
    type: Literal["answer_cleared"] = "answer_cleared"
    field_id: str


class ReviewStart(_Wire):
    type: Literal["review_start"] = "review_start"
    items: list[ReviewItemData]


class ReviewItem(_Wire):
    type: Literal["review_item"] = "review_item"
    item: ReviewItemData


class ReviewPrompt(_Wire):
    type: Literal["review_prompt"] = "review_prompt"
    text: str | None = None


class PlausibilityResult(_Wire):
    type: Literal["plausibility_result"] = "plausibility_result"
    status: Literal["ok", "skipped", "blocked"]
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)
    reason: str | None = None


class ValidationErrors(_Wire):
    type: Literal["validation_errors"] = "validation_errors"
    errors: dict[str, list[str]]
    first_field_id: str | None = None


class SessionResumed(_Wire):
    type: Literal["session_resumed"] = "session_resumed"
    session_id: str
    phase: Phase
    cursor: str | None = None
    answered: list[str] = Field(default_factory=list)


class FormComplete(_Wire):
    type: Literal["form_complete"] = "form_complete"
    submission_id: str
    answers: dict[str, Any] = Field(default_factory=dict)  # v1; sensitive values masked (S8)
    stored_in: str | None = None
    plausibility_summary: dict[str, Any] | None = None


class SessionEnded(_Wire):
    type: Literal["session_ended"] = "session_ended"
    session_id: str


class Error(_Wire):
    type: Literal["error"] = "error"
    code: str
    message: str
    session_id: str | None = None  # SESSION_ACTIVE only: the session holding the user's slot (same tenant)
    form_uid: str | None = None  # SESSION_ACTIVE only: that session's form


class Pong(_Wire):
    type: Literal["pong"] = "pong"


class _IORequest(BaseModel):
    """Marker base: the adapter performs these and feeds a *Done / IOFailed event back."""


class Synthesize(_IORequest):
    type: Literal["_synthesize"] = "_synthesize"
    keys: list[str]
    texts: dict[str, str]


class Transcribe(_IORequest):
    type: Literal["_transcribe"] = "_transcribe"
    field_id: str
    audio: bytes
    mime: str | None = None


class StoreBlob(_IORequest):
    type: Literal["_store_blob"] = "_store_blob"
    field_id: str
    audio: bytes
    mime: str
    version: int


class DeleteBlob(_IORequest):
    type: Literal["_delete_blob"] = "_delete_blob"
    blob_ref: str


class SaveSnapshot(_IORequest):
    type: Literal["_save_snapshot"] = "_save_snapshot"
    snapshot: dict[str, Any]  # dumped audio.session_store.AudioSnapshot (TASK-4219)


class RunPlausibility(_IORequest):
    type: Literal["_run_plausibility"] = "_run_plausibility"
    fields: set[str] | None = None  # None = every eligible field; never contains sensitive ones (S8)


class Submit(_IORequest):
    type: Literal["_submit"] = "_submit"
    data: dict[str, Any]
    context: dict[str, Any] | None = None


class Replan(_IORequest):
    type: Literal["_replan"] = "_replan"


WireMessage = Union[
    SessionStarted,
    AudioSegment,
    Question,
    Transcription,
    ConfirmRequest,
    AnswerAccepted,
    AnswerRejected,
    CommandAck,
    PlanUpdated,
    SectionEnter,
    QuestionSkipped,
    AnswerCleared,
    ReviewStart,
    ReviewItem,
    ReviewPrompt,
    PlausibilityResult,
    ValidationErrors,
    SessionResumed,
    FormComplete,
    SessionEnded,
    Error,
    Pong,
]
IORequest = Union[Synthesize, Transcribe, StoreBlob, DeleteBlob, SaveSnapshot, RunPlausibility, Submit, Replan]
Outbound = Union[WireMessage, IORequest]


def is_io_request(item: object) -> bool:
    """True when ``item`` is an I/O request the adapter must perform."""
    return isinstance(item, _IORequest)


def parse_inbound(data: dict[str, Any], *, protocol_version: int = 1) -> BaseModel:
    """Parse one client JSON message.

    v1 (protocol_version < 2): unknown keys are dropped before validation (S6).
    v2: strict (``extra="forbid"``). Internal ``_*`` types are never accepted.

    Raises:
        UnknownMessageType: unknown or internal ``type``.
        pydantic.ValidationError: malformed payload.
    """
    msg_type = data.get("type")
    model = _CLIENT_BY_TYPE.get(msg_type) if isinstance(msg_type, str) else None
    if model is None:
        raise UnknownMessageType(f"Unknown message type: {msg_type!r}")
    if protocol_version >= 2:
        return _CLIENT_ADAPTER.validate_python(data)
    filtered = {k: v for k, v in data.items() if k in model.model_fields}
    return model.model_validate(filtered)
