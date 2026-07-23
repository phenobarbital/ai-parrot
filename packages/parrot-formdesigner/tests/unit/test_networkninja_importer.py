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


# ---------------------------------------------------------------------------
# FEAT-325 — form_metadata.options as the primary select-option source
# ---------------------------------------------------------------------------


def test_metadata_options_populate_select():
    """FIELD_SELECT with form_metadata.options yields FieldOption(value=option_id, label=option_value)."""
    row = {
        "formid": 1, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [{
                "question_id": 1, "question_column_name": "10211",
                "question_description": "Role", "validations": [],
                "question_logic_groups": [],
            }],
        }],
        "metadata": [{
            "column_id": 1, "column_name": "10211", "data_type": "FIELD_SELECT",
            "description": "Role", "options": [
                {"is_active": True, "option_id": "6091", "column_name": 10211,
                 "option_value": "Field Merchandiser"},
            ],
        }],
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
        {"is_active": True, "option_id": str(i), "column_name": 10212, "option_value": str(i)}
        for i in range(1, 11)
    ]
    row = {
        "formid": 2, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [{
                "question_id": 1, "question_column_name": "10212",
                "question_description": "Quality", "validations": [],
                "question_logic_groups": [],
            }],
        }],
        "metadata": [{
            "column_id": 1, "column_name": "10212", "data_type": "FIELD_SELECT",
            "description": "Quality", "options": options,
        }],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert field.options is not None
    assert len(field.options) == 10


def test_inactive_option_marked_disabled():
    """is_active=false option imported with disabled=True, still present."""
    row = {
        "formid": 3, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [{
                "question_id": 1, "question_column_name": "10213",
                "question_description": "Role", "validations": [],
                "question_logic_groups": [],
            }],
        }],
        "metadata": [{
            "column_id": 1, "column_name": "10213", "data_type": "FIELD_SELECT",
            "description": "Role", "options": [
                {"is_active": True, "option_id": "1", "column_name": 10213, "option_value": "Active"},
                {"is_active": False, "option_id": "2", "column_name": 10213, "option_value": "Retired"},
            ],
        }],
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
        "formid": 4, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [{
                "question_id": 1, "question_column_name": "10214",
                "question_description": "Role", "validations": [],
                "question_logic_groups": [],
                "options": [{"value": "inline1", "label": "Inline One"}],
            }],
        }],
        "metadata": [{
            "column_id": 1, "column_name": "10214", "data_type": "FIELD_SELECT",
            "description": "Role", "options": [
                {"is_active": True, "option_id": "6091", "column_name": 10214,
                 "option_value": "Field Merchandiser"},
            ],
        }],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert {o.value for o in field.options} == {"6091"}


def test_inline_fallback_when_metadata_empty():
    """Empty metadata options -> inline options used (no regression)."""
    row = {
        "formid": 5, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [{
                "question_id": 1, "question_column_name": "10215",
                "question_description": "Role", "validations": [],
                "question_logic_groups": [],
                "options": [{"value": "inline1", "label": "Inline One"}],
            }],
        }],
        "metadata": [{
            "column_id": 1, "column_name": "10215", "data_type": "FIELD_SELECT",
            "description": "Role", "options": [],
        }],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert {o.value for o in field.options} == {"inline1"}
    assert next(o for o in field.options if o.value == "inline1").label == "Inline One"


def test_logic_group_fallback_when_no_metadata():
    """No metadata catalog -> logic-group text used as value & label."""
    row = {
        "formid": 6, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [
                {
                    "question_id": 1, "question_column_name": "10216",
                    "question_description": "Role", "validations": [],
                    "question_logic_groups": [],
                },
                {
                    "question_id": 2, "question_column_name": "99",
                    "question_description": "Dep", "validations": [],
                    "question_logic_groups": [{
                        "conditions": [{
                            "condition_logic": "EQUALS",
                            "condition_question_reference_id": 1,
                            "condition_comparison_value": "Field Merchandiser",
                        }],
                    }],
                },
            ],
        }],
        "metadata": [
            {"column_id": 1, "column_name": "10216", "data_type": "FIELD_SELECT",
             "description": "Role", "options": []},
            {"column_id": 2, "column_name": "99", "data_type": "FIELD_TEXT",
             "description": "Dep", "options": []},
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
        "formid": 7, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [
                {
                    "question_id": 1, "question_column_name": "10217",
                    "question_description": "Role", "validations": [],
                    "question_logic_groups": [],
                },
                {
                    "question_id": 2, "question_column_name": "99",
                    "question_description": "Dep", "validations": [],
                    "question_logic_groups": [{
                        "conditions": [{
                            "condition_logic": "EQUALS",
                            "condition_question_reference_id": 1,
                            "condition_comparison_value": "Field Merchandiser",
                        }],
                    }],
                },
            ],
        }],
        "metadata": [
            {"column_id": 1, "column_name": "10217", "data_type": "FIELD_SELECT",
             "description": "Role", "options": [
                 {"is_active": True, "option_id": "6091", "column_name": 10217,
                  "option_value": "Field Merchandiser"},
             ]},
            {"column_id": 2, "column_name": "99", "data_type": "FIELD_TEXT",
             "description": "Dep", "options": []},
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
        "formid": 8, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [
                {
                    "question_id": 1, "question_column_name": "10218",
                    "question_description": "Role", "validations": [],
                    "question_logic_groups": [],
                },
                {
                    "question_id": 2, "question_column_name": "99",
                    "question_description": "Dep", "validations": [],
                    "question_logic_groups": [{
                        "conditions": [{
                            "condition_logic": "EQUALS",
                            "condition_question_reference_id": 1,
                            "condition_comparison_value": "Unknown Value",
                        }],
                    }],
                },
            ],
        }],
        "metadata": [
            {"column_id": 1, "column_name": "10218", "data_type": "FIELD_SELECT",
             "description": "Role", "options": [
                 {"is_active": True, "option_id": "6091", "column_name": 10218,
                  "option_value": "Field Merchandiser"},
             ]},
            {"column_id": 2, "column_name": "99", "data_type": "FIELD_TEXT",
             "description": "Dep", "options": []},
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
        "formid": 9, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [
                {
                    "question_id": 1, "question_column_name": "meta_col",
                    "question_description": "Meta", "validations": [],
                    "question_logic_groups": [],
                },
                {
                    "question_id": 2, "question_column_name": "inline_col",
                    "question_description": "Inline", "validations": [],
                    "question_logic_groups": [],
                    "options": [{"value": "i1", "label": "Inline"}],
                },
                {
                    "question_id": 3, "question_column_name": "logic_col",
                    "question_description": "Logic", "validations": [],
                    "question_logic_groups": [],
                },
                {
                    "question_id": 4, "question_column_name": "none_col",
                    "question_description": "None", "validations": [],
                    "question_logic_groups": [],
                },
                {
                    "question_id": 5, "question_column_name": "dep_col",
                    "question_description": "Dep", "validations": [],
                    "question_logic_groups": [{
                        "conditions": [{
                            "condition_logic": "EQUALS",
                            "condition_question_reference_id": 3,
                            "condition_comparison_value": "Logic Value",
                        }],
                    }],
                },
            ],
        }],
        "metadata": [
            {"column_id": 1, "column_name": "meta_col", "data_type": "FIELD_SELECT",
             "description": "Meta", "options": [
                 {"is_active": True, "option_id": "1", "column_name": "meta_col",
                  "option_value": "Meta Val"},
             ]},
            {"column_id": 2, "column_name": "inline_col", "data_type": "FIELD_SELECT",
             "description": "Inline", "options": []},
            {"column_id": 3, "column_name": "logic_col", "data_type": "FIELD_SELECT",
             "description": "Logic", "options": []},
            {"column_id": 4, "column_name": "none_col", "data_type": "FIELD_SELECT",
             "description": "None", "options": []},
            {"column_id": 5, "column_name": "dep_col", "data_type": "FIELD_TEXT",
             "description": "Dep", "options": []},
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
        "formid": 10, "orgid": 1, "form_name": "F", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [{
                "question_id": 1, "question_column_name": "10219",
                "question_description": "Role", "validations": [],
                "question_logic_groups": [],
            }],
        }],
        "metadata": [{
            "column_id": 1, "column_name": "10219", "data_type": "FIELD_SELECT",
            "description": "Role", "options": [
                {"is_active": True, "option_id": 6091, "column_name": 10219,
                 "option_value": "Field Merchandiser"},
            ],
        }],
    }
    svc = _svc()
    schema = svc.to_form_schema(row)
    field = next(schema.iter_all_fields())
    assert field.options[0].value == "6091"
    assert isinstance(field.options[0].value, str)
