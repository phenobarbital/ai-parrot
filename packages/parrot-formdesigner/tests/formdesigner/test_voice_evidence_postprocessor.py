"""FEAT-653 TASK-4250 — post-processor provenance in the voice evidence envelope."""

from __future__ import annotations

from parrot_formdesigner.audio.models import AudioAnswer
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.core.voice_answer import VoiceEvidenceEnvelope, unwrap_voice, wrap_voice
from parrot_formdesigner.services.validators import FormValidator


def test_wrap_voice_carries_postprocessor() -> None:
    ans = AudioAnswer(
        field_id="email",
        value="john@gmail.com",
        source="speech",
        confidence=0.9,
        normalized_by="llm",
        llm_confidence=0.93,
    )
    out = wrap_voice({"email": "john@gmail.com"}, {"email": ans})
    assert out["email"]["normalized_by"] == "llm" and out["email"]["llm_confidence"] == 0.93
    assert unwrap_voice(out) == {"email": "john@gmail.com"}


def test_rules_provenance_without_llm() -> None:
    ans = AudioAnswer(field_id="phone", value="5550123", source="speech", normalized_by="rules")
    env = wrap_voice({"phone": "5550123"}, {"phone": ans})["phone"]
    assert env["normalized_by"] == "rules" and env["llm_confidence"] is None


def test_old_envelope_still_validates() -> None:
    old = {"answer": "x", "source": "speech", "confidence": 0.8}
    assert VoiceEvidenceEnvelope.model_validate(old).normalized_by is None


async def test_validator_recognises_new_keys() -> None:
    fields = [
        FormField(field_id="age", field_type=FieldType.NUMBER, label="Age"),
        FormField(
            field_id="note",
            field_type=FieldType.TEXT,
            label="Note",
            answer_envelope="voice",
            accept_content_types=["application/json"],
        ),
    ]
    form = FormSchema(form_id="f", title="F", sections=[FormSection(section_id="s", fields=fields)])
    # An envelope carrying ONLY the new keys must be recognised as evidence (not rejected as extra keys).
    result = await FormValidator().validate(
        form,
        {
            "age": {"answer": 25, "source": "speech", "normalized_by": "rules"},
            "note": {"answer": "hello", "normalized_by": "llm", "llm_confidence": 0.9},
        },
    )
    assert result.is_valid, result.errors
    assert result.sanitized_data["note"]["normalized_by"] == "llm"
    assert result.sanitized_data["age"]["normalized_by"] == "rules"
