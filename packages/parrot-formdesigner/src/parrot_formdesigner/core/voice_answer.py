"""Canonical value shape for voice-note answers (FEAT-488).

A TEXT_AREA field with accept_content_types containing "application/json"
may receive a VoiceAnswerEnvelope dict as its submission value. The validator
passes it through unchanged; the consumer is responsible for parsing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm_validation import PlausibilityVerdict

if TYPE_CHECKING:
    from ..audio.models import AudioAnswer


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


class VoiceEvidenceEnvelope(VoiceAnswerEnvelope):
    """Envelope for any spoken answer (FEAT-649): typed answer + STT/recording evidence.

    ``answer`` carries the field's normalised scalar (list for MULTI_SELECT,
    bool for BOOLEAN, ...). The FEAT-488 base keeps ``answer: str``.
    """

    answer: Any = Field(..., description="Normalised answer value")
    confidence: float | None = None
    source: Literal["speech"] = "speech"
    audio_mime: str | None = None
    duration_ms: int | None = None
    language: str | None = None
    plausibility: PlausibilityVerdict | None = None
    normalized_by: Literal["rules", "llm"] | None = None  # FEAT-653: which post-processor produced `answer`
    llm_confidence: float | None = None


_V1_VOICE_KEYS = frozenset({"answer", "blob_ref", "data_url"})  # VoiceAnswerEnvelope is extra="forbid"


def is_voice_envelope(value: Any) -> bool:
    """True for a voice envelope: a model instance, a speech evidence dict, or the exact v1 dict shape.

    Upload/photo answers (``{answer, blob_ref, display}`` or ``{answer, filename, content_type, blob_ref, …}``)
    are NOT voice: any key outside ``answer`` / ``blob_ref`` / ``data_url`` rules the v1 shape out.
    """
    if isinstance(value, VoiceAnswerEnvelope):
        return True
    if not isinstance(value, dict) or "answer" not in value:
        return False
    if value.get("source") == "speech":
        return True
    return "blob_ref" in value and set(value) <= _V1_VOICE_KEYS


def unwrap_voice(data: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict where every envelope is replaced by its ``answer``."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, VoiceAnswerEnvelope):
            out[key] = value.answer
        elif is_voice_envelope(value):
            out[key] = value["answer"]
        else:
            out[key] = value
    return out


def wrap_voice(scalars: dict[str, Any], evidence: dict[str, AudioAnswer]) -> dict[str, Any]:
    """Re-fold sanitised scalars into envelopes for spoken answers.

    For each ``field_id`` whose ``evidence[field_id].source == "speech"`` the scalar
    becomes ``VoiceEvidenceEnvelope(...).model_dump()``; all other values are copied.
    Values that already are envelopes are kept as-is (idempotent).
    """
    out: dict[str, Any] = dict(scalars)
    for field_id, answer in evidence.items():
        if field_id not in scalars or getattr(answer, "source", None) != "speech":
            continue
        if is_voice_envelope(scalars[field_id]):
            continue
        out[field_id] = VoiceEvidenceEnvelope(
            answer=scalars[field_id],
            confidence=getattr(answer, "confidence", None),
            blob_ref=getattr(answer, "blob_ref", None),
            audio_mime=getattr(answer, "audio_mime", None),
            duration_ms=getattr(answer, "duration_ms", None),
            language=getattr(answer, "stt_language", None),
            normalized_by=getattr(answer, "normalized_by", None),
            llm_confidence=getattr(answer, "llm_confidence", None),
        ).model_dump()
    return out
