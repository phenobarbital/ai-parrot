"""Unit and integration tests for DatabaseFormTool (TASK-547).

Tests cover:
- DB field type → FieldType mapping
- Conditional logic translation (single, multi-condition OR, multi-group AND)
- Validation mapping (responseRequired → required=True)
- Edge cases (unsupported types, missing metadata, display-only fields, file upload)
- Full form generation from a mock DB result
- Error paths (form not found, malformed JSON)
- Registry registration verification
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.forms import DatabaseFormTool, FormRegistry
from parrot.forms.constraints import ConditionOperator
from parrot.forms.schema import FormSchema
from parrot.forms.tools.database_form import _FIELD_TYPE_MAP
from parrot.forms.types import FieldType


# ---------------------------------------------------------------------------
# Helpers — build a minimal tool without a real DB
# ---------------------------------------------------------------------------


def _make_tool(registry: FormRegistry | None = None) -> DatabaseFormTool:
    """Return a DatabaseFormTool backed by a fresh FormRegistry (no DB needed)."""
    if registry is None:
        registry = FormRegistry()
    return DatabaseFormTool(registry=registry, dsn="postgres://fake/db")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> FormRegistry:
    """Fresh FormRegistry for each test."""
    return FormRegistry()


@pytest.fixture
def sample_db_row() -> dict[str, Any]:
    """Minimal form DB result: 1 block, 3 fields (TEXT, YES_NO, FLOAT2) + 1 conditional."""
    return {
        "formid": 4,
        "form_name": "Assembly Checklist",
        "description": "Daily assembly report",
        "client_id": 1,
        "client_name": "TestClient",
        "orgid": 71,
        "question_blocks": json.dumps([
            {
                "question_block_id": 1,
                "question_block_type": "simple",
                "questions": [
                    {
                        "question_id": 84,
                        "question_column_name": 8550,
                        "question_description": "Manager name",
                        "logic_groups": [],
                        "validations": [{"validation_type": "responseRequired"}],
                    },
                    {
                        "question_id": 85,
                        "question_column_name": 8551,
                        "question_description": "Area ready?",
                        "logic_groups": [],
                        "validations": [{"validation_type": "responseRequired"}],
                    },
                    {
                        "question_id": 86,
                        "question_column_name": 8552,
                        "question_description": "Time to get ready",
                        "logic_groups": [
                            {
                                "logic_group_id": 1,
                                "conditions": [
                                    {
                                        "condition_logic": "EQUALS",
                                        "condition_comparison_value": "0",
                                        "condition_question_reference_id": 85,
                                        "condition_option_id": None,
                                    }
                                ],
                            }
                        ],
                        "validations": [{"validation_type": "responseRequired"}],
                    },
                ],
            }
        ]),
        "metadata": [
            {
                "column_id": 84,
                "column_name": "8550",
                "data_type": "FIELD_TEXT",
                "description": "Manager name",
            },
            {
                "column_id": 85,
                "column_name": "8551",
                "data_type": "FIELD_YES_NO",
                "description": "Area ready?",
            },
            {
                "column_id": 86,
                "column_name": "8552",
                "data_type": "FIELD_FLOAT2",
                "description": "Time to get ready",
            },
        ],
    }


@pytest.fixture
def sample_metadata_with_unsupported() -> list[dict[str, Any]]:
    """Metadata including an unsupported type (FIELD_SIGNATURE_CAPTURE)."""
    return [
        {
            "column_id": 272,
            "column_name": "8740",
            "data_type": "FIELD_SIGNATURE_CAPTURE",
            "description": "Signature",
        },
        {
            "column_id": 84,
            "column_name": "8550",
            "data_type": "FIELD_TEXT",
            "description": "Name",
        },
    ]


# ---------------------------------------------------------------------------
# Helper — call the internal _build_form_schema directly (no DB)
# ---------------------------------------------------------------------------


def _build(row: dict[str, Any], registry: FormRegistry | None = None) -> FormSchema:
    """Build a FormSchema from a mock DB row using the tool's private pipeline."""
    tool = _make_tool(registry)
    return tool._build_form_schema(row)


# ===========================================================================
# TestFieldTypeMapping
# ===========================================================================


class TestFieldTypeMapping:
    """Each DB data_type maps to the correct FieldType (and extra kwargs)."""

    def test_field_text(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_TEXT"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.TEXT
        assert extra == {}

    def test_field_textarea(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_TEXTAREA"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.TEXT_AREA
        assert extra == {}

    def test_field_integer(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_INTEGER"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.INTEGER
        assert extra == {}

    def test_field_float2(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_FLOAT2"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.NUMBER
        assert extra == {}

    def test_field_yes_no(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_YES_NO"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.BOOLEAN
        assert extra == {}

    def test_field_multiselect(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_MULTISELECT"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.MULTI_SELECT
        assert extra == {}

    def test_field_image_upload(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_IMAGE_UPLOAD_MULTIPLE"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.FILE
        assert extra.get("meta") == {"accept": "image/*", "multiple": True}

    def test_display_text_readonly(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_DISPLAY_TEXT"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.TEXT
        assert extra.get("read_only") is True
        assert extra.get("meta", {}).get("render_as") == "display_text"

    def test_display_image_readonly(self) -> None:
        mapping = _FIELD_TYPE_MAP["FIELD_DISPLAY_IMAGE"]
        assert mapping is not None
        field_type, extra = mapping
        assert field_type == FieldType.IMAGE
        assert extra.get("read_only") is True
        assert extra.get("meta", {}).get("render_as") == "display_image"

    def test_unsupported_type_skipped(self) -> None:
        """FIELD_SIGNATURE_CAPTURE must be mapped to None (skip with warning)."""
        assert "FIELD_SIGNATURE_CAPTURE" in _FIELD_TYPE_MAP
        assert _FIELD_TYPE_MAP["FIELD_SIGNATURE_CAPTURE"] is None


# ===========================================================================
# TestConditionalLogic
# ===========================================================================


class TestConditionalLogic:
    """logic_groups translate correctly to DependencyRule."""

    def _make_row_with_logic(
        self, logic_groups: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build a minimal DB row with the given logic_groups on question 86."""
        return {
            "formid": 1,
            "form_name": "Test",
            "description": None,
            "orgid": 1,
            "question_blocks": json.dumps([
                {
                    "question_block_id": 1,
                    "questions": [
                        {
                            "question_id": 85,
                            "question_column_name": 8551,
                            "question_description": "Trigger field",
                            "logic_groups": [],
                            "validations": [],
                        },
                        {
                            "question_id": 86,
                            "question_column_name": 8552,
                            "question_description": "Conditional field",
                            "logic_groups": logic_groups,
                            "validations": [],
                        },
                    ],
                }
            ]),
            "metadata": [
                {
                    "column_id": 85,
                    "column_name": "8551",
                    "data_type": "FIELD_YES_NO",
                    "description": "Trigger",
                },
                {
                    "column_id": 86,
                    "column_name": "8552",
                    "data_type": "FIELD_TEXT",
                    "description": "Conditional",
                },
            ],
        }

    def test_single_condition_eq(self) -> None:
        """Single condition → DependencyRule with EQ operator."""
        logic_groups = [
            {
                "logic_group_id": 1,
                "conditions": [
                    {
                        "condition_logic": "EQUALS",
                        "condition_comparison_value": "yes",
                        "condition_question_reference_id": 85,
                        "condition_option_id": None,
                    }
                ],
            }
        ]
        row = self._make_row_with_logic(logic_groups)
        form = _build(row)
        section = form.sections[0]
        # The second field (8552) should have a dependency rule
        field = next(f for f in section.fields if f.field_id == "field_8552")
        assert field.depends_on is not None
        rule = field.depends_on
        assert rule.effect == "show"
        assert len(rule.conditions) == 1
        cond = rule.conditions[0]
        assert cond.field_id == "field_8551"
        assert cond.operator == ConditionOperator.EQ
        assert cond.value == "yes"

    def test_multi_conditions_or(self) -> None:
        """Multiple conditions in one logic_group → logic='or'."""
        logic_groups = [
            {
                "logic_group_id": 1,
                "conditions": [
                    {
                        "condition_logic": "EQUALS",
                        "condition_comparison_value": "yes",
                        "condition_question_reference_id": 85,
                        "condition_option_id": None,
                    },
                    {
                        "condition_logic": "EQUALS",
                        "condition_comparison_value": "maybe",
                        "condition_question_reference_id": 85,
                        "condition_option_id": None,
                    },
                ],
            }
        ]
        row = self._make_row_with_logic(logic_groups)
        form = _build(row)
        field = next(
            f
            for f in form.sections[0].fields
            if f.field_id == "field_8552"
        )
        assert field.depends_on is not None
        assert field.depends_on.logic == "or"
        assert len(field.depends_on.conditions) == 2

    def test_multi_groups_and(self) -> None:
        """Multiple logic_groups → logic='and'."""
        logic_groups = [
            {
                "logic_group_id": 1,
                "conditions": [
                    {
                        "condition_logic": "EQUALS",
                        "condition_comparison_value": "yes",
                        "condition_question_reference_id": 85,
                        "condition_option_id": None,
                    }
                ],
            },
            {
                "logic_group_id": 2,
                "conditions": [
                    {
                        "condition_logic": "EQUALS",
                        "condition_comparison_value": "confirmed",
                        "condition_question_reference_id": 85,
                        "condition_option_id": None,
                    }
                ],
            },
        ]
        row = self._make_row_with_logic(logic_groups)
        form = _build(row)
        field = next(
            f
            for f in form.sections[0].fields
            if f.field_id == "field_8552"
        )
        assert field.depends_on is not None
        assert field.depends_on.logic == "and"
        assert len(field.depends_on.conditions) == 2

    def test_question_id_to_field_id_resolution(self) -> None:
        """condition_question_reference_id → question_id → column_name → field_id."""
        # question_id=85 → question_column_name=8551 → column_name="8551" → field_id="field_8551"
        logic_groups = [
            {
                "logic_group_id": 1,
                "conditions": [
                    {
                        "condition_logic": "EQUALS",
                        "condition_comparison_value": "1",
                        "condition_question_reference_id": 85,
                        "condition_option_id": None,
                    }
                ],
            }
        ]
        row = self._make_row_with_logic(logic_groups)
        form = _build(row)
        field = next(
            f
            for f in form.sections[0].fields
            if f.field_id == "field_8552"
        )
        assert field.depends_on is not None
        assert field.depends_on.conditions[0].field_id == "field_8551"


# ===========================================================================
# TestValidationMapping
# ===========================================================================


class TestValidationMapping:
    """responseRequired maps correctly to required=True."""

    def test_response_required(self, sample_db_row: dict[str, Any]) -> None:
        form = _build(sample_db_row)
        # All three fields in sample_db_row have responseRequired
        for field in form.sections[0].fields:
            assert field.required is True, f"field {field.field_id} should be required"

    def test_no_validations(self) -> None:
        """Question with empty validations → required=False."""
        row = {
            "formid": 1,
            "form_name": "Test",
            "description": None,
            "orgid": 1,
            "question_blocks": json.dumps([
                {
                    "question_block_id": 1,
                    "questions": [
                        {
                            "question_id": 1,
                            "question_column_name": 100,
                            "question_description": "Optional field",
                            "logic_groups": [],
                            "validations": [],
                        }
                    ],
                }
            ]),
            "metadata": [
                {
                    "column_id": 1,
                    "column_name": "100",
                    "data_type": "FIELD_TEXT",
                    "description": "Optional",
                }
            ],
        }
        form = _build(row)
        field = form.sections[0].fields[0]
        assert field.required is False


# ===========================================================================
# TestQuestionBlockSections
# ===========================================================================


class TestQuestionBlockSections:
    """Each question_block becomes a separate FormSection."""

    def test_blocks_to_sections(self) -> None:
        """Two question blocks → two FormSections."""
        row = {
            "formid": 10,
            "form_name": "Multi-Block Form",
            "description": None,
            "orgid": 1,
            "question_blocks": json.dumps([
                {
                    "question_block_id": 11,
                    "questions": [
                        {
                            "question_id": 1,
                            "question_column_name": 100,
                            "question_description": "Block A field",
                            "logic_groups": [],
                            "validations": [],
                        }
                    ],
                },
                {
                    "question_block_id": 22,
                    "questions": [
                        {
                            "question_id": 2,
                            "question_column_name": 200,
                            "question_description": "Block B field",
                            "logic_groups": [],
                            "validations": [],
                        }
                    ],
                },
            ]),
            "metadata": [
                {
                    "column_id": 1,
                    "column_name": "100",
                    "data_type": "FIELD_INTEGER",
                    "description": "Block A field",
                },
                {
                    "column_id": 2,
                    "column_name": "200",
                    "data_type": "FIELD_TEXT",
                    "description": "Block B field",
                },
            ],
        }
        form = _build(row)
        assert len(form.sections) == 2
        section_ids = {s.section_id for s in form.sections}
        assert "section_11" in section_ids
        assert "section_22" in section_ids

    def test_question_not_in_metadata_skipped(
        self, sample_metadata_with_unsupported: list[dict[str, Any]]
    ) -> None:
        """Question whose column_name is absent from metadata is silently dropped."""
        row = {
            "formid": 1,
            "form_name": "Test",
            "description": None,
            "orgid": 1,
            "question_blocks": json.dumps([
                {
                    "question_block_id": 1,
                    "questions": [
                        {
                            "question_id": 99,
                            "question_column_name": 9999,  # NOT in metadata
                            "question_description": "Ghost field",
                            "logic_groups": [],
                            "validations": [],
                        },
                        {
                            "question_id": 84,
                            "question_column_name": 8550,  # IS in metadata
                            "question_description": "Name",
                            "logic_groups": [],
                            "validations": [],
                        },
                    ],
                }
            ]),
            "metadata": sample_metadata_with_unsupported,
        }
        form = _build(row)
        # Only "8550" (FIELD_TEXT) should be included — "9999" missing and "8740" unsupported
        assert len(form.sections) == 1
        assert len(form.sections[0].fields) == 1
        assert form.sections[0].fields[0].field_id == "field_8550"

    def test_form_header_mapping(self, sample_db_row: dict[str, Any]) -> None:
        """form_name → title, formid+orgid → form_id."""
        form = _build(sample_db_row)
        assert "Assembly Checklist" in str(form.title)
        assert "db-form-4" in form.form_id

    def test_display_field_read_only_and_meta(self) -> None:
        """FIELD_DISPLAY_TEXT → read_only=True + meta.render_as='display_text'."""
        row = {
            "formid": 1,
            "form_name": "Display Test",
            "description": None,
            "orgid": 1,
            "question_blocks": json.dumps([
                {
                    "question_block_id": 1,
                    "questions": [
                        {
                            "question_id": 1,
                            "question_column_name": 100,
                            "question_description": "Instructions",
                            "logic_groups": [],
                            "validations": [],
                        }
                    ],
                }
            ]),
            "metadata": [
                {
                    "column_id": 1,
                    "column_name": "100",
                    "data_type": "FIELD_DISPLAY_TEXT",
                    "description": "Instructions",
                }
            ],
        }
        form = _build(row)
        field = form.sections[0].fields[0]
        assert field.read_only is True
        assert field.meta is not None
        assert field.meta.get("render_as") == "display_text"

    def test_file_upload_meta(self) -> None:
        """FIELD_IMAGE_UPLOAD_MULTIPLE → file type with accept+multiple meta."""
        row = {
            "formid": 1,
            "form_name": "Upload Test",
            "description": None,
            "orgid": 1,
            "question_blocks": json.dumps([
                {
                    "question_block_id": 1,
                    "questions": [
                        {
                            "question_id": 1,
                            "question_column_name": 100,
                            "question_description": "Upload photos",
                            "logic_groups": [],
                            "validations": [],
                        }
                    ],
                }
            ]),
            "metadata": [
                {
                    "column_id": 1,
                    "column_name": "100",
                    "data_type": "FIELD_IMAGE_UPLOAD_MULTIPLE",
                    "description": "Upload photos",
                }
            ],
        }
        form = _build(row)
        field = form.sections[0].fields[0]
        assert field.field_type == FieldType.FILE
        assert field.meta is not None
        assert field.meta.get("accept") == "image/*"
        assert field.meta.get("multiple") is True


# ===========================================================================
# TestFullFormGeneration — integration tests with mocked DB
# ===========================================================================


class TestFullFormGeneration:
    """Integration tests: mock _fetch_form_row and run the full pipeline."""

    async def test_full_form_from_mock_db(
        self, sample_db_row: dict[str, Any], registry: FormRegistry
    ) -> None:
        """Full pipeline from mock DB result produces a valid FormSchema."""
        tool = _make_tool(registry)

        with patch.object(tool, "_fetch_form_row", new=AsyncMock(return_value=sample_db_row)):
            result = await tool._execute(formid=4, orgid=71)

        assert result.success is True
        assert result.status == "success"
        assert "form" in result.metadata

        form_dict = result.metadata["form"]
        form = FormSchema(**form_dict)
        assert form.form_id == "db-form-4-71"
        assert "Assembly Checklist" in str(form.title)
        assert len(form.sections) == 1

        section = form.sections[0]
        assert len(section.fields) == 3

        field_ids = {f.field_id for f in section.fields}
        assert "field_8550" in field_ids  # Manager name (TEXT)
        assert "field_8551" in field_ids  # Area ready? (YES_NO)
        assert "field_8552" in field_ids  # Time (FLOAT2) with conditional

        # Verify types
        by_id = {f.field_id: f for f in section.fields}
        assert by_id["field_8550"].field_type == FieldType.TEXT
        assert by_id["field_8551"].field_type == FieldType.BOOLEAN
        assert by_id["field_8552"].field_type == FieldType.NUMBER

        # All fields required
        for field in section.fields:
            assert field.required is True

        # Conditional on field_8552
        cond_field = by_id["field_8552"]
        assert cond_field.depends_on is not None
        assert cond_field.depends_on.conditions[0].field_id == "field_8551"
        assert cond_field.depends_on.conditions[0].operator == ConditionOperator.EQ
        assert cond_field.depends_on.conditions[0].value == "0"

    async def test_form_not_found(self, registry: FormRegistry) -> None:
        """Empty DB result (None) → error ToolResult."""
        tool = _make_tool(registry)

        with patch.object(tool, "_fetch_form_row", new=AsyncMock(return_value=None)):
            result = await tool._execute(formid=999, orgid=1)

        assert result.success is False
        assert result.status == "error"
        assert "not found" in result.metadata.get("error", "").lower()
        assert "999" in result.metadata.get("error", "")

    async def test_malformed_json(self, registry: FormRegistry) -> None:
        """Invalid question_blocks JSON → error ToolResult."""
        tool = _make_tool(registry)

        bad_row = {
            "formid": 5,
            "form_name": "Bad Form",
            "description": None,
            "orgid": 1,
            "question_blocks": "THIS IS NOT JSON }{",
            "metadata": [],
        }

        with patch.object(tool, "_fetch_form_row", new=AsyncMock(return_value=bad_row)):
            result = await tool._execute(formid=5, orgid=1)

        assert result.success is False
        assert result.status == "error"
        error_msg = result.metadata.get("error", "")
        assert "malformed" in error_msg.lower() or "json" in error_msg.lower()

    async def test_registry_registration(
        self, sample_db_row: dict[str, Any], registry: FormRegistry
    ) -> None:
        """Generated form is registered in FormRegistry and retrievable."""
        tool = _make_tool(registry)

        with patch.object(tool, "_fetch_form_row", new=AsyncMock(return_value=sample_db_row)):
            result = await tool._execute(formid=4, orgid=71)

        assert result.success is True

        # Form should be retrievable from registry
        form_id = "db-form-4-71"
        stored = await registry.get(form_id)
        assert stored is not None
        assert stored.form_id == form_id
        assert "Assembly Checklist" in str(stored.title)
