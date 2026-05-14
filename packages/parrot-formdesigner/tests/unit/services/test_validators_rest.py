"""Unit tests for FormValidator — FieldType.REST branch (FEAT-170)."""

from __future__ import annotations

import pytest

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
