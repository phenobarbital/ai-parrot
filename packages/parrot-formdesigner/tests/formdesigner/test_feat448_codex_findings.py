"""FEAT-448 — regression tests for the seven adversarial-review findings.

Every test here fails against the pre-fix implementation. They are grouped in
one file on purpose: the findings share a single root cause, and it is the same
one the whole feature exists to close — **a catalog that only travels one
way.** A type could be rendered and not read back, a shape could be published
narrower than the validator accepts, and a control could be advertised as
native while submitting nothing under its own name.

Raw review output: `artifacts/reviews/FEAT-448-codex.txt` (fieldsync repo).
Triage: `sdd/reviews/FEAT-448-review.md`.
"""

from __future__ import annotations

import asyncio

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.extractors.jsonschema import JsonSchemaExtractor
from parrot_formdesigner.extractors.yaml import YamlExtractor
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
from parrot_formdesigner.services.validators import FormValidator

#: The twelve types FEAT-448 added. Every one must survive a round trip.
ABSORBED = [
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
    FieldType.PLACE,
]


def _one_field_form(field_type: FieldType) -> FormSchema:
    return FormSchema(
        form_id="f",
        title="T",
        sections=[
            FormSection(
                section_id="s",
                title="S",
                fields=[FormField(field_id="q", field_type=field_type, label="Q")],
            )
        ],
    )


# ── F1 — JSON Schema round trip ────────────────────────────────────────────


@pytest.mark.parametrize("field_type", ABSORBED, ids=lambda ft: ft.value)
def test_f1_jsonschema_round_trip_preserves_the_field_type(field_type: FieldType) -> None:
    """Render → extract must return the SAME type.

    Before the fix the extractor read only `format`, and only `place` had been
    added there — so `search` came back as TEXT, `tree_select` as ARRAY and
    `credit_card` as GROUP. The renderer had been stamping `x-field-type` on
    every property all along and nothing read it.
    """
    rendered = asyncio.run(JsonSchemaRenderer().render(_one_field_form(field_type)))
    import json

    schema = json.loads(rendered.content) if isinstance(rendered.content, str) else rendered.content
    recovered = JsonSchemaExtractor().extract(schema)
    got = recovered.sections[0].fields[0].field_type
    assert got == field_type, f"{field_type.value} round-tripped as {got.value}"


def test_f1_an_unknown_x_field_type_falls_back_instead_of_raising() -> None:
    """A marker we do not recognise must not take the whole schema down.

    The point of honouring the marker is robustness; a schema from a NEWER
    parrot must still parse here, degraded, rather than crash.
    """
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string", "x-field-type": "type_from_the_future"}},
    }
    form = JsonSchemaExtractor().extract(schema)
    assert form.sections[0].fields[0].field_type == FieldType.TEXT


# ── F3 — YAML ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field_type", ABSORBED, ids=lambda ft: ft.value)
def test_f3_yaml_resolves_every_type_by_its_own_name(field_type: FieldType) -> None:
    """`field_type: search` in YAML must not silently become a text field."""
    yaml_src = f"""
form_id: f
title: T
sections:
  - section_id: s
    title: S
    fields:
      - field_id: q
        field_type: {field_type.value}
        label: Q
"""
    form = YamlExtractor().extract(yaml_src)
    assert form.sections[0].fields[0].field_type == field_type


# ── F4 / F5 / F6 — the published shape must not be narrower than the validator


def _shape(field_type: FieldType) -> dict:
    from parrot_formdesigner.renderers.jsonschema import type_level_value_shape

    return type_level_value_shape(field_type)


def test_f4_tree_select_publishes_the_single_select_scalar_too() -> None:
    shape = _shape(FieldType.TREE_SELECT)
    assert "oneOf" in shape, "tree_select published only the multi-select array"
    kinds = {branch.get("type") for branch in shape["oneOf"]}
    assert kinds == {"string", "array"}


def test_f5_image_dropzone_publishes_the_multi_file_array_too() -> None:
    shape = _shape(FieldType.IMAGE_DROPZONE)
    assert "oneOf" in shape, "image_dropzone published only the single-file object"
    kinds = {branch.get("type") for branch in shape["oneOf"]}
    assert kinds == {"object", "array"}


def test_f6_ai_capture_publishes_no_constraint_at_all() -> None:
    """Its shape belongs to a third-party API. Publishing `object` rejected
    server-valid arrays and scalars."""
    assert _shape(FieldType.AI_CAPTURE) == {}


@pytest.mark.parametrize(
    "field_type,value",
    [
        (FieldType.TREE_SELECT, "single-node"),
        (FieldType.TREE_SELECT, ["a", "b"]),
        (FieldType.IMAGE_DROPZONE, {"name": "a.png", "type": "image/png", "size": 1, "dataUrl": "d"}),
        (FieldType.IMAGE_DROPZONE, [{"name": "a.png", "type": "image/png", "size": 1, "dataUrl": "d"}]),
        (FieldType.AI_CAPTURE, {"a": 1}),
        (FieldType.AI_CAPTURE, [1, 2, 3]),
        (FieldType.AI_CAPTURE, "a scalar"),
    ],
)
def test_f4_f5_f6_everything_the_validator_accepts_is_inside_the_published_shape(
    field_type: FieldType, value: object
) -> None:
    """The two must agree. This is the assertion the whole feature is for:
    a client asserting against the published catalog must never reject a value
    this server accepts."""
    result = asyncio.run(FormValidator().validate(_one_field_form(field_type), {"q": value}))
    assert result.is_valid, f"server rejected {value!r}: {result.errors}"

    shape = _shape(field_type)
    if shape == {}:
        return  # unconstrained: nothing to check, by design
    branches = shape.get("oneOf", [shape])
    json_kind = {
        str: "string", list: "array", dict: "object", int: "integer", float: "number", bool: "boolean",
    }[type(value)]
    assert any(b.get("type") == json_kind for b in branches), (
        f"{field_type.value} accepts a {json_kind} but does not publish one"
    )


# ── F7 — credit_card enforces its whole advertised shape ───────────────────


def test_f7_credit_card_requires_every_advertised_property() -> None:
    """`{"last4": "4242"}` alone used to be accepted and stored, while the
    published contract requires brand, last4, name and expiry."""
    result = asyncio.run(
        FormValidator().validate(_one_field_form(FieldType.CREDIT_CARD), {"q": {"last4": "4242"}})
    )
    assert not result.is_valid
    message = " ".join(result.errors["q"])
    for missing in ("brand", "name", "expiry"):
        assert missing in message


def test_f7_a_complete_card_reference_still_validates() -> None:
    result = asyncio.run(
        FormValidator().validate(
            _one_field_form(FieldType.CREDIT_CARD),
            {"q": {"brand": "visa", "last4": "4242", "name": "A CARDHOLDER", "expiry": "12/29"}},
        )
    )
    assert result.is_valid, result.errors


@pytest.mark.parametrize("forbidden", [{"cvv": "123"}, {"number": "4242424242424242"}])
def test_f7_cardholder_data_is_still_rejected_and_never_echoed(forbidden: dict) -> None:
    """The reject-not-sanitize rule survives the added required-property check,
    and no message quotes the offending value back into the logs."""
    payload = {"brand": "visa", "last4": "4242", "name": "A", "expiry": "12/29", **forbidden}
    result = asyncio.run(
        FormValidator().validate(_one_field_form(FieldType.CREDIT_CARD), {"q": payload})
    )
    assert not result.is_valid
    message = " ".join(result.errors["q"])
    for secret in forbidden.values():
        assert secret not in message


# ── F2 — the PLACE control submits under the field's own name ──────────────


def test_f2_place_controls_submit_under_the_field_name() -> None:
    """Three selects named `<field>_country` / `_state` / `_city` meant a plain
    form POST carried NOTHING for `<field>`: a required PLACE failed validation
    and an optional one was silently dropped."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    form = _one_field_form(FieldType.PLACE)
    html = asyncio.run(HTML5Renderer().render(form)).content

    for part in ("country", "state", "city"):
        assert f'name="q[{part}]"' in html, f"no control submits q[{part}]"
    assert 'name="q_country"' not in html, "the un-submittable naming is back"
