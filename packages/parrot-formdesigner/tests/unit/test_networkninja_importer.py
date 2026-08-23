"""Unit tests for networkninja importer extensions (FEAT-300 TASK-006)."""

import json

import pytest

from parrot_formdesigner.core.schema import FormType
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.tools.services.networkninja import (
    ImportDiffEntry,
    ImportDiffReport,
    NetworkninjaFormService,
    stable_form_uid,
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
    assert any(f.field_type == FieldType.FORMULA for f in fields), "Expected at least one FORMULA field"
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
    assert any(
        f.field_type == FieldType.SIGNATURE for f in fields
    ), "Expected SIGNATURE field; FIELD_SIGNATURE_CAPTURE must not be skipped"


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
        "metadata": [{"column_id": 1, "column_name": "c1", "data_type": "FIELD_TEXT", "description": "Q"}],
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
    assert (
        fields[0].field_type == expected_type
    ), f"data_type '{data_type}' mapped to {fields[0].field_type!r}, expected {expected_type!r}"


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


# ---------------------------------------------------------------------------
# FEAT-325 — form_metadata.options as the primary select-option source
# ---------------------------------------------------------------------------


def test_metadata_options_populate_select():
    """FIELD_SELECT with form_metadata.options yields FieldOption(value=option_id, label=option_value)."""
    row = {
        "formid": 1,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10211",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10211",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [
                    {
                        "is_active": True,
                        "option_id": "6091",
                        "column_name": 10211,
                        "option_value": "Field Merchandiser",
                    },
                ],
            }
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert field.options is not None
    assert len(field.options) == 1
    opt = field.options[0]
    assert opt.value == "6091"
    assert opt.label == "Field Merchandiser"
    assert opt.disabled is False


def test_metadata_options_scale_1_10():
    """A 1-10 scale select (options only in metadata) yields 10 options."""
    options = [
        {"is_active": True, "option_id": str(i), "column_name": 10212, "option_value": str(i)} for i in range(1, 11)
    ]
    row = {
        "formid": 2,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10212",
                        "question_description": "Quality",
                        "validations": [],
                        "question_logic_groups": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10212",
                "data_type": "FIELD_SELECT",
                "description": "Quality",
                "options": options,
            }
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert field.options is not None
    assert len(field.options) == 10


def test_inactive_option_marked_disabled():
    """is_active=false option imported with disabled=True, still present."""
    row = {
        "formid": 3,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10213",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10213",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [
                    {"is_active": True, "option_id": "1", "column_name": 10213, "option_value": "Active"},
                    {"is_active": False, "option_id": "2", "column_name": 10213, "option_value": "Retired"},
                ],
            }
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert {o.value for o in field.options} == {"1", "2"}
    retired = next(o for o in field.options if o.value == "2")
    assert retired.disabled is True


def test_metadata_primary_over_inline():
    """When both metadata and inline options exist, metadata wins."""
    row = {
        "formid": 4,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10214",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                        "options": [{"value": "inline1", "label": "Inline One"}],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10214",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [
                    {
                        "is_active": True,
                        "option_id": "6091",
                        "column_name": 10214,
                        "option_value": "Field Merchandiser",
                    },
                ],
            }
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert {o.value for o in field.options} == {"6091"}


def test_inline_fallback_when_metadata_empty():
    """Empty metadata options -> inline options used (no regression)."""
    row = {
        "formid": 5,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10215",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                        "options": [{"value": "inline1", "label": "Inline One"}],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10215",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [],
            }
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert {o.value for o in field.options} == {"inline1"}
    assert next(o for o in field.options if o.value == "inline1").label == "Inline One"


def test_logic_group_fallback_when_no_metadata():
    """No metadata catalog -> logic-group text used as value & label."""
    row = {
        "formid": 6,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10216",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                    {
                        "question_id": 2,
                        "question_column_name": "99",
                        "question_description": "Dep",
                        "validations": [],
                        "question_logic_groups": [
                            {
                                "conditions": [
                                    {
                                        "condition_logic": "EQUALS",
                                        "condition_question_reference_id": 1,
                                        "condition_comparison_value": "Field Merchandiser",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
        "metadata": [
            {"column_id": 1, "column_name": "10216", "data_type": "FIELD_SELECT", "description": "Role", "options": []},
            {"column_id": 2, "column_name": "99", "data_type": "FIELD_TEXT", "description": "Dep", "options": []},
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    fields = {f.field_id: f for f in schema.iter_all_fields()}
    role_field = fields["field_10216"]
    assert {o.value for o in role_field.options} == {"Field Merchandiser"}
    assert role_field.options[0].label == "Field Merchandiser"


def test_condition_reindexed_to_option_id():
    """EQUALS on a metadata-backed select -> FieldCondition.value == option_id."""
    row = {
        "formid": 7,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10217",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                    {
                        "question_id": 2,
                        "question_column_name": "99",
                        "question_description": "Dep",
                        "validations": [],
                        "question_logic_groups": [
                            {
                                "conditions": [
                                    {
                                        "condition_logic": "EQUALS",
                                        "condition_question_reference_id": 1,
                                        "condition_comparison_value": "Field Merchandiser",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10217",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [
                    {
                        "is_active": True,
                        "option_id": "6091",
                        "column_name": 10217,
                        "option_value": "Field Merchandiser",
                    },
                ],
            },
            {"column_id": 2, "column_name": "99", "data_type": "FIELD_TEXT", "description": "Dep", "options": []},
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    fields = {f.field_id: f for f in schema.iter_all_fields()}
    dep_field = fields["field_99"]
    assert dep_field.depends_on is not None
    assert dep_field.depends_on.conditions[0].value == "6091"


def test_condition_unmatched_comparison_value_preserved():
    """comparison_value absent from catalog -> original value kept, no crash."""
    row = {
        "formid": 8,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10218",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                    {
                        "question_id": 2,
                        "question_column_name": "99",
                        "question_description": "Dep",
                        "validations": [],
                        "question_logic_groups": [
                            {
                                "conditions": [
                                    {
                                        "condition_logic": "EQUALS",
                                        "condition_question_reference_id": 1,
                                        "condition_comparison_value": "Unknown Value",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10218",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [
                    {
                        "is_active": True,
                        "option_id": "6091",
                        "column_name": 10218,
                        "option_value": "Field Merchandiser",
                    },
                ],
            },
            {"column_id": 2, "column_name": "99", "data_type": "FIELD_TEXT", "description": "Dep", "options": []},
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    fields = {f.field_id: f for f in schema.iter_all_fields()}
    dep_field = fields["field_99"]
    assert dep_field.depends_on is not None
    assert dep_field.depends_on.conditions[0].value == "Unknown Value"


def test_options_source_provenance():
    """ImportDiffEntry.options_source is metadata/inline/logic_groups/none as appropriate."""
    row = {
        "formid": 9,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "meta_col",
                        "question_description": "Meta",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                    {
                        "question_id": 2,
                        "question_column_name": "inline_col",
                        "question_description": "Inline",
                        "validations": [],
                        "question_logic_groups": [],
                        "options": [{"value": "i1", "label": "Inline"}],
                    },
                    {
                        "question_id": 3,
                        "question_column_name": "logic_col",
                        "question_description": "Logic",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                    {
                        "question_id": 4,
                        "question_column_name": "none_col",
                        "question_description": "None",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                    {
                        "question_id": 5,
                        "question_column_name": "dep_col",
                        "question_description": "Dep",
                        "validations": [],
                        "question_logic_groups": [
                            {
                                "conditions": [
                                    {
                                        "condition_logic": "EQUALS",
                                        "condition_question_reference_id": 3,
                                        "condition_comparison_value": "Logic Value",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "meta_col",
                "data_type": "FIELD_SELECT",
                "description": "Meta",
                "options": [
                    {"is_active": True, "option_id": "1", "column_name": "meta_col", "option_value": "Meta Val"},
                ],
            },
            {
                "column_id": 2,
                "column_name": "inline_col",
                "data_type": "FIELD_SELECT",
                "description": "Inline",
                "options": [],
            },
            {
                "column_id": 3,
                "column_name": "logic_col",
                "data_type": "FIELD_SELECT",
                "description": "Logic",
                "options": [],
            },
            {
                "column_id": 4,
                "column_name": "none_col",
                "data_type": "FIELD_SELECT",
                "description": "None",
                "options": [],
            },
            {"column_id": 5, "column_name": "dep_col", "data_type": "FIELD_TEXT", "description": "Dep", "options": []},
        ],
    }
    svc = _svc()
    _, report = svc.import_with_report(row)
    by_col = {e.column_name: e for e in report.fields}
    assert by_col["meta_col"].options_source == "metadata"
    assert by_col["inline_col"].options_source == "inline"
    assert by_col["logic_col"].options_source == "logic_groups"
    assert by_col["none_col"].options_source == "none"
    assert by_col["dep_col"].options_source is None


def test_option_id_cast_to_str():
    """Integer option_id cast to str for FieldOption.value."""
    row = {
        "formid": 10,
        "orgid": 1,
        "form_name": "F",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "10219",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "10219",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [
                    {"is_active": True, "option_id": 6091, "column_name": 10219, "option_value": "Field Merchandiser"},
                ],
            }
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert field.options[0].value == "6091"
    assert isinstance(field.options[0].value, str)


def test_malformed_metadata_options_do_not_crash():
    """Non-list / non-dict ``form_metadata.options`` are coerced, never crash.

    Real flexroc data stores ``options`` as the double-encoded JSON string
    ``"[]"`` on some (non-select) columns, and occasionally as other scalars.
    The import must tolerate this: such columns yield no options and the form
    still builds (regression for the FEAT-325 re-import crash).
    """
    row = {
        "formid": 50,
        "orgid": 74,
        "form_name": "Lovesac Event Form",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 1,
                        "question_column_name": "2493",
                        "question_description": "Notes",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                    {
                        "question_id": 2,
                        "question_column_name": "2500",
                        "question_description": "Role",
                        "validations": [],
                        "question_logic_groups": [],
                    },
                ],
            }
        ],
        "metadata": [
            # double-encoded empty array as a JSON *string* on a text column
            {"column_id": 1, "column_name": "2493", "data_type": "FIELD_TEXT", "description": "Notes", "options": "[]"},
            # a well-formed select alongside it must still populate
            {
                "column_id": 2,
                "column_name": "2500",
                "data_type": "FIELD_SELECT",
                "description": "Role",
                "options": [
                    {"is_active": True, "option_id": "6091", "column_name": 2500, "option_value": "Field Merchandiser"},
                    "garbage-non-dict-entry",  # dropped, not crashed
                ],
            },
        ],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)  # must not raise
    fields = {f.field_id: f for f in schema.iter_all_fields()}
    # text column: no options
    assert not fields["field_2493"].options
    # select column: the one valid option survived, the non-dict was dropped
    assert [o.value for o in fields["field_2500"].options] == ["6091"]


# ---------------------------------------------------------------------------
# Stable import identity — re-import must be idempotent
# ---------------------------------------------------------------------------


def test_form_uid_is_stable_across_imports(networkninja_formula_row):
    """Two imports of the same source row yield the SAME form_uid.

    Regression: FormSchema.form_uid defaulted to uuid4(), so every import
    minted a new identity and re-registering hit FormRegistry's slug
    uniqueness check (FormAlreadyExistsError) while form_id stayed constant.
    """
    svc = _svc()
    first = svc.to_form_schema(networkninja_formula_row)
    second = svc.to_form_schema(networkninja_formula_row)

    assert first.form_id == second.form_id
    assert first.form_uid == second.form_uid
    assert first.form_uid == stable_form_uid(999, 1)


def test_child_uids_are_stable_across_imports(networkninja_survey_row):
    """section_uid / field_uid are derived, not random.

    field_uid-keyed state (answers, partial saves, resolved rules) must
    survive a re-import of the same source form.
    """
    svc = _svc()
    first = svc.to_form_schema(networkninja_survey_row)
    second = svc.to_form_schema(networkninja_survey_row)

    assert [s.section_uid for s in first.sections] == [s.section_uid for s in second.sections]
    assert {f.field_id: f.field_uid for f in first.iter_all_fields()} == {
        f.field_id: f.field_uid for f in second.iter_all_fields()
    }


def test_distinct_source_forms_get_distinct_uids(networkninja_formula_row):
    """A different (formid, orgid) must never collide with another form."""
    svc = _svc()
    base = svc.to_form_schema(networkninja_formula_row)

    other_form = {**networkninja_formula_row, "formid": 1000}
    other_org = {**networkninja_formula_row, "orgid": 2}

    uids = {
        base.form_uid,
        svc.to_form_schema(other_form).form_uid,
        svc.to_form_schema(other_org).form_uid,
    }
    assert len(uids) == 3


def test_all_uids_within_a_form_are_unique(networkninja_survey_row):
    """Deriving uids must not introduce duplicates inside one form."""
    svc = _svc()
    schema = svc.to_form_schema(networkninja_survey_row)

    uids = (
        [schema.form_uid] + [s.section_uid for s in schema.sections] + [f.field_uid for f in schema.iter_all_fields()]
    )
    assert len(uids) == len(set(uids))


@pytest.mark.asyncio
async def test_reimport_reregisters_without_slug_conflict(networkninja_formula_row):
    """The end-to-end symptom: re-registering a re-imported form must not raise.

    Before the fix this raised FormAlreadyExistsError ("Slug 'db-form-999-1'
    already in use by form_uid=..."), which DatabaseFormTool surfaced to the
    API as HTTP 500 "Form load succeeded but form_uid missing".
    """
    from parrot_formdesigner.services.registry import FormRegistry

    svc = _svc()
    registry = FormRegistry(require_tenant=False, default_tenant="troc")

    for _ in range(3):
        schema = svc.to_form_schema(networkninja_formula_row)
        await registry.register(schema, persist=False, tenant="troc")

    assert await registry.list_form_ids(tenant="troc") == ["db-form-999-1"]


# ---------------------------------------------------------------------------
# Section-level conditional logic (block_logic_groups)
# ---------------------------------------------------------------------------


def _gated_row(*, logic_key: str = "block_logic_groups") -> dict:
    """Row whose second block is gated on the answer to the first block.

    Mirrors the real shape of ``db-form-10-69`` (Epson Visit Form): one
    driver select up front, and the rest of the form gated on its value.
    """
    return {
        "formid": 10,
        "orgid": 69,
        "form_name": "Gated Form",
        "description": None,
        "question_blocks": [
            {
                "block_id": 18,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 566,
                        "question_column_name": "9050",
                        "question_description": "Please select the type of visit.",
                        "question_logic_groups": [],
                        "validations": [],
                    }
                ],
            },
            {
                "block_id": 168,
                "block_type": "simple",
                logic_key: [
                    {
                        "logic_group_id": 3210,
                        "conditions": [
                            {
                                "condition_id": 3414,
                                "condition_logic": "EQUALS",
                                "condition_option_id": 4784,
                                "condition_comparison_value": "Lunch & Learn",
                                "condition_question_reference_id": 566,
                            }
                        ],
                    }
                ],
                "questions": [
                    {
                        "question_id": 700,
                        "question_column_name": "9100",
                        "question_description": "How many attended?",
                        "question_logic_groups": [],
                        "validations": [],
                    }
                ],
            },
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "9050",
                "data_type": "FIELD_SELECT",
                "description": "Visit type",
                "options": [
                    {"option_id": "4784", "option_value": "Lunch & Learn", "column_name": 9050, "is_active": True},
                ],
            },
            {
                "column_id": 2,
                "column_name": "9100",
                "data_type": "FIELD_INTEGER",
                "description": "How many attended?",
                "options": [],
            },
        ],
    }


def test_block_logic_groups_become_section_depends_on():
    """A gated block must import as a section with a visibility rule.

    Regression for the Epson Visit Form (``db-form-10-69``): dropping
    ``block_logic_groups`` made 277 of 292 fields — 234 of them required —
    render unconditionally, which left the form impossible to submit.
    """
    schema = _svc().to_form_schema(_gated_row())

    driver, gated = schema.sections
    assert driver.depends_on is None
    assert gated.depends_on is not None
    assert gated.depends_on.effect == "show"

    (condition,) = gated.depends_on.conditions
    assert condition.field_id == "field_9050"
    assert condition.operator == "eq"
    # FEAT-325 re-indexing: human text → the metadata option_id, so the
    # condition shares the value-space of the driver's FieldOption values.
    assert condition.value == "4784"


def test_section_logic_reads_the_legacy_key_too():
    """``question_block_logic_groups`` is the legacy spelling of the key."""
    schema = _svc().to_form_schema(_gated_row(logic_key="question_block_logic_groups"))

    assert schema.sections[1].depends_on is not None


def test_ungated_block_gets_no_section_rule():
    """A block with no logic must not acquire a rule out of nowhere."""
    row = _gated_row()
    row["question_blocks"][1]["block_logic_groups"] = []

    schema = _svc().to_form_schema(row)

    assert all(section.depends_on is None for section in schema.sections)


# ---------------------------------------------------------------------------
# Numeric validations → FieldConstraints
# ---------------------------------------------------------------------------


def _validated_row(data_type: str, validations: list[dict]) -> dict:
    row = _make_row(data_type, col_name="9023")
    row["question_blocks"][0]["questions"][0]["validations"] = validations
    return row


def test_lte_value_becomes_an_inclusive_max():
    """``lteValue`` maps straight onto ``max_value``."""
    schema = _svc().to_form_schema(
        _validated_row(
            "FIELD_MONEY",
            [
                {"validation_type": "lteValue", "validation_comparison_value": "5000"},
            ],
        )
    )

    field = next(schema.iter_all_fields())
    assert field.constraints is not None
    assert field.constraints.max_value == 5000


def test_lt_value_on_an_integer_becomes_max_minus_one():
    """Over the integers, "< 10" and "<= 9" are the same bound."""
    schema = _svc().to_form_schema(
        _validated_row(
            "FIELD_INTEGER",
            [
                {"validation_type": "responseRequired"},
                {"validation_type": "ltValue", "validation_comparison_value": "10"},
            ],
        )
    )

    field = next(schema.iter_all_fields())
    assert field.required is True
    assert field.constraints is not None
    assert field.constraints.max_value == 9


def test_exclusive_bound_on_a_float_is_reported_not_widened():
    """An inexpressible bound must be flagged, never silently relaxed."""
    svc = _svc()
    _, report = svc.import_with_report(
        _validated_row(
            "FIELD_FLOAT2",
            [
                {"validation_type": "ltValue", "validation_comparison_value": "10"},
            ],
        )
    )

    (entry,) = report.fields
    assert entry.status == "requiere_intervencion"
    assert "ltValue" in entry.note


def test_unmapped_validation_is_not_reported_as_clean():
    """The diff report must not claim fidelity it did not achieve."""
    svc = _svc()
    _, report = svc.import_with_report(
        _validated_row(
            "FIELD_TEXT",
            [
                {"validation_type": "someFutureRule", "validation_comparison_value": "x"},
            ],
        )
    )

    (entry,) = report.fields
    assert entry.status == "requiere_intervencion"
    assert "someFutureRule" in entry.note


def test_tightest_bound_wins():
    """Several bounds on one field collapse to the most restrictive."""
    schema = _svc().to_form_schema(
        _validated_row(
            "FIELD_INTEGER",
            [
                {"validation_type": "lteValue", "validation_comparison_value": "50"},
                {"validation_type": "ltValue", "validation_comparison_value": "10"},
            ],
        )
    )

    assert next(schema.iter_all_fields()).constraints.max_value == 9


# ---------------------------------------------------------------------------
# Columns repeated across blocks
# ---------------------------------------------------------------------------


def test_column_repeated_across_blocks_does_not_abort_the_import():
    """A column in two blocks must not kill the whole form.

    Regression for ``db-form-10-69``, where columns 8984/8985/8986 are help
    notes repeated as a header in blocks 27 and 28. FormSchema rejects
    duplicate field_ids, so the import died with a ValidationError that the
    API surfaced as an opaque HTTP 500.
    """
    row = _gated_row()
    # Repeat the driver question in the second block.
    row["question_blocks"][1]["questions"].append(dict(row["question_blocks"][0]["questions"][0]))

    schema, report = _svc().import_with_report(row)

    field_ids = [f.field_id for f in schema.iter_all_fields()]
    assert field_ids == ["field_9050", "field_9100"]
    assert len(field_ids) == len(set(field_ids))

    dropped = [e for e in report.fields if "repeated in block" in e.note]
    assert len(dropped) == 1
    assert dropped[0].column_name == "9050"
    assert dropped[0].status == "requiere_intervencion"


def test_first_occurrence_of_a_repeated_column_is_the_one_kept():
    """The earlier block owns the column; the later one loses it."""
    row = _gated_row()
    row["question_blocks"][1]["questions"].insert(0, dict(row["question_blocks"][0]["questions"][0]))

    schema = _svc().to_form_schema(row)

    first, second = schema.sections
    assert [f.field_id for f in first.iter_fields()] == ["field_9050"]
    assert [f.field_id for f in second.iter_fields()] == ["field_9100"]


def test_alternative_logic_groups_gate_on_or_not_and():
    """Groups are alternatives; ANDing them yields a rule that never fires.

    Every multi-group rule on ``db-form-10-69`` tests one single-select
    column against a different value per group. Under ``logic="and"``
    (``all(results)``) such a rule is unsatisfiable, so the element stays
    hidden no matter what the user answers.
    """
    row = _gated_row()
    row["question_blocks"][1]["block_logic_groups"].append(
        {
            "logic_group_id": 3211,
            "conditions": [
                {
                    "condition_id": 3415,
                    "condition_logic": "EQUALS",
                    "condition_option_id": 4782,
                    "condition_comparison_value": "Brand Ambassador",
                    "condition_question_reference_id": 566,
                }
            ],
        }
    )
    row["metadata"][0]["options"].append(
        {"option_id": "4782", "option_value": "Brand Ambassador", "column_name": 9050, "is_active": True}
    )

    rule = _svc().to_form_schema(row).sections[1].depends_on

    assert rule.logic == "or"
    assert {c.value for c in rule.conditions} == {"4782", "4784"}


@pytest.mark.asyncio
async def test_alternative_groups_actually_fire_in_the_evaluator():
    """End-to-end: a multi-group rule must fire for ANY of its alternatives.

    Exercised on a FIELD rule because ``RuleEvaluator`` only walks
    ``FormField.depends_on`` — it does not read ``FormSection.depends_on``
    (see the note in the audit). This is the enforced path, and under the
    old AND gate it could never fire.
    """
    from parrot_formdesigner.services.rule_evaluator import RuleEvaluator

    row = _gated_row()
    # Move the rule from the block onto the question itself.
    row["question_blocks"][1]["questions"][0]["question_logic_groups"] = [
        row["question_blocks"][1]["block_logic_groups"][0],
        {
            "logic_group_id": 3211,
            "conditions": [
                {
                    "condition_id": 3415,
                    "condition_logic": "EQUALS",
                    "condition_option_id": 4782,
                    "condition_comparison_value": "Brand Ambassador",
                    "condition_question_reference_id": 566,
                }
            ],
        },
    ]
    row["question_blocks"][1]["block_logic_groups"] = []
    row["metadata"][0]["options"].append(
        {"option_id": "4782", "option_value": "Brand Ambassador", "column_name": 9050, "is_active": True}
    )

    schema = _svc().to_form_schema(row)
    assert schema.sections[1].fields[0].depends_on.logic == "or"

    evaluator = RuleEvaluator()
    unanswered = await evaluator.resolve(schema, {})
    lunch = await evaluator.resolve(schema, {"field_9050": "4784"})
    ambassador = await evaluator.resolve(schema, {"field_9050": "4782"})

    assert unanswered.visible["field_9100"] is False
    # Either alternative alone must reveal the field.
    assert lunch.visible["field_9100"] is True
    assert ambassador.visible["field_9100"] is True


def test_multi_field_groups_keep_conjunction():
    """Groups naming DIFFERENT fields are prerequisites, and stay AND.

    Three rules in the 91-form corpus have this shape (e.g. formid 102
    orgid 74). Flattening them to OR would widen what the form reveals.
    """
    row = _gated_row()
    row["question_blocks"][1]["questions"].append(
        {
            "question_id": 800,
            "question_column_name": "9200",
            "question_description": "Region",
            "question_logic_groups": [],
            "validations": [],
        }
    )
    row["metadata"].append(
        {
            "column_id": 3,
            "column_name": "9200",
            "data_type": "FIELD_TEXT",
            "description": "Region",
            "options": [],
        }
    )
    row["question_blocks"][1]["block_logic_groups"].append(
        {
            "logic_group_id": 3212,
            "conditions": [
                {
                    "condition_id": 3416,
                    "condition_logic": "EQUALS",
                    "condition_option_id": None,
                    "condition_comparison_value": "West",
                    "condition_question_reference_id": 800,
                }
            ],
        }
    )

    rule = _svc().to_form_schema(row).sections[1].depends_on

    assert rule.logic == "and"
    assert {c.field_id for c in rule.conditions} == {"field_9050", "field_9200"}


def test_fractional_exclusive_bound_uses_a_ceiling():
    """ "< 10.5" on an integer must allow 10, not cap at 9.5."""
    schema = _svc().to_form_schema(
        _validated_row(
            "FIELD_INTEGER",
            [
                {"validation_type": "ltValue", "validation_comparison_value": "10.5"},
            ],
        )
    )

    assert next(schema.iter_all_fields()).constraints.max_value == 10


def test_negative_fractional_exclusive_bound():
    """ "< -3.5" on an integer must cap at -4."""
    schema = _svc().to_form_schema(
        _validated_row(
            "FIELD_INTEGER",
            [
                {"validation_type": "ltValue", "validation_comparison_value": "-3.5"},
            ],
        )
    )

    assert next(schema.iter_all_fields()).constraints.max_value == -4


def test_rule_pointing_at_an_unbuilt_field_does_not_abort_the_import():
    """An unmapped data_type must cost one question, not the whole form.

    ``question_id_index`` resolves through active metadata, which includes
    columns no field was built for. ``resolve_rule_references`` raises on a
    dangling reference, so without pruning the import dies outright.
    """
    row = _gated_row()
    # Driver becomes a type the mapping table does not know.
    row["metadata"][0]["data_type"] = "FIELD_SOMETHING_NEW"

    schema = _svc().to_form_schema(row)

    assert [f.field_id for f in schema.iter_all_fields()] == ["field_9100"]
    # The gated section survives, unconditional, rather than the import dying.
    assert schema.sections[0].section_id == "section_168"
    assert schema.sections[0].depends_on is None


# ---------------------------------------------------------------------------
# Store-group gating (FEAT-440 TASK-2315, spec §3 Module 4)
# ---------------------------------------------------------------------------


def test_store_groups_produce_one_logic_group_per_group():
    """Each store group is its own alternative, sharing the existing answer condition.

    Mirrors the real gating shape (spec §1): a block gated on BOTH a store
    group and an answer needs AND-of-ORs, which only ``groups`` can express.
    """
    row = _gated_row()
    row["question_blocks"][1]["store_groups"] = ["Ring of Fire", "Epson Test Store"]

    rule = _svc().to_form_schema(row).sections[1].depends_on

    assert rule.conditions == []
    assert rule.groups is not None
    assert len(rule.groups) == 2

    for group, expected_store in zip(rule.groups, ["Ring of Fire", "Epson Test Store"]):
        assert len(group.conditions) == 2
        store_cond, shared_cond = group.conditions
        assert store_cond.source == "visit_context"
        assert store_cond.key == "store_groups"
        assert store_cond.operator == "contains"
        assert store_cond.value == expected_store
        # The shared visit-type condition — same shape as the flat-rule case.
        assert shared_cond.field_id == "field_9050"
        assert shared_cond.operator == "eq"
        assert shared_cond.value == "4784"  # FEAT-325 re-indexed to option_id


def test_store_group_conditions_carry_independent_instances():
    """The shared condition must not be the SAME object across groups.

    Resolution (FEAT-393) mutates field_uid in place; aliasing the same
    FieldCondition instance across every group's list would still behave
    correctly today (idempotent resolution), but is a latent trap for any
    future per-group mutation. Guard the invariant directly.
    """
    row = _gated_row()
    row["question_blocks"][1]["store_groups"] = ["Ring of Fire", "Epson Test Store"]

    rule = _svc().to_form_schema(row).sections[1].depends_on
    shared_a = rule.groups[0].conditions[1]
    shared_b = rule.groups[1].conditions[1]
    assert shared_a is not shared_b
    assert shared_a.field_uid == shared_b.field_uid  # same resolved target
    # AC6: a context condition carries no field reference and is never resolved.
    assert rule.groups[0].conditions[0].field_uid is None


def test_store_group_alone_with_no_shared_condition():
    """A block gated on store group alone still produces valid alternatives."""
    row = _gated_row()
    row["question_blocks"][1]["block_logic_groups"] = []
    row["question_blocks"][1]["store_groups"] = ["Ring of Fire"]

    rule = _svc().to_form_schema(row).sections[1].depends_on

    assert rule.groups is not None
    (group,) = rule.groups
    (condition,) = group.conditions
    assert condition.source == "visit_context"
    assert condition.value == "Ring of Fire"


def test_store_group_dangling_shared_condition_drops_only_that_group():
    """A group whose shared condition points at an unbuilt field is dropped
    as a whole alternative, not silently treated as unconditional (FEAT-440
    extension of the FEAT-393 pruning contract to ``groups``)."""
    row = _gated_row()
    row["question_blocks"][1]["store_groups"] = ["Ring of Fire"]
    # Driver becomes a type the mapping table does not know, so field_9050
    # is never built and the shared condition inside the store-group's
    # LogicGroup dangles.
    row["metadata"][0]["data_type"] = "FIELD_SOMETHING_NEW"

    schema = _svc().to_form_schema(row)

    # The store-group condition alone survives pruning inside the group —
    # only the dangling shared condition is stripped, not the whole group.
    rule = schema.sections[0].depends_on
    assert rule.groups is not None
    (group,) = rule.groups
    (condition,) = group.conditions
    assert condition.source == "visit_context"


@pytest.mark.asyncio
async def test_store_group_alternatives_evaluate_correctly():
    """End-to-end: the imported rule fires only for a matching store AND answer.

    Exercised on a FIELD rule (RuleEvaluator only reads FormField.depends_on,
    not FormSection.depends_on directly — see the multi-group precedent above)
    by moving the same store-group + visit-type gate onto the question.
    """
    from parrot_formdesigner.services.rule_evaluator import RuleEvaluator

    row = _gated_row()
    row["question_blocks"][1]["questions"][0]["store_groups"] = [
        "Ring of Fire",
        "Epson Test Store",
    ]
    row["question_blocks"][1]["questions"][0]["question_logic_groups"] = row["question_blocks"][1]["block_logic_groups"]
    row["question_blocks"][1]["block_logic_groups"] = []

    schema = _svc().to_form_schema(row)
    rule = schema.sections[1].fields[0].depends_on
    assert rule.groups is not None and len(rule.groups) == 2

    evaluator = RuleEvaluator()

    # Right store, right answer -> visible.
    hit = await evaluator.resolve(
        schema,
        {"field_9050": "4784"},
        visit_context={"store_groups": ["Ring of Fire"]},
    )
    assert hit.visible["field_9100"] is True

    # Right store, wrong answer -> hidden (the shared condition still gates).
    wrong_answer = await evaluator.resolve(
        schema,
        {"field_9050": "4782"},
        visit_context={"store_groups": ["Ring of Fire"]},
    )
    assert wrong_answer.visible["field_9100"] is False

    # Right answer, wrong store -> hidden.
    wrong_store = await evaluator.resolve(
        schema,
        {"field_9050": "4784"},
        visit_context={"store_groups": ["Best Buy"]},
    )
    assert wrong_store.visible["field_9100"] is False

    # Right answer, no context at all -> hidden (fail closed — spec §3 Module 5).
    no_context = await evaluator.resolve(schema, {"field_9050": "4784"})
    assert no_context.visible["field_9100"] is False

    # The other alternative group also fires on its own store.
    other_group = await evaluator.resolve(
        schema,
        {"field_9050": "4784"},
        visit_context={"store_groups": ["Epson Test Store"]},
    )
    assert other_group.visible["field_9100"] is True


def test_store_group_collapses_same_field_alternatives_into_in():
    """Regression: a same-field answer alternative must not be ANDed with itself.

    Code-review finding (post-TASK-2315): when the source expresses "visit
    type == Brand Ambassador OR visit type == Assisted Sales" as TWO
    logic_groups on the SAME field — the spec's own majority real shape
    (§1: 23 of 26 dual-axis elements need this AND-of-ORs) — naively
    copying both EQ conditions into every store-group LogicGroup ANDs them
    together. A LogicGroup only ANDs; unlike the flat path, it has no
    top-level "or" to fall back on, so `field_9050 == "4784" AND field_9050
    == "4782"` is unsatisfiable for a single-valued field — the rule could
    never fire for ANY store or answer. The fix collapses same-field EQ
    alternates into one IN condition (spec §2's own worked example shape)
    before folding them into each store-group alternative.
    """
    row = _gated_row()
    # A second logic_group on the SAME field (566 / field_9050) — an
    # alternative answer, not an independent prerequisite.
    row["question_blocks"][1]["block_logic_groups"].append({
        "logic_group_id": 3211,
        "conditions": [{
            "condition_id": 3415,
            "condition_logic": "EQUALS",
            "condition_option_id": 4782,
            "condition_comparison_value": "Brand Ambassador",
            "condition_question_reference_id": 566,
        }],
    })
    row["metadata"][0]["options"].append(
        {"option_id": "4782", "option_value": "Brand Ambassador",
         "column_name": 9050, "is_active": True}
    )
    row["question_blocks"][1]["store_groups"] = ["Ring of Fire", "Epson Test Store"]

    rule = _svc().to_form_schema(row).sections[1].depends_on

    assert rule.groups is not None and len(rule.groups) == 2
    for group in rule.groups:
        assert len(group.conditions) == 2
        _store_cond, answer_cond = group.conditions
        assert answer_cond.field_id == "field_9050"
        assert answer_cond.operator == "in"
        assert set(answer_cond.value) == {"4784", "4782"}


@pytest.mark.asyncio
async def test_store_group_alternatives_evaluate_for_either_answer_value():
    """End-to-end companion to the collapse regression above.

    EITHER alternative answer value must reveal the field at a matching
    store — this is exactly what "AND ANDed EQs" made impossible before
    the fix.
    """
    from parrot_formdesigner.services.rule_evaluator import _eval_rule

    row = _gated_row()
    row["question_blocks"][1]["block_logic_groups"].append({
        "logic_group_id": 3211,
        "conditions": [{
            "condition_id": 3415,
            "condition_logic": "EQUALS",
            "condition_option_id": 4782,
            "condition_comparison_value": "Brand Ambassador",
            "condition_question_reference_id": 566,
        }],
    })
    row["metadata"][0]["options"].append(
        {"option_id": "4782", "option_value": "Brand Ambassador",
         "column_name": 9050, "is_active": True}
    )
    row["question_blocks"][1]["store_groups"] = ["Ring of Fire"]

    schema = _svc().to_form_schema(row)

    # Exercised on the SECTION rule directly — RuleEvaluator.resolve() only
    # walks FormField.depends_on, not FormSection.depends_on (see the
    # multi-group precedent test above), so _eval_rule is called directly
    # here rather than moving the gate onto a field.
    rule = schema.sections[1].depends_on
    for answer in ("4784", "4782"):
        fired = _eval_rule(
            rule, {"field_9050": answer}, schema,
            visit_context={"store_groups": ["Ring of Fire"]},
        )
        assert fired is True, f"answer={answer!r} should fire at a matching store"

    # Wrong store, either answer -> does not fire.
    for answer in ("4784", "4782"):
        fired = _eval_rule(
            rule, {"field_9050": answer}, schema,
            visit_context={"store_groups": ["Best Buy"]},
        )
        assert fired is False, f"answer={answer!r} must not fire at a non-matching store"
