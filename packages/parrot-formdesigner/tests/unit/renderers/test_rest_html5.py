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
