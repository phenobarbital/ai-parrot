"""Unit tests for FormValidator — FieldType.REST branch (FEAT-170)."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def validator() -> FormValidator:
    return FormValidator()


@pytest.fixture
def rest_field_required() -> FormField:
    """A required REST field with a valid callback spec."""
    return FormField(
        field_id="planogram_photo",
        field_type=FieldType.REST,
        label="Planogram Photo",
        required=True,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "planogram_compliance",
            }
        },
    )


@pytest.fixture
def rest_field_optional() -> FormField:
    """An optional REST field."""
    return FormField(
        field_id="optional_upload",
        field_type=FieldType.REST,
        label="Optional Upload",
        required=False,
        meta={"rest": {"mode": "callback", "callback_ref": "cb"}},
    )


# ---------------------------------------------------------------------------
# Shape acceptance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accepts_answer_and_blob_ref(
    validator: FormValidator, rest_field_required: FormField
):
    """Valid {answer, blob_ref} dict passes without errors."""
    errors = await validator.validate_field(
        rest_field_required,
        {"answer": 0.86, "blob_ref": "s3://bucket/key"},
    )
    assert errors == []


@pytest.mark.asyncio
async def test_accepts_answer_with_none_blob_ref(
    validator: FormValidator, rest_field_required: FormField
):
    """blob_ref may be None (persist_binary=False)."""
    errors = await validator.validate_field(
        rest_field_required,
        {"answer": "ok", "blob_ref": None},
    )
    assert errors == []


@pytest.mark.asyncio
async def test_status_key_stripped_from_valid_value(
    validator: FormValidator, rest_field_required: FormField
):
    """A valid submission's status key is stripped by the validator."""
    value = {"answer": 0.9, "blob_ref": "s3://x", "status": "complete"}
    errors = await validator.validate_field(rest_field_required, value)
    assert errors == []
    assert "status" not in value


# ---------------------------------------------------------------------------
# Rejection: status=in_progress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_status_in_progress(
    validator: FormValidator, rest_field_required: FormField
):
    """status='in_progress' must be rejected with a structured error."""
    errors = await validator.validate_field(
        rest_field_required,
        {"answer": None, "blob_ref": None, "status": "in_progress"},
    )
    assert len(errors) > 0
    # Error must mention field_id and in_progress
    assert any("in_progress" in e for e in errors)


# ---------------------------------------------------------------------------
# Rejection: non-dict shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_non_dict_value(
    validator: FormValidator, rest_field_required: FormField
):
    """Submitting a plain string is not a valid REST field shape."""
    errors = await validator.validate_field(rest_field_required, "not a dict")
    assert len(errors) > 0


@pytest.mark.asyncio
async def test_rejects_list_value(
    validator: FormValidator, rest_field_required: FormField
):
    """Submitting a list is not a valid REST field shape."""
    errors = await validator.validate_field(rest_field_required, [0.86])
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# Required-field rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_required_rejects_null_answer(
    validator: FormValidator, rest_field_required: FormField
):
    """required=True with answer=None must fail."""
    errors = await validator.validate_field(
        rest_field_required, {"answer": None, "blob_ref": "s3://x"}
    )
    assert len(errors) > 0
    assert any("required" in e.lower() or "null" in e.lower() for e in errors)


@pytest.mark.asyncio
async def test_optional_allows_null_answer(
    validator: FormValidator, rest_field_optional: FormField
):
    """required=False allows answer=None."""
    errors = await validator.validate_field(
        rest_field_optional, {"answer": None, "blob_ref": None}
    )
    assert errors == []


# ---------------------------------------------------------------------------
# Design-time spec parse
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_design_time_parse_catches_invalid_spec(validator: FormValidator):
    """Invalid meta.rest (typo in mode) is caught at validation time."""
    bad_field = FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        required=False,
        meta={"rest": {"mod": "callback"}},  # typo: 'mod' instead of 'mode'
    )
    errors = await validator.validate_field(bad_field, {"answer": 1, "blob_ref": None})
    assert len(errors) > 0
    assert any("spec" in e.lower() or "meta" in e.lower() or "rest" in e.lower() for e in errors)


@pytest.mark.asyncio
async def test_design_time_parse_catches_missing_callback_ref(validator: FormValidator):
    """Missing callback_ref in callback mode is caught at validation time."""
    bad_field = FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        required=False,
        meta={"rest": {"mode": "callback"}},  # missing callback_ref
    )
    errors = await validator.validate_field(bad_field, {"answer": 1, "blob_ref": None})
    assert len(errors) > 0


@pytest.mark.asyncio
async def test_design_time_parse_catches_internal_missing_slash(
    validator: FormValidator,
):
    """Internal mode with endpoint not starting with '/' is caught."""
    bad_field = FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        required=False,
        meta={"rest": {"mode": "internal", "endpoint": "api/no-leading-slash"}},
    )
    errors = await validator.validate_field(bad_field, {"answer": 1, "blob_ref": None})
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# FEAT-488: Dict pass-through for accept_content_types
# ---------------------------------------------------------------------------


VOICE_PAYLOAD = {
    "answer": "I agree with the terms.",
    "blob_ref": "s3://bucket/voice-notes/abc123.wav",
    "data_url": None,
}


def _field(field_type: FieldType, **kwargs) -> FormField:
    return FormField(field_id="f", field_type=field_type, label="F", **kwargs)


def test_coerce_dict_passthrough_with_json_accept(validator: FormValidator):
    """A TEXT_AREA opting into application/json keeps the dict identity."""
    field = _field(
        FieldType.TEXT_AREA,
        accept_content_types=["text/plain", "application/json"],
    )
    coerced = validator._coerce_value(VOICE_PAYLOAD, field)
    assert coerced is VOICE_PAYLOAD


def test_coerce_dict_passthrough_applies_to_text(validator: FormValidator):
    """TEXT gets the same pass-through as TEXT_AREA."""
    field = _field(FieldType.TEXT, accept_content_types=["application/json"])
    assert validator._coerce_value(VOICE_PAYLOAD, field) is VOICE_PAYLOAD


def test_coerce_dict_without_json_in_accept_list_is_stringified(validator: FormValidator):
    """An accept list that omits application/json must not disable coercion."""
    field = _field(FieldType.TEXT_AREA, accept_content_types=["text/plain"])
    coerced = validator._coerce_value({"key": "value"}, field)
    assert isinstance(coerced, str)


def test_coerce_dict_without_accept_content_types_is_stringified(validator: FormValidator):
    """No regression: accept_content_types=None still coerces a dict to str."""
    field = _field(FieldType.TEXT_AREA)
    coerced = validator._coerce_value({"key": "value"}, field)
    assert coerced == str({"key": "value"})


def test_coerce_str_unchanged_with_json_accept(validator: FormValidator):
    """A plain string on a json-accepting field still coerces and strips."""
    field = _field(FieldType.TEXT_AREA, accept_content_types=["application/json"])
    assert validator._coerce_value("  some text  ", field) == "some text"


def test_coerce_str_unchanged_no_accept(validator: FormValidator):
    """No regression: str coercion unchanged when accept_content_types=None."""
    field = _field(FieldType.TEXT_AREA)
    assert validator._coerce_value("  some text  ", field) == "some text"


def test_place_field_still_normalized_with_json_accept(validator: FormValidator):
    """The guard is scoped to text types: PLACE keeps its own dict handling.

    Regression test for a guard that fired on every field_type and so skipped
    PLACE's country-required check and ISO uppercase normalisation.
    """
    field = _field(FieldType.PLACE, accept_content_types=["application/json"])
    with pytest.raises(ValueError):
        validator._coerce_value({"foo": 1}, field)


def test_signature_field_still_rejects_dict_with_json_accept(validator: FormValidator):
    """A non-text type that rejects dicts must keep rejecting them."""
    field = _field(FieldType.SIGNATURE, accept_content_types=["application/json"])
    with pytest.raises(ValueError):
        validator._coerce_value({"foo": 1}, field)


# ---------------------------------------------------------------------------
# FEAT-488: answer_envelope="voice" enforces the VoiceAnswerEnvelope shape
# ---------------------------------------------------------------------------


def _voice_field(**kwargs) -> FormField:
    return _field(
        FieldType.TEXT_AREA,
        accept_content_types=["text/plain", "application/json"],
        **kwargs,
    )


def test_voice_envelope_validated_and_canonicalized(validator: FormValidator):
    """A declared voice envelope is validated and returned in canonical form."""
    coerced = validator._coerce_value({"answer": "I agree."}, _voice_field(answer_envelope="voice"))
    assert coerced == {"answer": "I agree.", "blob_ref": None, "data_url": None}


def test_voice_envelope_keeps_blob_ref(validator: FormValidator):
    """A populated blob_ref survives canonicalization."""
    coerced = validator._coerce_value(
        {"answer": "I agree.", "blob_ref": "s3://bucket/a.wav"},
        _voice_field(answer_envelope="voice"),
    )
    assert coerced["blob_ref"] == "s3://bucket/a.wav"


def test_voice_envelope_missing_answer_rejected(validator: FormValidator):
    """The required `answer` key is enforced, with a readable message."""
    with pytest.raises(ValueError, match="voice answer envelope"):
        validator._coerce_value({"blob_ref": "s3://b/a.wav"}, _voice_field(answer_envelope="voice"))


def test_voice_envelope_extra_key_rejected(validator: FormValidator):
    """extra='forbid' on the envelope is actually enforced at submission."""
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        validator._coerce_value(
            {"answer": "hi", "bogus": 1}, _voice_field(answer_envelope="voice")
        )


def test_voice_envelope_error_message_is_single_line(validator: FormValidator):
    """Pydantic's multi-line error is summarized for a form error list."""
    with pytest.raises(ValueError) as exc:
        validator._coerce_value({}, _voice_field(answer_envelope="voice"))
    assert "\n" not in str(exc.value)
    assert "https://" not in str(exc.value)


def test_arbitrary_json_not_forced_into_envelope(validator: FormValidator):
    """Without answer_envelope, a JSON-accepting field keeps arbitrary dicts.

    Regression test: enforcing the envelope on every application/json field
    would break the `content_type="application/json"` use case the spec lists
    as a goal.
    """
    payload = {"threshold": 5, "mode": "strict"}
    assert validator._coerce_value(payload, _voice_field()) is payload


@pytest.mark.asyncio
async def test_voice_envelope_surfaces_as_field_error(validator: FormValidator):
    """A malformed envelope becomes a validation error, not an exception."""
    errors = await validator.validate_field(
        _voice_field(answer_envelope="voice"), {"blob_ref": "s3://b/a.wav"}
    )
    assert len(errors) == 1
    assert "voice answer envelope" in errors[0]


# ---------------------------------------------------------------------------
# FEAT-488: required + constraints are not bypassed by a dict answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_required_rejects_empty_dict(validator: FormValidator):
    """`{}` does not satisfy a required JSON-accepting field."""
    field = _voice_field(required=True)
    errors = await validator.validate_field(field, {})
    assert errors == ["F is required"]


@pytest.mark.asyncio
async def test_required_rejects_blank_envelope_answer(validator: FormValidator):
    """A voice envelope with a blank transcript and no audio is not an answer."""
    field = _voice_field(required=True, answer_envelope="voice")
    errors = await validator.validate_field(field, {"answer": "   "})
    assert errors == ["F is required"]


@pytest.mark.asyncio
async def test_required_accepts_blank_transcript_with_audio(validator: FormValidator):
    """A recorded note with an empty transcript IS an answer."""
    field = _voice_field(required=True, answer_envelope="voice")
    errors = await validator.validate_field(
        field, {"answer": "", "blob_ref": "s3://bucket/a.wav"}
    )
    assert errors == []


@pytest.mark.asyncio
async def test_required_accepts_non_empty_arbitrary_json(validator: FormValidator):
    """A non-empty arbitrary-JSON dict satisfies required."""
    errors = await validator.validate_field(_voice_field(required=True), {"threshold": 5})
    assert errors == []


@pytest.mark.asyncio
async def test_max_length_applies_to_envelope_transcript(validator: FormValidator):
    """max_length still guards the transcript once a field accepts JSON.

    Regression test: the constraint checks were gated on isinstance(str), so
    adding accept_content_types to an existing TEXT_AREA silently dropped its
    length guarantee.
    """
    field = _voice_field(
        answer_envelope="voice", constraints=FieldConstraints(max_length=5)
    )
    errors = await validator.validate_field(field, {"answer": "far too long"})
    assert errors == ["F must be at most 5 characters"]


@pytest.mark.asyncio
async def test_pattern_applies_to_envelope_transcript(validator: FormValidator):
    """pattern likewise applies to the transcript."""
    field = _voice_field(
        answer_envelope="voice", constraints=FieldConstraints(pattern=r"[A-Z]+")
    )
    assert await validator.validate_field(field, {"answer": "lowercase"}) != []
    assert await validator.validate_field(field, {"answer": "UPPER"}) == []


@pytest.mark.asyncio
async def test_constraints_skip_arbitrary_json(validator: FormValidator):
    """Arbitrary JSON has no transcript, so text constraints are skipped."""
    field = _voice_field(constraints=FieldConstraints(max_length=5))
    assert await validator.validate_field(field, {"a": 1, "b": 2, "c": 3}) == []


@pytest.mark.asyncio
async def test_max_length_still_applies_to_plain_string(validator: FormValidator):
    """No regression: plain strings are constrained exactly as before."""
    field = _field(FieldType.TEXT_AREA, constraints=FieldConstraints(max_length=5))
    assert await validator.validate_field(field, "far too long") != []
    assert await validator.validate_field(field, "ok") == []
