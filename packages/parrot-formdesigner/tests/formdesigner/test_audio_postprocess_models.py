"""FEAT-653 TASK-4248 — post-processor config + protocol models."""

from __future__ import annotations

import pytest

from parrot_formdesigner.audio.events import (
    AnswerRejected,
    ConfirmRequest,
    RefineValue,
    StartSession,
    UnknownMessageType,
    ValueRefined,
    is_io_request,
    parse_inbound,
)
from parrot_formdesigner.audio.models import AudioAnswer, AudioSessionState
from parrot_formdesigner.core.voice import FieldVoiceMeta, VoiceFormConfig


def test_config_defaults() -> None:
    cfg = VoiceFormConfig()
    assert cfg.llm_refine_values is False and 0.0 <= cfg.llm_refine_threshold <= 1.0 and cfg.llm_refine_timeout_s > 0
    meta = FieldVoiceMeta()
    assert meta.normalize is True and meta.llm_refine is None


def test_start_session_timezone_optional() -> None:
    s = parse_inbound({"type": "start_session", "form_uid": "f", "timezone": "America/New_York"}, protocol_version=2)
    assert isinstance(s, StartSession) and s.timezone == "America/New_York"
    assert parse_inbound({"type": "start_session", "form_uid": "f"}, protocol_version=2).timezone is None


def test_wire_fields_omitted_when_unset() -> None:
    assert "value" not in ConfirmRequest(field_id="a", transcript="t").to_wire()
    wire = ConfirmRequest(field_id="a", transcript="t", value="x@y.io", refined_by="rules").to_wire()
    assert wire["value"] == "x@y.io" and wire["refined_by"] == "rules"
    assert "value" not in AnswerRejected(field_id="a", error="e").to_wire()
    assert AnswerRejected(field_id="a", error="e", code="INVALID_EMAIL", value="a@b").to_wire()["value"] == "a@b"


def test_value_refined_is_internal_only() -> None:
    payload = {"type": "_value_refined", "field_id": "a", "request_id": "r", "status": "ok"}
    with pytest.raises(UnknownMessageType):
        parse_inbound(payload, protocol_version=2)
    ValueRefined(type="_value_refined", field_id="a", request_id="r", status="failed")


def test_refine_value_is_io_request() -> None:
    req = RefineValue(
        field_id="a", request_id="r", transcript="t", field_type="email", label="Email", today="2026-10-12"
    )
    assert is_io_request(req)


def test_answer_and_state_fields_default_none() -> None:
    a = AudioAnswer(field_id="a", value="v", source="speech")
    assert a.normalized_by is None and a.llm_confidence is None
    assert AudioAnswer.model_validate({"field_id": "a", "value": "v", "source": "speech"})  # old snapshot shape
    assert AudioSessionState(session_id="s", form_uid="f", user_id="u").timezone is None


def test_refine_timeout_is_capped() -> None:
    """Product decision 3: 10 s is the ceiling; 11 is rejected, and resolve_voice_config never exceeds it."""
    from pydantic import ValidationError

    from parrot_formdesigner.audio.models import AudioSessionConfig
    from parrot_formdesigner.core.schema import FormSchema
    from parrot_formdesigner.core.voice import resolve_voice_config

    assert VoiceFormConfig(llm_refine_timeout_s=10.0).llm_refine_timeout_s == 10.0
    with pytest.raises(ValidationError):
        VoiceFormConfig(llm_refine_timeout_s=11.0)
    with pytest.raises(ValidationError):
        VoiceFormConfig(llm_refine_timeout_s=0.0)
    form = FormSchema.model_construct(voice=VoiceFormConfig.model_construct(llm_refine_timeout_s=60.0))
    assert resolve_voice_config(form, None).llm_refine_timeout_s == 10.0
    assert resolve_voice_config(form, AudioSessionConfig(form_uid="f")).llm_refine_timeout_s == 10.0
