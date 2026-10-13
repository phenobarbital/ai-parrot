"""Voice-mode configuration models and helpers (FEAT-649)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .types import FieldType

if TYPE_CHECKING:
    from ..audio.models import AudioSessionConfig
    from .schema import FormField, FormSchema

_logger = logging.getLogger(__name__)


class HandsFreeConfig(BaseModel):
    """Client hands-free behaviour: auto-open mic after TTS, end-of-speech silence, barge-in.

    ``barge_in`` (default True) tells the client it MAY keep the microphone armed with VAD while
    narration segments play and cancel playback on speech onset. It is a client policy and a
    ceiling: the client must still disable it when echo cancellation is not effective or the
    user opts out, and never enables it when the form says False. The server already accepts a
    recording at any time during ASKING/CONFIRMING and never learns playback was interrupted.
    """

    auto_record: bool = True
    silence_ms: int = Field(default=1200, ge=0)
    barge_in: bool = True


class UiCue(BaseModel):
    """Visual cue telling the client which control to focus/highlight."""

    control: str
    focus: bool = True
    highlight: bool = True
    submit_via: Literal["voice", "control", "both"] = "both"


class FieldVoiceMeta(BaseModel):
    """Per-field voice settings parsed from ``FormField.meta["voice"]``."""

    model_config = ConfigDict(extra="ignore")

    prompt: str | None = None
    enumerate: Literal["auto", "always", "never", "count_only"] = "auto"
    confirm: Literal["auto", "always", "never"] = "auto"
    pause_ms: int | None = None
    ui_cue: UiCue | None = None
    match_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    skip_in_review: bool = False
    commands: Literal["on", "off"] = "on"
    sensitive: bool = False
    option_pause_ms: int | None = Field(default=None, ge=0)  # per-field gap between enumerated options (ms)


class VoiceFormConfig(BaseModel):
    """Per-form voice settings (``FormSchema.voice``)."""

    enabled: bool = True
    max_questions: int | None = Field(default=10, ge=1)
    hint_pause_ms: int = Field(default=600, ge=0)
    option_pause_ms: int = Field(default=500, ge=0)  # gap between enumerated options (ms); provisional, spec §8 Q-A
    enumerate_options: bool = True
    stt_confirm_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    option_match_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    review: Literal["always", "never", "ask"] = "always"
    review_playback: Literal["tts", "recording", "both"] = "tts"
    store_recordings: bool = True
    resume_ttl_seconds: int = Field(default=3600, ge=1)
    llm_refine_options: bool = False
    commands: Literal["on", "off"] = "on"
    hands_free: HandsFreeConfig = Field(default_factory=HandsFreeConfig)
    tts_backend: Literal["supertonic", "google"] = "supertonic"
    tts_voice: str | None = None
    max_recording_seconds: int = Field(default=60, ge=1)


def is_sensitive(field: FormField) -> bool:
    """Single sensitivity policy (S8).

    True when the field is a PASSWORD or ``meta["voice"]["sensitive"]`` is True.
    Used by narration, review, plausibility eligibility, logging and form_complete.
    """
    if field.field_type == FieldType.PASSWORD:
        return True
    voice = (field.meta or {}).get("voice")
    return isinstance(voice, dict) and voice.get("sensitive") is True


def field_voice_meta(field: FormField, *, logger: logging.Logger | None = None) -> FieldVoiceMeta:
    """Parse ``field.meta["voice"]`` into a ``FieldVoiceMeta``.

    Unknown keys are ignored with ONE warning per call; an absent or invalid
    block yields defaults (invalid also logs a warning). Never raises.
    """
    log = logger or _logger
    raw: Any = (field.meta or {}).get("voice")
    if not isinstance(raw, dict):
        return FieldVoiceMeta()
    unknown = sorted(set(raw) - set(FieldVoiceMeta.model_fields))
    if unknown:
        log.warning("field %s: ignoring unknown meta.voice keys %s", field.field_id, unknown)
    try:
        return FieldVoiceMeta.model_validate(raw)
    except ValidationError as exc:
        log.warning("field %s: invalid meta.voice (%s); using defaults", field.field_id, exc)
        return FieldVoiceMeta()


def resolve_voice_config(form: FormSchema, session: AudioSessionConfig | None) -> VoiceFormConfig:
    """Return the effective voice config for a session.

    Starts from ``form.voice`` (or defaults). A session config may only TIGHTEN
    it: thresholds may go up, caps may go down, features may be switched off —
    never the reverse.
    """
    base = form.voice or VoiceFormConfig()
    if session is None:
        return base
    overrides: dict[str, Any] = {
        "stt_confirm_threshold": max(base.stt_confirm_threshold, session.stt_confirm_threshold),
        "enumerate_options": base.enumerate_options and session.enumerate_options,
    }
    fields_set = session.model_fields_set
    if "tts_backend" in fields_set and session.tts_backend:
        overrides["tts_backend"] = session.tts_backend
    if session.tts_voice:
        overrides["tts_voice"] = session.tts_voice
    return base.model_copy(update=overrides)
