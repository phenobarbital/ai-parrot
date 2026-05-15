"""Unit tests for FieldType.REST fallback in PdfRenderer — FEAT-170."""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfReader

from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection, RenderedForm
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers.pdf import PdfRenderer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rest_field() -> FormField:
    return FormField(
        field_id="upload_photo",
        field_type=FieldType.REST,
        label={"en": "Upload Photo"},
        required=False,
        meta={
            "rest": {
                "mode": "callback",
                "callback_ref": "photo_analysis",
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
# PDF fallback REST rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_rest_fallback_warns(form_with_rest: FormSchema) -> None:
    """PdfRenderer must emit RenderWarning for FieldType.REST."""
    out = await PdfRenderer().render(form_with_rest)
    assert isinstance(out, RenderedForm)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert len(rest_warnings) >= 1


@pytest.mark.asyncio
async def test_pdf_rest_warning_field_id(form_with_rest: FormSchema) -> None:
    """RenderWarning must reference the correct field_id."""
    out = await PdfRenderer().render(form_with_rest)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert rest_warnings[0].field_id == "upload_photo"


@pytest.mark.asyncio
async def test_pdf_rest_warning_renderer(form_with_rest: FormSchema) -> None:
    """RenderWarning must identify renderer as 'pdf'."""
    out = await PdfRenderer().render(form_with_rest)
    rest_warnings = [w for w in out.warnings if w.field_type == "rest"]
    assert rest_warnings[0].renderer == "pdf"


@pytest.mark.asyncio
async def test_pdf_rest_still_produces_pdf(form_with_rest: FormSchema) -> None:
    """PdfRenderer must still produce valid PDF bytes even with a REST field."""
    out = await PdfRenderer().render(form_with_rest)
    assert out.content_type == "application/pdf"
    reader = PdfReader(BytesIO(out.content))
    assert len(reader.pages) >= 1
