"""Tests for FormValidator REST field branch (FEAT-170)."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


@pytest.fixture
def rest_field() -> FormField:
    return FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        required=True,
        meta={"rest": {"mode": "callback", "callback_ref": "cb"}},
    )


@pytest.fixture
def rest_field_optional() -> FormField:
    return FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        required=False,
        meta={"rest": {"mode": "callback", "callback_ref": "cb"}},
    )


@pytest.mark.asyncio
async def test_accepts_answer_blob_ref(rest_field: FormField) -> None:
    v = FormValidator()
    errors = await v.validate_field(rest_field, {"answer": 0.86, "blob_ref": "s3://x"})
    assert errors == []


@pytest.mark.asyncio
async def test_rejects_in_progress(rest_field: FormField) -> None:
    v = FormValidator()
    errors = await v.validate_field(
        rest_field, {"answer": None, "blob_ref": None, "status": "in_progress"}
    )
    assert errors
    assert any("in_progress" in e for e in errors)


@pytest.mark.asyncio
async def test_required_rejects_null_answer(rest_field: FormField) -> None:
    v = FormValidator()
    errors = await v.validate_field(rest_field, {"answer": None, "blob_ref": None})
    assert errors


@pytest.mark.asyncio
async def test_optional_accepts_null_answer(rest_field_optional: FormField) -> None:
    v = FormValidator()
    errors = await v.validate_field(
        rest_field_optional, {"answer": None, "blob_ref": None}
    )
    assert errors == []


@pytest.mark.asyncio
async def test_rejects_non_dict(rest_field: FormField) -> None:
    v = FormValidator()
    errors = await v.validate_field(rest_field, "not-a-dict")
    assert errors


def test_coerce_strips_status(rest_field: FormField) -> None:
    v = FormValidator()
    coerced = v._coerce_value(
        {"answer": 0.86, "blob_ref": "s3://x", "status": "done"}, rest_field
    )
    assert "status" not in coerced
    assert coerced["answer"] == 0.86


def test_design_time_parse_catches_typo() -> None:
    bad = FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        meta={"rest": {"mod": "callback"}},  # typo: 'mod' instead of 'mode'
    )
    v = FormValidator()
    errors = v.validate_field_schema(bad)
    assert errors


def test_design_time_valid_spec_passes() -> None:
    good = FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        meta={"rest": {"mode": "callback", "callback_ref": "cb"}},
    )
    v = FormValidator()
    errors = v.validate_field_schema(good)
    assert errors == []


def test_design_time_missing_rest_meta() -> None:
    field = FormField(
        field_id="x",
        field_type=FieldType.REST,
        label="x",
        meta={},
    )
    v = FormValidator()
    errors = v.validate_field_schema(field)
    assert errors
