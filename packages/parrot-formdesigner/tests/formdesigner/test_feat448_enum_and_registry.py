"""Tests for TASK-2332 (FEAT-448) — enum values + registry entries for the
client's eleven types.

Before this lands, a ``FormSchema`` carrying any of these eleven types fails
to parse at all (strict enum on ``FormField.field_type``). AC1/AC2 assert the
schema parses; AC3 asserts the control-registry entry that
``GET /api/v1/form-controls`` serves; AC4 asserts the 33 pre-existing values
are untouched.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.controls.builtin import _BUILTIN_METADATA
from parrot_formdesigner.controls.registry import get_controls
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

CLIENT_ELEVEN = [
    FieldType.SEARCH,
    FieldType.MASKED,
    FieldType.COLOR_PICKER,
    FieldType.EMOJI,
    FieldType.CRON,
    FieldType.TREE_SELECT,
    FieldType.SIGNATURE_PAD,
    FieldType.CREDIT_CARD,
    FieldType.IMAGE_DROPZONE,
    FieldType.MULTI_UPLOAD,
    FieldType.AI_CAPTURE,
]

# The 33 values that existed before FEAT-448 (verified against core/types.py).
PRE_EXISTING_33 = {
    "text",
    "text_area",
    "number",
    "integer",
    "boolean",
    "date",
    "datetime",
    "time",
    "select",
    "multi_select",
    "file",
    "image",
    "color",
    "url",
    "email",
    "phone",
    "password",
    "hidden",
    "group",
    "array",
    "signature",
    "dynamic_select",
    "transfer_list",
    "remote_response",
    "availability",
    "location",
    "tags",
    "nps",
    "likert",
    "ranking",
    "rest",
    "audio",
    "formula",
}


class TestFieldTypeEnumMembers:
    """AC1 — FormField constructs for all eleven, one case per type."""

    @pytest.mark.parametrize("field_type", CLIENT_ELEVEN, ids=[ft.value for ft in CLIENT_ELEVEN])
    def test_formfield_constructs(self, field_type: FieldType):
        field = FormField(field_id="f1", field_type=field_type, label="L")
        assert field.field_type == field_type

    @pytest.mark.parametrize("field_type", CLIENT_ELEVEN, ids=[ft.value for ft in CLIENT_ELEVEN])
    def test_value_matches_client_string(self, field_type: FieldType):
        """The enum value must be the client's exact string, no near-misses."""
        assert field_type.value == field_type.name.lower()


class TestFormSchemaParsesAllEleven:
    """AC2 — a FormSchema containing all eleven at once parses."""

    def test_schema_with_all_eleven_parses(self):
        fields = [FormField(field_id=f"f_{ft.value}", field_type=ft, label=ft.value) for ft in CLIENT_ELEVEN]
        schema = FormSchema(
            form_id="feat448-client-eleven",
            title="Client Eleven",
            sections=[FormSection(section_id="s1", fields=fields)],
        )
        assert len(list(schema.iter_all_fields())) == len(CLIENT_ELEVEN)


class TestControlRegistryEntries:
    """AC3 — GET /api/v1/form-controls serves all eleven with metadata."""

    @pytest.mark.parametrize("field_type", CLIENT_ELEVEN, ids=[ft.value for ft in CLIENT_ELEVEN])
    def test_builtin_metadata_present(self, field_type: FieldType):
        assert field_type in _BUILTIN_METADATA

    @pytest.mark.parametrize("field_type", CLIENT_ELEVEN, ids=[ft.value for ft in CLIENT_ELEVEN])
    def test_builtin_metadata_has_nonempty_label_and_known_category(self, field_type: FieldType):
        entry = _BUILTIN_METADATA[field_type]
        assert entry["label"]
        assert entry["category"] in {"basic", "selection", "media", "layout", "advanced"}

    def test_registry_serves_all_eleven(self):
        types = {c.type for c in get_controls()}
        for ft in CLIENT_ELEVEN:
            assert ft.value in types


class TestPreExisting33Untouched:
    """AC4 — the 33 pre-existing enum values are untouched, asserted by value."""

    def test_all_pre_existing_values_present(self):
        current_values = {ft.value for ft in FieldType}
        assert PRE_EXISTING_33.issubset(current_values)

    def test_pre_existing_count(self):
        assert len(PRE_EXISTING_33) == 33
