"""Unit tests for networkninja importer extensions (FEAT-300 TASK-006)."""

import json

import pytest

from parrot_formdesigner.core.schema import FormType
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools.services.networkninja import (
    ImportDiffEntry,
    ImportDiffReport,
    NetworkninjaFormService,
)


# ---------------------------------------------------------------------------
# Spec §4 fixtures (verbatim from spec)
# ---------------------------------------------------------------------------


@pytest.fixture
def networkninja_formula_row():
    """Minimal networkninja row with a FIELD_FORMULA column (options=[])."""
    return {
        "formid": 999,
        "orgid": 1,
        "form_name": "Formula Test",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "1",
                        "question_description": "Total Price",
                        "question_logic_groups": [],
                        "validations": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "1",
                "data_type": "FIELD_FORMULA",
                "description": "Total Price",
                "options": [],
            }
        ],
    }


@pytest.fixture
def networkninja_legacy_double_encoded_row():
    """Legacy double-encoded row (JSON string with question_block_* keys)."""
    return {
        "formid": 998,
        "orgid": 1,
        "form_name": "Legacy Encoded Test",
        "description": None,
        "question_blocks": (
            '[{"question_block_id":1,"question_block_type":"simple",'
            '"question_block_logic_groups":[],'
            '"questions":[{"question_id":1,"question_column_name":"1",'
            '"question_description":"Q1"}]}]'
        ),
        "metadata": [
            {
                "column_id": 1,
                "column_name": "1",
                "data_type": "FIELD_TEXT",
                "description": "Q1",
                "options": [],
            }
        ],
    }


@pytest.fixture
def networkninja_survey_row():
    """Survey-type row (block_type='survey'), modeled on live formid 71."""
    return {
        "formid": 997,
        "orgid": 1,
        "form_name": "Survey Test",
        "description": None,
        "question_blocks": [
            {
                "block_id": 210,
                "block_type": "survey",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "1",
                        "question_description": "Aisle number",
                        "question_logic_groups": [],
                        "validations": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "1",
                "data_type": "FIELD_TEXT",
                "description": "Aisle number",
                "options": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _svc() -> NetworkninjaFormService:
    """Return a NetworkninjaFormService with no DB (test-only)."""
    return NetworkninjaFormService(dsn="postgres://test")


def _make_row(data_type: str, col_name: str = "c1") -> dict:
    """Build a minimal row for a single-field form."""
    return {
        "formid": 1,
        "orgid": 1,
        "form_name": f"Test {data_type}",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": col_name,
                        "question_description": "Q",
                        "question_logic_groups": [],
                        "validations": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": col_name,
                "data_type": data_type,
                "description": "Q",
                "options": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# ImportDiffReport model
# ---------------------------------------------------------------------------


def test_import_diff_report_model():
    """ImportDiffReport is a valid Pydantic v2 model."""
    from datetime import datetime, timezone

    report = ImportDiffReport(
        form_id="f1",
        source="networkninja",
        imported_at=datetime.now(timezone.utc),
        fields=[],
    )
    assert report.source == "networkninja"
    assert report.fields == []


def test_import_diff_entry_model():
    """ImportDiffEntry validates correctly."""
    entry = ImportDiffEntry(
        column_name="c1",
        source_data_type="FIELD_FORMULA",
        mapped_field_type="formula",
        status="requiere_intervencion",
        note="expression unavailable",
    )
    assert entry.status == "requiere_intervencion"


# ---------------------------------------------------------------------------
# FIELD_FORMULA mapping
# ---------------------------------------------------------------------------


def test_networkninja_formula_mapping(networkninja_formula_row):
    """FIELD_FORMULA maps to FieldType.FORMULA with meta.expression=None."""
    svc = _svc()
    schema = svc.to_form_schema(networkninja_formula_row)
    fields = list(schema.iter_all_fields())
    assert any(f.field_type == FieldType.FORMULA for f in fields), (
        "Expected at least one FORMULA field"
    )
    formula_field = next(f for f in fields if f.field_type == FieldType.FORMULA)
    assert formula_field.meta is not None
    assert formula_field.meta.get("expression") is None


def test_networkninja_formula_no_expression(networkninja_formula_row):
    """FIELD_FORMULA row yields a requiere_intervencion report entry."""
    svc = _svc()
    schema, report = svc.import_with_report(networkninja_formula_row)
    assert isinstance(report, ImportDiffReport)
    formula_entries = [e for e in report.fields if e.source_data_type == "FIELD_FORMULA"]
    assert formula_entries, "Expected at least one FIELD_FORMULA report entry"
    assert formula_entries[0].status == "requiere_intervencion"
    assert formula_entries[0].mapped_field_type == "formula"


# ---------------------------------------------------------------------------
# FIELD_SIGNATURE_CAPTURE (no longer skipped)
# ---------------------------------------------------------------------------


def test_networkninja_signature_mapping():
    """FIELD_SIGNATURE_CAPTURE now maps to FieldType.SIGNATURE (not skipped)."""
    svc = _svc()
    schema = svc.to_form_schema(_make_row("FIELD_SIGNATURE_CAPTURE"))
    fields = list(schema.iter_all_fields())
    assert any(f.field_type == FieldType.SIGNATURE for f in fields), (
        "Expected SIGNATURE field; FIELD_SIGNATURE_CAPTURE must not be skipped"
    )


# ---------------------------------------------------------------------------
# Survey block_type detection
# ---------------------------------------------------------------------------


def test_networkninja_survey_block_type(networkninja_survey_row):
    """A block with block_type='survey' → FormSchema.form_type == SURVEY."""
    svc = _svc()
    schema = svc.to_form_schema(networkninja_survey_row)
    assert schema.form_type == FormType.SURVEY


def test_networkninja_simple_block_type():
    """A block with block_type='simple' → FormSchema.form_type == SIMPLE."""
    svc = _svc()
    schema = svc.to_form_schema(_make_row("FIELD_TEXT"))
    assert schema.form_type == FormType.SIMPLE


# ---------------------------------------------------------------------------
# Legacy double-encoded blocks
# ---------------------------------------------------------------------------


def test_networkninja_legacy_double_encoded_blocks(networkninja_legacy_double_encoded_row):
    """Legacy string-encoded blocks (question_block_* keys) decode correctly."""
    svc = _svc()
    schema = svc.to_form_schema(networkninja_legacy_double_encoded_row)
    assert schema.sections, "Expected at least one section after legacy decode"
    fields = list(schema.iter_all_fields())
    assert fields, "Expected at least one field from legacy-decoded blocks"


def test_networkninja_legacy_null_block_type():
    """Legacy blocks with null question_block_type default to 'simple'."""
    row = {
        "formid": 11,
        "orgid": 1,
        "form_name": "Null Type",
        "description": None,
        "question_blocks": json.dumps(
            [
                {
                    "question_block_id": 1,
                    "question_block_type": None,
                    "question_block_logic_groups": [],
                    "questions": [
                        {
                            "question_id": 1,
                            "question_column_name": "c1",
                            "question_description": "Q",
                        }
                    ],
                }
            ]
        ),
        "metadata": [
            {"column_id": 1, "column_name": "c1", "data_type": "FIELD_TEXT", "description": "Q"}
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    assert schema.form_type == FormType.SIMPLE


# ---------------------------------------------------------------------------
# Unmappable field — no abort
# ---------------------------------------------------------------------------


def test_networkninja_unmappable_field_no_abort():
    """Unknown data_type does not abort the import; report entry is generated."""
    row = _make_row("FIELD_TOTALLY_UNKNOWN")
    svc = _svc()
    schema, report = svc.import_with_report(row)
    # Form is returned (not raised)
    assert schema is not None
    # Report entry for the unmappable field
    entries = [e for e in report.fields if e.source_data_type == "FIELD_TOTALLY_UNKNOWN"]
    assert entries, "Expected report entry for unknown data_type"
    assert entries[0].status == "requiere_intervencion"
    assert entries[0].mapped_field_type is None


def test_networkninja_unmappable_field_draft_form():
    """A form with unmappable fields is left as draft (published_version=None)."""
    row = _make_row("FIELD_TOTALLY_UNKNOWN")
    svc = _svc()
    schema, _ = svc.import_with_report(row)
    assert schema.published_version is None


# ---------------------------------------------------------------------------
# Formula dangling reference
# ---------------------------------------------------------------------------


def test_networkninja_formula_dangling_reference():
    """Formula field referencing a deleted source field imports without crash."""
    row = {
        "formid": 100,
        "orgid": 1,
        "form_name": "Dangling Ref",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 99,
                        "question_column_name": "formula_col",
                        "question_description": "Computed",
                        "question_logic_groups": [],
                        "validations": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 99,
                "column_name": "formula_col",
                "data_type": "FIELD_FORMULA",
                "description": "Computed",
                "options": [],
            }
        ],
    }
    svc = _svc()
    # Must not raise
    schema, report = svc.import_with_report(row)
    assert schema is not None
    entries = [e for e in report.fields if e.source_data_type == "FIELD_FORMULA"]
    assert entries[0].status == "requiere_intervencion"


# ---------------------------------------------------------------------------
# All 9 new map entries — parametrized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data_type, expected_type",
    [
        ("FIELD_IMAGE_UPLOAD", FieldType.FILE),
        ("FIELD_AGREEMENT_CHECKBOX", FieldType.BOOLEAN),
        ("FIELD_DURATION", FieldType.TEXT),
        ("FIELD_DATETIME", FieldType.DATETIME),
        ("FIELD_TIME", FieldType.TIME),
        ("FIELD_HYPERLINK", FieldType.URL),
        ("FIELD_PHONENUMBER", FieldType.PHONE),
        ("FIELD_TOTAL", FieldType.FORMULA),
        ("FIELD_SIGNATURE_CAPTURE", FieldType.SIGNATURE),
    ],
)
def test_new_map_entries_all_covered(data_type: str, expected_type: FieldType):
    """Each of the 9 new/fixed map entries maps to the expected FieldType."""
    svc = _svc()
    schema = svc.to_form_schema(_make_row(data_type))
    fields = list(schema.iter_all_fields())
    assert fields, f"Expected at least one field for data_type '{data_type}'"
    assert fields[0].field_type == expected_type, (
        f"data_type '{data_type}' mapped to {fields[0].field_type!r}, expected {expected_type!r}"
    )


# ---------------------------------------------------------------------------
# FIELD_TOTAL (approximate mapping — render_as='total')
# ---------------------------------------------------------------------------


def test_networkninja_total_maps_to_formula_with_render_as():
    """FIELD_TOTAL maps to FORMULA with meta.render_as='total'."""
    svc = _svc()
    schema = svc.to_form_schema(_make_row("FIELD_TOTAL"))
    fields = list(schema.iter_all_fields())
    total_field = fields[0]
    assert total_field.field_type == FieldType.FORMULA
    assert total_field.meta is not None
    assert total_field.meta.get("render_as") == "total"


# ---------------------------------------------------------------------------
# Report statuses
# ---------------------------------------------------------------------------


def test_report_mapeado_status():
    """Fully mapped fields have status='mapeado'."""
    svc = _svc()
    _, report = svc.import_with_report(_make_row("FIELD_TEXT"))
    assert report.fields
    assert report.fields[0].status == "mapeado"


def test_report_aproximado_status():
    """Approximate mappings (e.g. FIELD_MONEY with render_as) have status='aproximado'."""
    svc = _svc()
    _, report = svc.import_with_report(_make_row("FIELD_MONEY"))
    assert report.fields
    assert report.fields[0].status == "aproximado"
