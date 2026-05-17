"""Unit tests for FieldType.REST in HTML5Renderer — FEAT-170."""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.html5 import HTML5Renderer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field() -> FormField:
    return FormField(
        field_id="planogram_photo",
        field_type=FieldType.REST,
        label={"en": "Planogram Photo"},
        required=True,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "planogram_compliance",
            }
        },
    )


@pytest.fixture
def form_with_rest(rest_field: FormField) -> FormSchema:
    return FormSchema(
        form_id="demo",
        title={"en": "Demo"},
        sections=[FormSection(section_id="s1", fields=[rest_field])],
    )


# ---------------------------------------------------------------------------
# HTML5 native REST rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_html5_rest_contains_file_input(form_with_rest: FormSchema) -> None:
    """HTML5 output must include <input type="file"> for REST field."""
    out = await HTML5Renderer().render(form_with_rest)
    assert isinstance(out, RenderedForm)
    assert '<input type="file"' in out.content


@pytest.mark.asyncio
async def test_html5_rest_contains_answer_hidden(form_with_rest: FormSchema) -> None:
    """HTML5 output must include hidden answer input."""
    out = await HTML5Renderer().render(form_with_rest)
    assert "answer" in out.content


@pytest.mark.asyncio
async def test_html5_rest_contains_blob_ref_hidden(form_with_rest: FormSchema) -> None:
    """HTML5 output must include hidden blob_ref input."""
    out = await HTML5Renderer().render(form_with_rest)
    assert "blob_ref" in out.content


@pytest.mark.asyncio
async def test_html5_rest_uses_uploader_div(form_with_rest: FormSchema) -> None:
    """HTML5 output must wrap REST field in parrot-rest-uploader div."""
    out = await HTML5Renderer().render(form_with_rest)
    assert "parrot-rest-uploader" in out.content


@pytest.mark.asyncio
async def test_html5_rest_no_warnings(form_with_rest: FormSchema) -> None:
    """HTML5 is a native REST renderer — no warnings should be emitted."""
    out = await HTML5Renderer().render(form_with_rest)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert rest_warnings == []


@pytest.mark.asyncio
async def test_html5_rest_content_type(form_with_rest: FormSchema) -> None:
    """HTML5 REST output must use text/html content type."""
    out = await HTML5Renderer().render(form_with_rest)
    assert out.content_type == "text/html"


# ---------------------------------------------------------------------------
# Additional args rendering
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
                        "label": "Tenant slug",
                    },
                    {
                        "name": "n",
                        "visibility": "public",
                        "data_type": "integer",
                        "value": 1,
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
async def test_html5_renders_public_args(form_with_args: FormSchema) -> None:
    """Public args must be rendered as visible <input> with their bare name."""
    out = await HTML5Renderer().render(form_with_args)
    assert 'name="tenant"' in out.content
    assert 'name="n"' in out.content


@pytest.mark.asyncio
async def test_html5_omits_private_args(form_with_args: FormSchema) -> None:
    """Private args MUST NOT appear in the rendered HTML."""
    out = await HTML5Renderer().render(form_with_args)
    assert 'name="prompt"' not in out.content
    assert "describe-this-image" not in out.content


@pytest.mark.asyncio
async def test_html5_public_int_arg_uses_number_input(form_with_args: FormSchema) -> None:
    """Integer-typed public arg renders as <input type='number'>."""
    out = await HTML5Renderer().render(form_with_args)
    assert 'name="n"' in out.content
    # Each public input carries its data-data-type attribute
    assert 'data-data-type="integer"' in out.content


@pytest.mark.asyncio
async def test_html5_public_required_arg_marked(form_with_args: FormSchema) -> None:
    """A required public arg renders with the 'required' attribute."""
    out = await HTML5Renderer().render(form_with_args)
    # Find the tenant input section
    tenant_html = out.content[out.content.index('name="tenant"'):]
    assert "required" in tenant_html.split(">", 1)[0]
