"""Integration tests for FEAT-300 — Form Builder Parity (spec §4, Integration table).

Covers the cross-module flows the unit suites do not exercise:

- ``test_recap_survey_round_trip`` — import a survey-type recap (fixture
  modeled on live formid 71 "Siffron Site Survey") and render it.
- ``test_epson_recap_product_round_trip`` — a synthetic PRODUCT form renders
  without error (production has no product blocks; PRODUCT activates via
  ``product_bindings`` / FEAT-302, never via the importer).
- ``test_question_bank_reuse_in_two_forms`` — one ReusableField referenced
  by two forms yields ``usage_forms == 2``.
- ``test_inflight_response_keeps_version`` — RF-06: a response started on
  v1.1 keeps resolving against the v1.1 snapshot after v1.2 is published.
- ``test_epson_validation_set_auto_mapping`` — RF-01 (representative): every
  live data_type imports without abort; auto-map rate weighted by the live
  production field counts (verified 2026-06-11) is ≥95%.
- ``test_render_performance_200_questions`` — NFR: a 200-question form
  renders via HTML5 in <2s.
"""

import json
import time

from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSection,
    FormType,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer
from parrot_formdesigner.services.form_version import FormVersionService
from parrot_formdesigner.services.question_bank import (
    QuestionBankService,
    ReusableFieldRef,
)
from parrot_formdesigner.services.registry import FormRegistry
from parrot_formdesigner.tools.services.networkninja import (
    NetworkninjaFormService,
)


# ---------------------------------------------------------------------------
# Live production facts (RO replica, verified 2026-06-11) — spec §8
# ---------------------------------------------------------------------------

#: data_type → live row count in networkninja.form_metadata.
LIVE_DATA_TYPE_COUNTS: dict[str, int] = {
    "FIELD_INTEGER": 827,
    "FIELD_YES_NO": 656,
    "FIELD_IMAGE_UPLOAD_MULTIPLE": 609,
    "FIELD_TEXTAREA": 345,
    "FIELD_TEXT": 320,
    "FIELD_DISPLAY_TEXT": 244,
    "FIELD_MULTISELECT": 243,
    "FIELD_SELECT_RADIO": 227,
    "FIELD_DISPLAY_IMAGE": 111,
    "FIELD_SELECT": 111,
    "FIELD_IMAGE_UPLOAD": 109,
    "FIELD_SUBSECTION": 56,
    "FIELD_AGREEMENT_CHECKBOX": 52,
    "FIELD_FLOAT2": 26,
    "FIELD_FORMULA": 22,
    "FIELD_SIGNATURE_CAPTURE": 9,
    "FIELD_DURATION": 8,
    "FIELD_DATE": 6,
    "FIELD_MONEY": 4,
    "FIELD_DATETIME": 2,
    "FIELD_TIME": 2,
    "FIELD_HYPERLINK": 1,
    "FIELD_PHONENUMBER": 1,
    "FIELD_TOTAL": 1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _service() -> NetworkninjaFormService:
    return NetworkninjaFormService(dsn="postgres://test")


def _row_with_all_live_types() -> dict:
    """One question per live data_type, single simple block."""
    questions = []
    metadata = []
    for i, data_type in enumerate(LIVE_DATA_TYPE_COUNTS, start=1):
        col = str(1000 + i)
        questions.append(
            {
                "question_id": i,
                "question_column_name": col,
                "question_description": f"Q {data_type}",
                "question_logic_groups": [],
                "validations": [],
            }
        )
        metadata.append(
            {
                "column_id": i,
                "column_name": col,
                "data_type": data_type,
                "description": f"Q {data_type}",
                "options": (
                    [{"is_active": True, "option_id": 1, "column_name": 1000 + i,
                      "option_value": "A"}]
                    if data_type
                    in ("FIELD_SELECT", "FIELD_SELECT_RADIO", "FIELD_MULTISELECT")
                    else []
                ),
            }
        )
    return {
        "formid": 9000,
        "orgid": 1,
        "form_name": "All Live Types",
        "description": None,
        "question_blocks": [
            {
                "block_id": 1,
                "block_type": "simple",
                "block_logic_groups": [],
                "questions": questions,
            }
        ],
        "metadata": metadata,
    }


def _survey_row() -> dict:
    """Survey recap modeled on live formid 71 (Siffron Site Survey, FLEXROC)."""
    return {
        "formid": 71,
        "orgid": 1,
        "form_name": "Siffron Site Survey",
        "description": None,
        "question_blocks": [
            {
                "block_id": 210,
                "block_type": "survey",
                "block_logic_groups": [],
                "questions": [
                    {
                        "question_id": 3328,
                        "question_column_name": "11095",
                        "question_description": (
                            "Enter the aisle or section number you are counting:"
                        ),
                        "question_logic_groups": [],
                        "validations": [
                            {
                                "validation_id": 2543,
                                "validation_type": "responseRequired",
                                "validation_logic": None,
                                "validation_comparison_value": None,
                                "validation_question_reference_id": None,
                            }
                        ],
                    }
                ],
            }
        ],
        "metadata": [
            {
                "column_id": 1,
                "column_name": "11095",
                "data_type": "FIELD_TEXT",
                "description": "Aisle number",
                "options": [],
            }
        ],
    }


def _form_with_n_questions(n: int, form_id: str = "perf-form") -> FormSchema:
    fields = [
        FormField(field_id=f"q{i}", field_type=FieldType.TEXT, label=f"Question {i}")
        for i in range(n)
    ]
    return FormSchema(
        form_id=form_id,
        title="Performance Form",
        sections=[FormSection(section_id="s1", fields=fields)],
        tenant="t1",
    )


# ---------------------------------------------------------------------------
# Round trips (import → schema → render)
# ---------------------------------------------------------------------------


async def test_recap_survey_round_trip():
    """Survey recap imports as FormType.SURVEY and renders without error."""
    schema, report = _service().import_with_report(_survey_row())

    assert schema.form_type == FormType.SURVEY
    assert schema.published_version is None  # imported forms stay draft
    assert report.fields, "report must cover every metadata field"

    rendered = await HTML5Renderer().render(schema)
    assert rendered.content


async def test_epson_recap_product_round_trip():
    """A PRODUCT form (synthetic — see module docstring) renders without error."""
    form = FormSchema(
        form_id="product-form",
        title="Product Recap",
        form_type=FormType.PRODUCT,
        product_bindings=["sku-100", "sku-200"],
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(
                        field_id="q1", field_type=FieldType.TEXT, label="Units sold"
                    )
                ],
            )
        ],
        tenant="epson",
    )

    assert form.form_type == FormType.PRODUCT
    assert form.product_bindings == ["sku-100", "sku-200"]

    rendered = await HTML5Renderer().render(form)
    assert rendered.content


# ---------------------------------------------------------------------------
# QuestionBank reuse across forms
# ---------------------------------------------------------------------------


async def test_question_bank_reuse_in_two_forms():
    """One ReusableField referenced in two FormSchemas → usage_forms == 2."""
    bank = QuestionBankService(None, tenant="t1")
    base = FormField(field_id="store-id", field_type=FieldType.TEXT, label="Store ID")
    entry = await bank.create_field(base)

    forms = []
    for n in (1, 2):
        resolved = await bank.resolve_ref(ReusableFieldRef(bank_field_id=entry.field_id))
        forms.append(
            FormSchema(
                form_id=f"form-{n}",
                title=f"Form {n}",
                sections=[FormSection(section_id="s1", fields=[resolved])],
                tenant="t1",
            )
        )
        await bank.increment_usage(entry.field_id, forms=1)

    assert len(forms) == 2
    refreshed = await bank.get_field(entry.field_id)
    assert refreshed.usage_forms == 2


# ---------------------------------------------------------------------------
# RF-06 — in-flight responses keep their version
# ---------------------------------------------------------------------------


async def test_inflight_response_keeps_version():
    """RF-06: a response started against v1.1 resolves against the v1.1
    snapshot even after v1.2 is published mid-capture."""
    registry = FormRegistry()
    svc = FormVersionService(registry, storage=None)

    original = FormSchema(
        form_id="recap",
        title="Recap v1",
        sections=[
            FormSection(
                section_id="s1",
                fields=[
                    FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")
                ],
            )
        ],
        tenant="t1",
    )
    await registry.register(original, tenant="t1")
    inflight_version = await svc.publish("recap", tenant="t1")  # "1.1"

    # An in-flight response pins this version.
    # Meanwhile the form is edited (starting from the CURRENT live form,
    # whose version was bumped by publish) and re-published (v1.2):
    live = await registry.get("recap", tenant="t1")
    edited = live.model_copy(deep=True)
    edited.title = "Recap v2 — restructured"
    await registry.register(edited, tenant="t1", overwrite=True)
    newer_version = await svc.publish("recap", tenant="t1")  # "1.2"
    assert newer_version != inflight_version

    # The in-flight response still resolves against its pinned snapshot:
    pinned = await svc.get_published("recap", version=inflight_version, tenant="t1")
    assert pinned is not None
    assert str(pinned.title) == "Recap v1"
    assert pinned.published_version == inflight_version


# ---------------------------------------------------------------------------
# RF-01 (representative) — auto-mapping rate over the live data_type universe
# ---------------------------------------------------------------------------


def test_epson_validation_set_auto_mapping():
    """RF-01 (representative): all 24 live data_types import without abort and
    the auto-map rate weighted by live production counts is ≥95%.

    NOTE: the contractual RF-01 check runs over the agreed Epson production
    form set (list pending — spec §5); this test guards the mapping table
    against regressions using the verified live distribution instead.
    """
    schema, report = _service().import_with_report(_row_with_all_live_types())

    # 100% of fields covered by the report, import never aborts
    assert len(report.fields) == len(LIVE_DATA_TYPE_COUNTS)
    by_type = {e.source_data_type: e for e in report.fields}

    # No unknown-type entries: every live data_type is in the mapping table
    for data_type in LIVE_DATA_TYPE_COUNTS:
        assert by_type[data_type].mapped_field_type is not None, (
            f"{data_type} fell out of _FIELD_TYPE_MAP"
        )

    # Auto-map rate weighted by live counts (mapeado/aproximado = auto)
    total = sum(LIVE_DATA_TYPE_COUNTS.values())
    auto = sum(
        count
        for data_type, count in LIVE_DATA_TYPE_COUNTS.items()
        if by_type[data_type].status in ("mapeado", "aproximado")
    )
    rate = auto / total
    assert rate >= 0.95, f"weighted auto-map rate {rate:.2%} < 95%"


# ---------------------------------------------------------------------------
# FEAT-325 — form_metadata.options as the primary select-option source
# ---------------------------------------------------------------------------


def test_feat300_all_live_types_options():
    """Integration fixture uses ``option_value`` (not ``option_label``);
    SELECT/RADIO/MULTISELECT fields carry populated options."""
    row = _row_with_all_live_types()
    schema, _ = _service().import_with_report(row)

    fields_by_id = {f.field_id: f for f in schema.iter_all_fields()}
    metadata_by_col = {m["column_name"]: m for m in row["metadata"]}

    select_family = ("FIELD_SELECT", "FIELD_SELECT_RADIO", "FIELD_MULTISELECT")
    checked = 0
    for col, meta in metadata_by_col.items():
        if meta["data_type"] not in select_family:
            continue
        field = fields_by_id[f"field_{col}"]
        assert field.options, (
            f"{meta['data_type']} field '{col}' expected populated options"
        )
        opt = field.options[0]
        assert opt.value == "1"
        assert opt.label == "A"
        checked += 1

    assert checked == 3, "expected FIELD_SELECT, FIELD_SELECT_RADIO, FIELD_MULTISELECT to be checked"


async def test_end_to_end_metadata_form():
    """A row modeling a live metadata-backed select imports with populated,
    id-keyed options and consistent conditions."""
    row = {
        "formid": 5000, "orgid": 1, "form_name": "Metadata E2E", "description": None,
        "question_blocks": [{
            "block_id": 1, "block_type": "simple", "block_logic_groups": [],
            "questions": [
                {
                    "question_id": 1, "question_column_name": "20001",
                    "question_description": "Role", "validations": [],
                    "question_logic_groups": [],
                },
                {
                    "question_id": 2, "question_column_name": "20002",
                    "question_description": "Follow-up", "validations": [],
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
            {"column_id": 1, "column_name": "20001", "data_type": "FIELD_SELECT",
             "description": "Role", "options": [
                 {"is_active": True, "option_id": "6091", "column_name": 20001,
                  "option_value": "Field Merchandiser"},
                 {"is_active": False, "option_id": "6092", "column_name": 20001,
                  "option_value": "Retired Role"},
             ]},
            {"column_id": 2, "column_name": "20002", "data_type": "FIELD_TEXT",
             "description": "Follow-up", "options": []},
        ],
    }
    schema, report = _service().import_with_report(row)

    role_field = next(f for f in schema.iter_all_fields() if f.field_id == "field_20001")
    followup_field = next(f for f in schema.iter_all_fields() if f.field_id == "field_20002")

    assert {o.value for o in role_field.options} == {"6091", "6092"}
    assert next(o for o in role_field.options if o.value == "6092").disabled is True

    assert followup_field.depends_on is not None
    assert followup_field.depends_on.conditions[0].value == "6091"

    entry = next(e for e in report.fields if e.column_name == "20001")
    assert entry.options_source == "metadata"

    rendered = await HTML5Renderer().render(schema)
    assert rendered.content


# ---------------------------------------------------------------------------
# NFR — render performance
# ---------------------------------------------------------------------------


async def test_render_performance_200_questions():
    """[PROPUESTA — Review v2.1] A ≥200-question form renders in <2s (HTML5)."""
    form = _form_with_n_questions(200)

    start = time.perf_counter()
    rendered = await HTML5Renderer().render(form)
    elapsed = time.perf_counter() - start

    assert rendered.content
    assert elapsed < 2.0, f"render took {elapsed:.2f}s (NFR: <2s)"


# ---------------------------------------------------------------------------
# Defensive: legacy double-encoded survey block still detected
# ---------------------------------------------------------------------------


def test_survey_detection_in_legacy_encoded_row():
    """A double-encoded (legacy) row with a survey block still yields SURVEY."""
    row = _survey_row()
    legacy_blocks = [
        {
            "question_block_id": b["block_id"],
            "question_block_type": b["block_type"],
            "question_block_logic_groups": b["block_logic_groups"],
            "questions": b["questions"],
        }
        for b in row["question_blocks"]
    ]
    row["question_blocks"] = json.dumps(legacy_blocks)

    schema, _ = _service().import_with_report(row)
    assert schema.form_type == FormType.SURVEY
