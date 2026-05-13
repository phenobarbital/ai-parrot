"""Tests for NetworkninjaFormService — relocated from test_database_form.py (TASK-1130).

Tests cover:
- DB field type → FieldType mapping
- Conditional logic translation (single, multi-condition OR, multi-group AND)
- Validation mapping (responseRequired → required=True)
- Edge cases (unsupported types, missing metadata, display-only fields, file upload)
- Full form generation from a mock DB result
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from parrot_formdesigner.tools.services import NetworkninjaFormService
from parrot_formdesigner.tools.services.networkninja import _FIELD_TYPE_MAP
from parrot_formdesigner.core.constraints import ConditionOperator
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.core.types import FieldType


# ---------------------------------------------------------------------------
# Helpers — build a minimal service without a real DB
# ---------------------------------------------------------------------------


def _make_service() -> NetworkninjaFormService:
    """Return a NetworkninjaFormService without DB access (DSN is unused here)."""
    return NetworkninjaFormService(dsn="postgres://fake/db")


def _build(row: dict[str, Any]) -> FormSchema:
    """Build a FormSchema from a mock DB row using the service's pipeline."""
    return _make_service().to_form_schema(row)


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
# TestFullFormGeneration — integration tests with mocked fetch
# ===========================================================================


class TestFullFormGeneration:
    """Integration tests: mock fetch and run the full pipeline on the service."""

    @pytest.mark.asyncio
    async def test_full_form_from_mock_fetch(
        self, sample_db_row: dict[str, Any]
    ) -> None:
        """Full pipeline from mock fetch result produces a valid FormSchema."""
        svc = _make_service()

        with patch.object(svc, "fetch", new=AsyncMock(return_value=sample_db_row)):
            raw = await svc.fetch(formid=4, orgid=71)

        form = svc.to_form_schema(raw)

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

    def test_malformed_json_raises(self) -> None:
        """Invalid question_blocks JSON → json.JSONDecodeError."""
        import json as _json
        svc = _make_service()
        bad_row = {
            "formid": 5,
            "form_name": "Bad Form",
            "description": None,
            "orgid": 1,
            "question_blocks": "THIS IS NOT JSON }{",
            "metadata": [],
        }
        with pytest.raises(_json.JSONDecodeError):
            svc.to_form_schema(bad_row)

    def test_dsn_resolution_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DSN resolution: explicit arg > PARROT_NETWORKNINJA_DSN > parrot.conf."""
        # Constructor arg wins
        monkeypatch.delenv("PARROT_NETWORKNINJA_DSN", raising=False)
        svc = NetworkninjaFormService(dsn="postgres://explicit")
        assert svc._get_dsn() == "postgres://explicit"

        # Env var used when no constructor arg
        monkeypatch.setenv("PARROT_NETWORKNINJA_DSN", "postgres://from-env")
        svc2 = NetworkninjaFormService()
        assert svc2._get_dsn() == "postgres://from-env"
