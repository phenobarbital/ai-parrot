"""Unit tests for A2UIFormRenderer field lowering (FEAT-544, TASK-3072).

Covers the ``FIELD_LOWERING`` table, constraint -> checks lowering, and
honest degradation for FieldTypes with no A2UI v1.0 primitive.
"""

from __future__ import annotations

import pytest

pytest.importorskip("parrot.outputs.a2ui")

from parrot_formdesigner.core.constraints import FieldConstraints
from parrot_formdesigner.core.options import FieldOption
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.a2ui import FIELD_LOWERING, A2UIFormRenderer

from parrot.outputs.a2ui.catalog import validate_envelope
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin
from parrot.outputs.a2ui.models import CreateSurface


def _form_with_field(field: FormField) -> FormSchema:
    return FormSchema(form_id="demo", title="Demo", tenant="acme", sections=[FormSection(section_id="s", fields=[field])])


def _surface(content: dict) -> dict:
    return content["createSurface"]


async def _render_field(field: FormField) -> dict:
    renderer = A2UIFormRenderer()
    result = await renderer.render(_form_with_field(field))
    return _surface(result.content), result


def test_every_fieldtype_has_a_lowering_entry():
    assert set(FIELD_LOWERING) == set(FieldType)


@pytest.mark.parametrize(
    "field_type,variant",
    [
        (FieldType.TEXT, "shortText"),
        (FieldType.TEXT_AREA, "longText"),
        (FieldType.NUMBER, "number"),
        (FieldType.INTEGER, "number"),
        (FieldType.PASSWORD, "obscured"),
        (FieldType.SEARCH, "shortText"),
        (FieldType.MASKED, "shortText"),
        (FieldType.COLOR, "shortText"),
        (FieldType.COLOR_PICKER, "shortText"),
    ],
)
async def test_text_family_maps_to_textfield_variants(field_type, variant):
    field = FormField(field_id="f", field_type=field_type, label="F")
    surface, _ = await _render_field(field)
    component = next(c for c in surface["components"] if c["id"] == "f-f")
    assert component["component"] == "TextField"
    assert component["variant"] == variant


async def test_email_adds_email_check():
    field = FormField(field_id="email", field_type=FieldType.EMAIL, label="Email")
    surface, _ = await _render_field(field)
    component = next(c for c in surface["components"] if c["id"] == "f-email")
    assert component["component"] == "TextField"
    calls = [check["condition"]["call"] for check in component["checks"]]
    assert "email" in calls


async def test_url_and_phone_add_regex_check():
    for field_type in (FieldType.URL, FieldType.PHONE):
        field = FormField(field_id="f", field_type=field_type, label="F")
        surface, _ = await _render_field(field)
        component = next(c for c in surface["components"] if c["id"] == "f-f")
        calls = [check["condition"]["call"] for check in component["checks"]]
        assert "regex" in calls


async def test_boolean_maps_to_checkbox():
    field = FormField(field_id="agree", field_type=FieldType.BOOLEAN, label="Agree")
    surface, _ = await _render_field(field)
    component = next(c for c in surface["components"] if c["id"] == "f-agree")
    assert component["component"] == "CheckBox"
    assert component["value"] == {"path": "/answers/agree"}


async def test_select_and_multiselect_map_to_choicepicker():
    options = [FieldOption(value="a", label="A"), FieldOption(value="b", label="B", disabled=True)]

    select_field = FormField(field_id="sel", field_type=FieldType.SELECT, label="Select", options=options)
    surface, _ = await _render_field(select_field)
    component = next(c for c in surface["components"] if c["id"] == "f-sel")
    assert component["component"] == "ChoicePicker"
    assert component["variant"] == "mutuallyExclusive"
    assert component["options"] == [{"label": "A", "value": "a"}]  # disabled option skipped

    multi_field = FormField(field_id="multi", field_type=FieldType.MULTI_SELECT, label="Multi", options=options)
    surface, _ = await _render_field(multi_field)
    component = next(c for c in surface["components"] if c["id"] == "f-multi")
    assert component["variant"] == "multipleSelection"

    tags_field = FormField(field_id="tags", field_type=FieldType.TAGS, label="Tags")
    surface, _ = await _render_field(tags_field)
    component = next(c for c in surface["components"] if c["id"] == "f-tags")
    assert component["variant"] == "multipleSelection"
    assert component["displayStyle"] == "chips"


async def test_date_time_datetime_flags():
    date_field = FormField(field_id="d", field_type=FieldType.DATE, label="Date")
    surface, _ = await _render_field(date_field)
    component = next(c for c in surface["components"] if c["id"] == "f-d")
    assert component["component"] == "DateTimeInput"
    assert component["enableDate"] is True
    assert component.get("enableTime") is not True

    time_field = FormField(field_id="t", field_type=FieldType.TIME, label="Time")
    surface, _ = await _render_field(time_field)
    component = next(c for c in surface["components"] if c["id"] == "f-t")
    assert component["enableTime"] is True

    dt_field = FormField(field_id="dt", field_type=FieldType.DATETIME, label="DateTime")
    surface, _ = await _render_field(dt_field)
    component = next(c for c in surface["components"] if c["id"] == "f-dt")
    assert component["enableDate"] is True
    assert component["enableTime"] is True


async def test_scale_types_map_to_slider():
    nps_field = FormField(field_id="nps", field_type=FieldType.NPS, label="NPS")
    surface, _ = await _render_field(nps_field)
    component = next(c for c in surface["components"] if c["id"] == "f-nps")
    assert component["component"] == "Slider"
    assert component["min"] == 0
    assert component["max"] == 10

    likert_field = FormField(field_id="likert", field_type=FieldType.LIKERT, label="Likert")
    surface, _ = await _render_field(likert_field)
    component = next(c for c in surface["components"] if c["id"] == "f-likert")
    assert component["max"] == 5

    scaled_field = FormField(
        field_id="ranking",
        field_type=FieldType.RANKING,
        label="Ranking",
        constraints=FieldConstraints(scale_min=1, scale_max=7, scale_step=1),
    )
    surface, _ = await _render_field(scaled_field)
    component = next(c for c in surface["components"] if c["id"] == "f-ranking")
    assert component["min"] == 1
    assert component["max"] == 7
    assert component["steps"] == 1


async def test_hidden_is_datamodel_only():
    field = FormField(field_id="hid", field_type=FieldType.HIDDEN, label="Hidden", default="secret")
    renderer = A2UIFormRenderer()
    result = await renderer.render(_form_with_field(field))
    surface = _surface(result.content)

    assert not any(c["id"] == "f-hid" for c in surface["components"])
    assert surface["dataModel"]["answers"]["hid"] == "secret"
    assert result.metadata["field_paths"]["hid"] == "/answers/hid"


async def test_constraints_lower_to_checks():
    field = FormField(
        field_id="f",
        field_type=FieldType.TEXT,
        label="F",
        required=True,
        constraints=FieldConstraints(min_length=2, max_length=10, pattern=r"^[a-z]+$", pattern_message="lowercase only"),
    )
    surface, _ = await _render_field(field)
    component = next(c for c in surface["components"] if c["id"] == "f-f")
    calls = {check["condition"]["call"]: check for check in component["checks"]}

    assert "required" in calls
    assert calls["required"]["message"] == "F is required."
    assert "length" in calls
    assert calls["length"]["condition"]["args"]["min"] == 2
    assert calls["length"]["condition"]["args"]["max"] == 10
    assert "regex" in calls
    assert calls["regex"]["message"] == "lowercase only"


async def test_numeric_constraints_lower_to_numeric_check():
    field = FormField(
        field_id="n",
        field_type=FieldType.NUMBER,
        label="N",
        constraints=FieldConstraints(min_value=0, max_value=100),
    )
    surface, _ = await _render_field(field)
    component = next(c for c in surface["components"] if c["id"] == "f-n")
    calls = {check["condition"]["call"]: check for check in component["checks"]}
    assert calls["numeric"]["condition"]["args"]["min"] == 0
    assert calls["numeric"]["condition"]["args"]["max"] == 100


@pytest.mark.parametrize(
    "field_type",
    [
        FieldType.FILE,
        FieldType.GROUP,
        FieldType.ARRAY,
        FieldType.SIGNATURE,
        FieldType.CRON,
        FieldType.IMAGE,
        FieldType.REMOTE_RESPONSE,
        FieldType.AVAILABILITY,
        FieldType.LOCATION,
        FieldType.REST,
        FieldType.AUDIO,
        FieldType.FORMULA,
        FieldType.EMOJI,
        FieldType.TREE_SELECT,
        FieldType.SIGNATURE_PAD,
        FieldType.CREDIT_CARD,
        FieldType.IMAGE_DROPZONE,
        FieldType.MULTI_UPLOAD,
        FieldType.AI_CAPTURE,
        FieldType.PLACE,
    ],
)
async def test_unsupported_types_degrade_to_notice_and_warning(field_type):
    field = FormField(field_id="f", field_type=field_type, label="F")
    renderer = A2UIFormRenderer()
    result = await renderer.render(_form_with_field(field))
    surface = _surface(result.content)

    component = next(c for c in surface["components"] if c["id"] == "f-f")
    assert component["component"] == "Text"
    assert component["metadata"]["extensions"]["parrot_role"] == "notice"

    assert len(result.warnings) == 1
    assert result.warnings[0].renderer == "a2ui"
    assert result.warnings[0].field_id == "f"

    assert result.metadata["degraded"] == [
        {"id": "f-f", "field_id": "f", "field_type": field_type.value, "reason": result.warnings[0].reason}
    ]
    assert "f" not in result.metadata["field_paths"]


@pytest.mark.parametrize("field_type", list(FieldType))
async def test_rendering_never_raises_for_any_fieldtype(field_type):
    """Property test (spec §7): no ``FieldType`` may ever raise on render."""
    field = FormField(field_id="f", field_type=field_type, label="F")
    surface, result = await _render_field(field)
    assert result.content_type == "application/a2ui+json"
    assert surface["surfaceId"]


async def test_form_with_every_fieldtype_renders_and_validates():
    fields = [
        FormField(field_id=f"field_{ft.value}", field_type=ft, label=ft.value)
        for ft in FieldType
        # SELECT-family and scale types need well-formed inputs — covered
        # individually above; here we only need "never raises" over the rest.
        if ft
        not in (
            FieldType.SELECT,
            FieldType.MULTI_SELECT,
            FieldType.DYNAMIC_SELECT,
            FieldType.TAGS,
            FieldType.TRANSFER_LIST,
        )
    ]
    form = FormSchema(form_id="every", title="Every FieldType", sections=[FormSection(section_id="s", fields=fields)])

    renderer = A2UIFormRenderer()
    result = await renderer.render(form)
    surface_dict = _surface(result.content)
    surface_model = CreateSurface.model_validate(surface_dict)

    validate_envelope(surface_model, origin=ProducerOrigin.TOOL, surface_catalog_id=DEFAULT_CATALOG_ID)
