"""Unit tests for FieldType.REST in JsonSchemaRenderer — FEAT-170."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field_callback() -> FormField:
    return FormField(
        field_id="planogram_photo",
        field_type=FieldType.REST,
        label={"en": "Planogram Photo"},
        required=True,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "planogram_compliance",
                "response_path": "$.compliance_score",
                "display_template": "Score: {{ answer }}",
            }
        },
    )


@pytest.fixture
def form_with_rest(rest_field_callback: FormField) -> FormSchema:
    return FormSchema(
        form_id="demo",
        title={"en": "Demo"},
        sections=[FormSection(section_id="s1", fields=[rest_field_callback])],
    )


# ---------------------------------------------------------------------------
# JSON Schema native REST rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jsonschema_rest_type_is_object(form_with_rest: FormSchema) -> None:
    """JSON Schema REST property must have type=object."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    assert prop["type"] == "object"


@pytest.mark.asyncio
async def test_jsonschema_rest_has_answer_property(form_with_rest: FormSchema) -> None:
    """JSON Schema REST property must include properties.answer."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    assert "answer" in prop.get("properties", {})


@pytest.mark.asyncio
async def test_jsonschema_rest_has_blob_ref_property(form_with_rest: FormSchema) -> None:
    """JSON Schema REST property must include properties.blob_ref as nullable string."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    blob_ref = prop.get("properties", {}).get("blob_ref", {})
    assert blob_ref.get("type") == ["string", "null"]


@pytest.mark.asyncio
async def test_jsonschema_rest_required_answer(form_with_rest: FormSchema) -> None:
    """JSON Schema REST property must require answer key."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    assert "answer" in prop.get("required", [])


@pytest.mark.asyncio
async def test_jsonschema_rest_has_x_parrot_rest(form_with_rest: FormSchema) -> None:
    """JSON Schema REST property must include x-parrot-rest extension."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    assert "x-parrot-rest" in prop


@pytest.mark.asyncio
async def test_jsonschema_rest_x_parrot_rest_mode(form_with_rest: FormSchema) -> None:
    """x-parrot-rest must carry the mode from meta.rest."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    assert prop["x-parrot-rest"]["mode"] == "callback"


@pytest.mark.asyncio
async def test_jsonschema_rest_x_parrot_rest_response_path(form_with_rest: FormSchema) -> None:
    """x-parrot-rest must carry response_path from meta.rest."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    assert prop["x-parrot-rest"]["response_path"] == "$.compliance_score"


@pytest.mark.asyncio
async def test_jsonschema_rest_upload_url_template(form_with_rest: FormSchema) -> None:
    """x-parrot-rest must include the upload_url_template."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    prop = out.content["properties"]["planogram_photo"]
    assert "upload_url_template" in prop["x-parrot-rest"]
    assert "{form_id}" in prop["x-parrot-rest"]["upload_url_template"]


@pytest.mark.asyncio
async def test_jsonschema_rest_no_warnings(form_with_rest: FormSchema) -> None:
    """JSON Schema is a native REST renderer — no warnings should be emitted."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert rest_warnings == []


@pytest.mark.asyncio
async def test_jsonschema_rest_content_type(form_with_rest: FormSchema) -> None:
    """JSON Schema REST output must use application/schema+json content type."""
    out = await JsonSchemaRenderer().render(form_with_rest)
    assert out.content_type == "application/schema+json"


# ---------------------------------------------------------------------------
# Additional args in x-parrot-rest extension
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field_with_args() -> FormField:
    return FormField(
        field_id="image_analyze",
        field_type=FieldType.REST,
        label={"en": "Analyze"},
        required=True,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "image_analyze",
                "additional_args": [
                    {
                        "name": "prompt",
                        "visibility": "private",
                        "value": "describe-this-image",
                    },
                    {
                        "name": "tenant",
                        "visibility": "public",
                        "required": True,
                        "label": "Tenant",
                        "description": "Tenant slug",
                    },
                    {
                        "name": "n",
                        "visibility": "public",
                        "data_type": "integer",
                        "value": 3,
                    },
                ],
            }
        },
    )


@pytest.fixture
def form_with_args(rest_field_with_args: FormField) -> FormSchema:
    return FormSchema(
        form_id="form-args",
        title={"en": "Args"},
        sections=[FormSection(section_id="s1", fields=[rest_field_with_args])],
    )


@pytest.mark.asyncio
async def test_jsonschema_emits_additional_args(form_with_args: FormSchema) -> None:
    """x-parrot-rest.additional_args reflects spec exactly (round-trippable)."""
    out = await JsonSchemaRenderer().render(form_with_args)
    rest_ext = out.content["properties"]["image_analyze"]["x-parrot-rest"]

    assert "additional_args" in rest_ext
    names = [a["name"] for a in rest_ext["additional_args"]]
    assert names == ["prompt", "tenant", "n"]
    # Private arg is preserved in the round-trippable list
    private = next(a for a in rest_ext["additional_args"] if a["name"] == "prompt")
    assert private["visibility"] == "private"
    assert private["value"] == "describe-this-image"


@pytest.mark.asyncio
async def test_jsonschema_public_args_projection(form_with_args: FormSchema) -> None:
    """x-parrot-rest.public_args lists ONLY the renderable args."""
    out = await JsonSchemaRenderer().render(form_with_args)
    rest_ext = out.content["properties"]["image_analyze"]["x-parrot-rest"]

    names = [a["name"] for a in rest_ext["public_args"]]
    assert names == ["tenant", "n"]  # prompt (private) excluded
    assert "visibility" not in rest_ext["public_args"][0]  # projection drops it

    tenant = next(a for a in rest_ext["public_args"] if a["name"] == "tenant")
    assert tenant["required"] is True
    assert tenant["data_type"] == "string"
    assert tenant["label"] == "Tenant"

    n = next(a for a in rest_ext["public_args"] if a["name"] == "n")
    assert n["data_type"] == "integer"
    assert n["default"] == 3
    assert n["required"] is False
