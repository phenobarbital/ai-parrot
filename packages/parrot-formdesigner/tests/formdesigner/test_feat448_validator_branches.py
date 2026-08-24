"""Tests for TASK-2333 (FEAT-448) — validator branches for ten of the
client's types (``credit_card`` is TASK-2334, tested separately).

Shapes read from the controls, not navigator-svelte's 2026-05 spec table
(spec §4): ``search``, ``masked``, ``color_picker``, ``emoji``, ``cron``,
``tree_select``, ``signature_pad``, ``image_dropzone``, ``multi_upload``,
``ai_capture``.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.validators import FormValidator


@pytest.fixture
def validator() -> FormValidator:
    return FormValidator()


def _field(field_type: FieldType) -> FormField:
    return FormField(
        field_id=f"f_{field_type.value}",
        field_type=field_type,
        label=field_type.value,
        required=False,
    )


# ---------------------------------------------------------------------------
# AC1 — a value produced by each client control validates with no errors.
# ---------------------------------------------------------------------------

VALID_VALUES: dict[FieldType, object] = {
    FieldType.SEARCH: "widget-123",
    FieldType.MASKED: "555-123-4567",
    FieldType.COLOR_PICKER: "#1a2b3c",
    FieldType.EMOJI: "\U0001f600",
    FieldType.CRON: "0 0 * * *",
    FieldType.TREE_SELECT: ["node-1", "node-2"],
    FieldType.SIGNATURE_PAD: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA",
    FieldType.IMAGE_DROPZONE: {
        "name": "photo.png",
        "type": "image/png",
        "size": 1024,
        "dataUrl": "data:image/png;base64,AA==",
    },
    FieldType.MULTI_UPLOAD: [{"answer": "a1", "blob_ref": "b1", "display": "Photo 1"}],
    FieldType.AI_CAPTURE: {"nested": {"score": 0.9}},
}


class TestValidValuesAccepted:
    @pytest.mark.parametrize("field_type", list(VALID_VALUES.keys()), ids=[ft.value for ft in VALID_VALUES])
    @pytest.mark.asyncio
    async def test_accepts_control_value(self, validator: FormValidator, field_type: FieldType):
        field = _field(field_type)
        errors = await validator.validate_field(field, VALID_VALUES[field_type])
        assert errors == [], f"{field_type.value}: unexpected errors {errors}"

    @pytest.mark.asyncio
    async def test_tree_select_single_mode_accepts_scalar(self, validator: FormValidator):
        """Single mode yields the node value (a bare string), not a list."""
        field = _field(FieldType.TREE_SELECT)
        errors = await validator.validate_field(field, "node-1")
        assert errors == []

    @pytest.mark.asyncio
    async def test_image_dropzone_accepts_list_form(self, validator: FormValidator):
        """AC4 — image_dropzone accepts both the single and the list form."""
        field = _field(FieldType.IMAGE_DROPZONE)
        errors = await validator.validate_field(
            field,
            [
                {"name": "a.png", "type": "image/png", "size": 10, "dataUrl": "data:image/png;base64,AA=="},
                {"name": "b.png", "type": "image/png", "size": 20, "dataUrl": "data:image/png;base64,AA=="},
            ],
        )
        assert errors == []


# ---------------------------------------------------------------------------
# AC2 — a clearly wrong value for each type produces an error (a dict where
# a string belongs, and the reverse).
# ---------------------------------------------------------------------------

WRONG_TYPE_VALUES: dict[FieldType, object] = {
    FieldType.SEARCH: {"unexpected": "dict"},
    FieldType.MASKED: {"unexpected": "dict"},
    FieldType.COLOR_PICKER: {"unexpected": "dict"},
    FieldType.EMOJI: {"unexpected": "dict"},
    FieldType.CRON: {"unexpected": "dict"},
    FieldType.TREE_SELECT: {"unexpected": "dict"},
    FieldType.SIGNATURE_PAD: {"unexpected": "dict"},
    FieldType.IMAGE_DROPZONE: "just a string",
    FieldType.MULTI_UPLOAD: {"unexpected": "dict, not a list"},
}


class TestWrongTypeRejected:
    @pytest.mark.parametrize("field_type", list(WRONG_TYPE_VALUES.keys()), ids=[ft.value for ft in WRONG_TYPE_VALUES])
    @pytest.mark.asyncio
    async def test_rejects_wrong_shape(self, validator: FormValidator, field_type: FieldType):
        field = _field(field_type)
        errors = await validator.validate_field(field, WRONG_TYPE_VALUES[field_type])
        assert errors, f"{field_type.value}: expected an error for {WRONG_TYPE_VALUES[field_type]!r}"


# ---------------------------------------------------------------------------
# AC3 — ai_capture accepts a nested object, a list and a scalar alike.
# ---------------------------------------------------------------------------


class TestAiCaptureUnconstrained:
    @pytest.mark.asyncio
    async def test_accepts_nested_object(self, validator: FormValidator):
        field = _field(FieldType.AI_CAPTURE)
        errors = await validator.validate_field(field, {"a": {"b": [1, 2, 3]}})
        assert errors == []

    @pytest.mark.asyncio
    async def test_accepts_list(self, validator: FormValidator):
        field = _field(FieldType.AI_CAPTURE)
        errors = await validator.validate_field(field, [1, 2, 3])
        assert errors == []

    @pytest.mark.asyncio
    async def test_accepts_scalar(self, validator: FormValidator):
        field = _field(FieldType.AI_CAPTURE)
        errors = await validator.validate_field(field, "a plain scalar answer")
        assert errors == []

    @pytest.mark.asyncio
    async def test_rejects_non_json_serialisable(self, validator: FormValidator):
        """A value with no schema at all is still not *anything* — reject
        what json.dumps() itself cannot serialise."""
        field = _field(FieldType.AI_CAPTURE)
        errors = await validator.validate_field(field, {1, 2, 3})  # a set — not JSON-serialisable
        assert errors


# ---------------------------------------------------------------------------
# AC4 — image_dropzone accepts both the single and the list form (single
# form covered in TestValidValuesAccepted; list form has its own test above).
# ---------------------------------------------------------------------------


class TestCronArity:
    """cron — validate the 5-field arity, not the semantics of each field."""

    @pytest.mark.asyncio
    async def test_rejects_wrong_arity(self, validator: FormValidator):
        field = _field(FieldType.CRON)
        errors = await validator.validate_field(field, "0 0 * *")  # 4 fields
        assert errors


class TestMultiUploadEnvelopeShape:
    @pytest.mark.asyncio
    async def test_rejects_envelope_missing_blob_ref(self, validator: FormValidator):
        field = _field(FieldType.MULTI_UPLOAD)
        errors = await validator.validate_field(field, [{"answer": "a1"}])
        assert errors


# ---------------------------------------------------------------------------
# AC5 — no existing branch changes behaviour. Spot-checked here; the full
# regression sweep is the existing suite (run separately by the worker).
# ---------------------------------------------------------------------------


class TestExistingBranchesUnaffected:
    @pytest.mark.asyncio
    async def test_text_field_still_validates(self, validator: FormValidator):
        field = FormField(field_id="name", field_type=FieldType.TEXT, label="Name")
        errors = await validator.validate_field(field, "Jane Doe")
        assert errors == []

    @pytest.mark.asyncio
    async def test_location_still_validates(self, validator: FormValidator):
        field = FormField(field_id="country", field_type=FieldType.LOCATION, label="Country")
        errors = await validator.validate_field(field, "CA")
        assert errors == []
